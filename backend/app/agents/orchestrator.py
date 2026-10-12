from dataclasses import dataclass
import hashlib
import os
import re
import time

from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.core.config import Settings, get_settings
from app.tools.mermaid_validator import validate_mermaid

@dataclass
class AgentResult:
    mermaid_code: str
    node_mapping: dict
    agent_logs: list[dict]
    # 这些字段用于让调用方区分“有业务证据的图”和仅用于导航的结构视图。
    # 暂不把它们加入 Diagram 表；P3-06 再迁移为正式图表字段。
    generation_mode: str = "structural_fallback"
    reason: str = ""
    quality_status: str = "degraded"


@dataclass(frozen=True)
class SourceFileContext:
    id: int
    relative_path: str
    language: str | None
    line_count: int
    file_hash: str | None


@dataclass(frozen=True)
class SymbolContext:
    id: int
    file_id: int
    name: str
    kind: str
    qualified_name: str | None
    start_line: int | None
    end_line: int | None
    signature: str | None


@dataclass(frozen=True)
class CodeChunkContext:
    id: int
    file_id: int
    chunk_type: str
    symbol_name: str | None
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True)
class AnalysisContextSnapshot:
    source_files: tuple[SourceFileContext, ...]
    symbols: tuple[SymbolContext, ...]
    chunks: tuple[CodeChunkContext, ...]


def safe_label(text: str, max_len: int = 40) -> str:
    text = (text or "").replace("[", "(").replace("]", ")")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("|", "-").replace('"', "'")
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text or "unknown"


def safe_id(text: str, prefix: str = "N") -> str:
    value = re.sub(r"[^0-9a-zA-Z_]", "_", text or "")
    value = value.strip("_")

    if not value:
        value = prefix

    if value[0].isdigit():
        value = f"{prefix}_{value}"

    return value[:60]


class AgentOrchestrator:
    """基于数据库解析结果生成 Mermaid，并可选接入 Agent 负责人提供的 LLM 链路。

    集成原则：
    1. 保留前后端联调版本的 DB 检索、源码映射、文件范围过滤能力。
    2. LLM 只作为增强生成器；未配置或调用失败时自动回退到规则生成图。
    3. 返回结构保持 AgentResult，便于 DiagramService 保存 diagram 和 agent_runs。
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.llm_enabled = self.settings.llm_model_enabled
        self.llm_model = self.settings.llm_model
        self.max_context_chars = self.settings.llm_max_context_chars
        self._llm_usage: dict = {}

    def _public_llm_error(self, error: str | None) -> str:
        """只把可操作的校验原因展示给用户，不泄露请求 URL、密钥或内部异常。"""
        text = (error or "").strip()
        safe_markers = ("图表类型不匹配", "缺少合法的Mermaid图表声明", "双引号未闭合", "Mermaid源码不能为空")
        for marker in safe_markers:
            if marker in text:
                return marker
        return "模型调用失败或输出未通过校验"

    def run_analysis(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str = "flowchart",
        db: Session | None = None,
        project_id: int | None = None,
        scope_paths: list[str] | None = None,
        snapshot: AnalysisContextSnapshot | None = None,
    ) -> AgentResult:
        """执行 DB 检索 -> Mermaid 生成 -> 可选 LLM 优化 -> 校验。"""
        if snapshot is None and (db is None or project_id is None):
            return self._run_without_db_or_fallback(project_name, prompt, diagram_type)

        logs: list[dict] = []

        try:
            start = time.time()
            if snapshot is None:
                source_files = (
                    db.query(SourceFile)
                    .filter(SourceFile.project_id == project_id)
                    .order_by(SourceFile.relative_path.asc())
                    .all()
                )
            else:
                source_files = list(snapshot.source_files)

            if scope_paths is not None:
                selected = set(scope_paths)
                source_files = [f for f in source_files if f.relative_path in selected]

            if not source_files:
                result = self._fallback(
                    project_name,
                    prompt,
                    diagram_type,
                    reason="项目没有已解析源码文件，无法确认仓库业务语义",
                )
                result.agent_logs.append(
                    self._log(
                        "RetrievalAgent",
                        project_name,
                        "未找到已解析源码文件，使用兜底 Mermaid",
                        start,
                    )
                )
                return result

            file_ids = {f.id for f in source_files}
            if snapshot is None:
                symbols = (
                    db.query(Symbol)
                    .filter(Symbol.project_id == project_id, Symbol.file_id.in_(file_ids))
                    .order_by(Symbol.file_id.asc(), Symbol.start_line.asc(), Symbol.name.asc())
                    .all()
                )
                chunks = (
                    db.query(CodeChunk)
                    .filter(CodeChunk.project_id == project_id, CodeChunk.file_id.in_(file_ids))
                    .order_by(CodeChunk.file_id.asc(), CodeChunk.start_line.asc())
                    .all()
                )
            else:
                symbols = [symbol for symbol in snapshot.symbols if symbol.file_id in file_ids]
                chunks = [chunk for chunk in snapshot.chunks if chunk.file_id in file_ids]

            logs.append(
                self._log(
                    "RetrievalAgent",
                    f"项目名: {project_name}",
                    f"读取源码文件 {len(source_files)} 个，符号 {len(symbols)} 个，代码块 {len(chunks)} 个",
                    start,
                )
            )

            # 先用已验证的规则生成器产出稳定结果和精准源码映射，作为兜底。
            start = time.time()
            rule_mermaid, mapping = self._build_by_type(
                project_name, prompt, diagram_type, source_files, symbols, chunks
            )
            rule_validation = validate_mermaid(rule_mermaid)
            logs.append(
                self._log(
                    "RuleDiagramAgent",
                    diagram_type,
                    "规则图生成完成" if rule_validation.valid else ";".join(rule_validation.errors),
                    start,
                    None if rule_validation.valid else ";".join(rule_validation.errors),
                )
            )

            final_mermaid = rule_mermaid
            code_context = self._build_code_context(source_files, symbols, chunks, prompt=prompt)
            has_evidence = bool(symbols or chunks)
            generation_mode = "structural_fallback"
            quality_status = "degraded"
            reason = (
                "解析结果没有可用的符号或代码块，无法验证仓库业务语义；"
                "当前结果仅作为结构视图"
                if not has_evidence
                else "LLM 未启用；当前结果仅依据解析结构表示文件包含关系，未验证业务语义"
            )

            # 再尝试使用 agent 负责人提供的大模型链路增强图表表达。
            if self.llm_enabled and has_evidence:
                start = time.time()
                llm_mermaid, llm_error = self._try_llm_mermaid(
                    project_name=project_name,
                    prompt=prompt,
                    diagram_type=diagram_type,
                    code_context=code_context,
                    node_hints=self._build_node_hints(mapping),
                    baseline_mermaid=rule_mermaid,
                )
                if llm_mermaid:
                    final_mermaid = llm_mermaid
                    mapping = self._augment_mapping_for_mermaid(final_mermaid, mapping, code_context)
                    generation_mode = "business"
                    quality_status = "unverified"
                    reason = "LLM 已基于源码上下文生成并通过文本预检查，但未完成业务关系或完整 Mermaid 语法验证"
                elif self.llm_enabled:
                    reason = (
                        f"{self._public_llm_error(llm_error)}；已回退为仅表示解析结构的结构视图"
                    )

                logs.append(
                    self._log(
                        "DiagramAgent",
                        f"Prompt长度: {len(prompt)}, 上下文长度: {len(code_context)}",
                        "LLM Mermaid 生成成功" if llm_mermaid else "LLM 不可用或生成无效，沿用规则图",
                        start,
                        llm_error,
                        model_name=self.llm_model,
                        usage=self._llm_usage,
                    )
                )
            elif not self.llm_enabled:
                logs.append(
                    self._log(
                        "DiagramAgent",
                        "LLM_ENABLED/LLM_API_KEY",
                        "未启用 LLM，沿用规则图",
                    )
                )
            else:
                logs.append(
                    self._log(
                        "DiagramAgent",
                        "解析证据",
                        "缺少符号或代码块，跳过 LLM，沿用结构视图",
                    )
                )

            start = time.time()
            validation = validate_mermaid(final_mermaid, expected_type=diagram_type)
            review_error = None
            if not validation.valid:
                review_error = ";".join(validation.errors)
                if rule_validation.valid:
                    final_mermaid = rule_mermaid
                else:
                    fallback = self._fallback(
                        project_name,
                        prompt,
                        diagram_type,
                        reason="规则图和 LLM 结果均未通过 Mermaid 校验",
                    )
                    final_mermaid = fallback.mermaid_code
                generation_mode = "structural_fallback"
                quality_status = "degraded"
                reason = f"{reason}；{review_error}"

            logs.append(
                self._log(
                    "ReviewAgent",
                    "待校验的 Mermaid 文本",
                    "校验通过" if not review_error else "校验失败，已回退到规则图",
                    start,
                    review_error,
                )
            )

            if "上下文省略" in code_context:
                reason += "；Provider 上下文已省略部分源码，未展示证据不能作为完整业务依据"
            if "证据不足" in code_context:
                reason += "；目标代码证据不足，请结合完整源码核对"

            logs.append(
                self._log(
                    "GenerationQualityAgent",
                    diagram_type,
                    f"generation_mode={generation_mode}; quality_status={quality_status}; reason={reason}",
                )
            )
            return AgentResult(
                mermaid_code=final_mermaid,
                node_mapping=mapping,
                agent_logs=logs,
                generation_mode=generation_mode,
                reason=reason,
                quality_status=quality_status,
            )

        except Exception:
            result = self._fallback(
                project_name,
                prompt,
                diagram_type,
                reason="生成异常，缺少可验证结果",
            )
            result.agent_logs.append(
                self._log(
                    "ErrorGuard",
                    diagram_type,
                    "生成异常，已降级为占位图",
                    error="internal generation failure",
                )
            )
            return result

    def _run_without_db_or_fallback(self, project_name: str, prompt: str, diagram_type: str) -> AgentResult:
        """兼容 agent 负责人原始测试：没有 DB 时可尝试本地路径检索，否则回退。"""
        if not self.llm_enabled:
            return self._fallback(
                project_name,
                prompt,
                diagram_type,
                reason="未启用 LLM 且没有数据库源码上下文，无法确认仓库业务语义",
            )

        start = time.time()
        try:
            from app.agents.retrieval import simple_code_retrieval

            project_path = os.getenv("PROJECT_ROOT_PATH")
            if not project_path:
                return self._fallback(
                    project_name,
                    prompt,
                    diagram_type,
                    reason="未提供数据库上下文或明确的项目源码路径，无法读取服务器当前工作目录",
                )
            code_context = simple_code_retrieval(project_path, prompt[:20].strip())
            llm_mermaid, error = self._try_llm_mermaid(
                project_name=project_name,
                prompt=prompt,
                diagram_type=diagram_type,
                code_context=code_context,
                node_hints="A/B/C 等通用节点 ID",
                baseline_mermaid="",
            )
            if llm_mermaid and code_context and "没有可用代码块" not in code_context:
                mapping = self._augment_mapping_for_mermaid(llm_mermaid, {}, code_context)
                return AgentResult(
                    mermaid_code=llm_mermaid,
                    node_mapping=mapping,
                    agent_logs=[self._log("RetrievalAgent", project_path, f"本地检索上下文长度: {len(code_context)}", start),
                                self._log("DiagramAgent", prompt[:200], "LLM Mermaid 生成成功", error=error, model_name=self.llm_model, usage=self._llm_usage)],
                    generation_mode="business",
                    reason="LLM 已基于本地检索源码生成并通过文本预检查，但未完成业务关系或完整 Mermaid 语法验证",
                    quality_status="unverified",
                )
        except Exception:
            pass

        return self._fallback(
            project_name,
            prompt,
            diagram_type,
            reason="未提供数据库上下文或没有可验证源码证据，无法确认仓库业务语义",
        )

    def _build_by_type(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> tuple[str, dict]:
        diagram_type_key = (diagram_type or "flowchart").lower()
        if diagram_type_key in ("sequence", "sequencediagram"):
            return self._build_sequence_diagram(project_name, prompt, source_files, symbols, chunks)
        if diagram_type_key in ("state", "statediagram"):
            return self._build_state_diagram(project_name, prompt, source_files, symbols, chunks)
        if diagram_type_key in ("architecture", "class", "classdiagram"):
            return self._build_class_diagram(project_name, prompt, source_files, symbols, chunks)
        return self._build_flowchart(project_name, prompt, source_files, symbols, chunks)

    def _try_llm_mermaid(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str,
        code_context: str,
        node_hints: str,
        baseline_mermaid: str,
    ) -> tuple[str | None, str | None]:
        self._llm_usage = {}
        try:
            from app.agents.llm_provider import LLMProvider, LLMResult
            from app.agents.prompts import MERMAID_SYSTEM_PROMPT, MERMAID_USER_TEMPLATE

            llm = LLMProvider(model=self.llm_model, settings=self.settings)
            user_content = MERMAID_USER_TEMPLATE.format(
                project_name=project_name,
                user_prompt=prompt,
                diagram_type=diagram_type,
                diagram_header=self._diagram_header(diagram_type),
                node_hints=node_hints,
                baseline_mermaid=baseline_mermaid[:4000],
                code_context=code_context,
            )
            try:
                output = llm.chat(system_prompt=MERMAID_SYSTEM_PROMPT, user_prompt=user_content)
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    close()
            if isinstance(output, LLMResult):
                self._llm_usage = {"prompt_tokens": output.prompt_tokens,
                                   "completion_tokens": output.completion_tokens,
                                   "usage_collected": output.prompt_tokens is not None and output.completion_tokens is not None}
                output = output.content
            # Local/legacy providers returning only text have unknown usage.
            mermaid_code = self._strip_markdown_fences(output)

            if (diagram_type or "").lower() in {"state", "statediagram", "statediagram-v2"}:
                mermaid_code = self._repair_state_diagram(mermaid_code)

            validation = validate_mermaid(mermaid_code, expected_type=diagram_type)
            if not validation.valid:
                return None, ";".join(validation.errors)
            return mermaid_code, None
        except Exception:
            return None, "模型调用或结果校验失败"
    
    def _repair_state_diagram(self, mermaid_code: str) -> str:
        """修复 LLM 常见的非法 stateDiagram 写法。

        只修复箭头两边直接使用引号文本的情况，例如：
            [*] --> "未登录"
            "未登录" --> "已登录": 登录成功
    
        不修改合法的状态定义：
            state "未登录" as S1
        """
        if not mermaid_code or "stateDiagram" not in mermaid_code:
            return mermaid_code

        lines = mermaid_code.splitlines()
        if not lines:
            return mermaid_code

        header = lines[0].strip()
        body_lines = lines[1:]

        label_to_id: dict[str, str] = {}

        # 先收集已有的合法 state 定义，避免重复定义
        existing_state_def_lines: list[str] = []
        used_ids: set[str] = set()

        state_def_pattern = re.compile(r'^\s*state\s+"([^"]+)"\s+as\s+([A-Za-z][A-Za-z0-9_]*)\s*$')

        for line in body_lines:
            match = state_def_pattern.match(line)
            if match:
                label, state_id = match.group(1), match.group(2)
                label_to_id[label] = state_id
                used_ids.add(state_id)
                existing_state_def_lines.append(line)

        # 端点中已有的裸标识符也属于当前 Mermaid 作用域；否则首次遇到
        # 引号标签时可能复用 S1，改写成自环并改变原有转移含义。
        bare_endpoint_pattern = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)(?![A-Za-z0-9_])")
        for line in body_lines:
            if "-->" not in line:
                continue
            transition = line.split(":", 1)[0]
            for token in bare_endpoint_pattern.findall(transition):
                if token not in {"state", "stateDiagram", "direction", "done"}:
                    used_ids.add(token)

        def new_state_id(label: str) -> str:
            if label in label_to_id:
                return label_to_id[label]

            index = len(label_to_id) + 1
            state_id = f"S{index}"
            while state_id in used_ids:
                index += 1
                state_id = f"S{index}"

            label_to_id[label] = state_id
            used_ids.add(state_id)
            return state_id

        repaired_body: list[str] = []
        endpoint_pattern = re.compile(r'(?P<endpoint>\[[*]\]|"[^"]+")')

        for line in body_lines:
            stripped = line.strip()

            # 合法 state 定义行不要替换，否则会把 state "xxx" as S1 修坏
            if state_def_pattern.match(line):
                repaired_body.append(line)
                continue

            new_line = line
            # 只替换箭头两侧的端点；冒号后的边注释即使带引号也必须保留。
            if "-->" in line:
                arrow_index = line.index("-->")
                left = line[:arrow_index]
                right = line[arrow_index + 3 :]

                def replace_endpoint(match: re.Match[str]) -> str:
                    token = match.group("endpoint")
                    if token == "[*]":
                        return token
                    label = token[1:-1]
                    return new_state_id(label)

                left_match = list(endpoint_pattern.finditer(left))
                if left_match:
                    match = left_match[-1]
                    left = left[: match.start()] + replace_endpoint(match) + left[match.end() :]
                right_target = right.split(":", 1)[0]
                right_match = endpoint_pattern.search(right_target)
                if right_match:
                    right = (
                        right[: right_match.start()]
                        + replace_endpoint(right_match)
                        + right[right_match.end() :]
                    )
                new_line = left + "-->" + right

            repaired_body.append(new_line)

        # 给新出现但原来没有定义的中文状态补 state 定义
        defined_labels = {
            match.group(1)
            for line in body_lines
            for match in [state_def_pattern.match(line)]
            if match
        }

        state_defs: list[str] = []
        for label, state_id in label_to_id.items():
            if label not in defined_labels:
                state_defs.append(f'    state "{label}" as {state_id}')

        return "\n".join([header, *state_defs, *repaired_body])
    
    def _build_code_context(
        self,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
        prompt: str = "",
    ) -> str:
        from app.agents.context_builder import build_code_context

        return build_code_context(source_files, symbols, chunks, prompt, self.max_context_chars)

    def _build_node_hints(self, mapping: dict) -> str:
        hints: list[str] = []
        for key, info in mapping.items():
            key_text = str(key)
            if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", key_text):
                continue
            if not isinstance(info, dict):
                continue
            hints.append(
                f"{key_text}: {info.get('file_path') or 'unresolved'}:{info.get('start_line') or '?'}-{info.get('end_line') or '?'}"
            )
            if len(hints) >= 80:
                break
        return "\n".join(hints) or "无"

    def _augment_mapping_for_mermaid(self, mermaid_code: str, mapping: dict, code_context: str) -> dict:
        """为 LLM 新增的节点保留未定位状态，不伪造源码路径和行号。"""

        unresolved = {
            "file_id": None,
            "symbol_id": None,
            "file_hash": None,
            "file_path": None,
            "start_line": None,
            "end_line": None,
            "code": "",
            "unresolved": True,
            "reason": "LLM 节点未能匹配到已解析文件或符号；需要进一步证据定位",
        }
        patterns = [
            r"\b([A-Za-z][A-Za-z0-9_]*)\s*(?:\[|\(|\{)",
            r"\bclass\s+([A-Za-z][A-Za-z0-9_]*)",
            r"\bparticipant\s+([A-Za-z][A-Za-z0-9_]*)",
            r"\bas\s+([A-Za-z][A-Za-z0-9_]*)",
        ]
        for pattern in patterns:
            for node_id in re.findall(pattern, mermaid_code):
                mapping.setdefault(node_id, dict(unresolved))
        return mapping

    @staticmethod
    def _stable_node_id(prefix: str, file_path: str, qualified_name: str | None = None) -> str:
        """根据完整路径和限定符号名生成跨排序稳定的 Mermaid 节点 ID。"""

        normalized_path = file_path.replace("\\", "/")
        identity = f"{normalized_path}{qualified_name or ''}"
        digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
        readable = safe_id(qualified_name or file_path, prefix)[:36]
        return f"{prefix}_{readable}_{digest}"

    def _symbol_node_id(self, prefix: str, source_file: SourceFile, symbol: Symbol) -> str:
        qualified = symbol.qualified_name or symbol.name
        # 行范围是同一文件内重复限定名时的确定性消歧信息；不会依赖列表顺序。
        identity = f"{qualified}@{symbol.start_line or 0}:{symbol.end_line or symbol.start_line or 0}"
        return self._stable_node_id(prefix, source_file.relative_path, identity)

    @staticmethod
    def _source_info(
        source_file: SourceFile,
        *,
        code: str = "",
        start_line: int | None = 1,
        end_line: int | None = 1,
        symbol: Symbol | None = None,
        unresolved: bool = False,
        reason: str | None = None,
    ) -> dict:
        info = {
            "file_id": source_file.id,
            "symbol_id": symbol.id if symbol is not None else None,
            "file_hash": source_file.file_hash,
            "file_path": source_file.relative_path,
            "start_line": start_line,
            "end_line": end_line,
            "code": code or "",
            "unresolved": unresolved,
        }
        if reason:
            info["reason"] = reason
        return info

    @staticmethod
    def _unresolved_source_info(reason: str) -> dict:
        return {
            "file_id": None,
            "symbol_id": None,
            "file_hash": None,
            "file_path": None,
            "start_line": None,
            "end_line": None,
            "code": "",
            "unresolved": True,
            "reason": reason,
        }

    @staticmethod
    def _put_mapping(mapping: dict, key: str, value: dict) -> None:
        """只在没有同名键时写入别名，避免同名符号互相覆盖。"""

        if key and key not in mapping:
            mapping[key] = value

    @staticmethod
    def _diagram_header(diagram_type: str) -> str:
        diagram_type_key = (diagram_type or "flowchart").lower()
        if diagram_type_key in ("sequence", "sequencediagram"):
            return "sequenceDiagram"
        if diagram_type_key in ("state", "statediagram"):
            return "stateDiagram-v2"
        if diagram_type_key in ("architecture", "class", "classdiagram"):
            return "classDiagram"
        return "flowchart TD"

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        return stripped

    @staticmethod
    def _log(
        agent_name: str,
        input_summary: str | None,
        output_summary: str | None,
        start_time: float | None = None,
        error: str | None = None,
        model_name: str | None = None,
        usage: dict | None = None,
    ) -> dict:
        return {
            "agent_name": agent_name,
            "input_summary": (input_summary or "")[:500],
            "output_summary": (output_summary or "")[:1000],
            "duration_sec": round(time.time() - start_time, 3) if start_time else 0,
            "errors": error,
            "model_name": model_name,
            **(usage or {}),
        }

    def _build_flowchart(
        self,
        project_name: str,
        prompt: str,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> tuple[str, dict]:
        lines = ["flowchart TD"]
        mapping: dict = {}
        max_edges = 450
        max_chars = 44000
        edge_count = 0
        omitted = False

        def append(line: str, edge: bool = False) -> bool:
            nonlocal edge_count, omitted
            if edge and edge_count >= max_edges:
                omitted = True
                return False
            if sum(len(item) + 1 for item in lines) + len(line) > max_chars:
                omitted = True
                return False
            lines.append(line)
            if edge:
                edge_count += 1
            return True

        project_node = "P"
        project_label = f"项目：{safe_label(project_name)}"
        project_info = self._unresolved_source_info("项目结构节点不对应单个源码位置")
        append(f'    {project_node}["{project_label}（结构包含视图）"]')
        mapping[project_node] = project_info
        mapping[project_label] = project_info

        symbols_by_file = self._group_symbols_by_file(symbols)
        chunks_by_file = self._group_chunks_by_file(chunks)
        for source_file in source_files:
            file_node = self._stable_node_id("File", source_file.relative_path)
            file_label = f"文件：{safe_label(source_file.relative_path)}"
            if not append(f'    {project_node} --> {file_node}["{file_label}"]', edge=True):
                break
            file_chunks = chunks_by_file.get(source_file.id, [])
            file_source_info = self._source_info(
                source_file,
                code=self._merge_file_chunks(file_chunks),
                start_line=1,
                end_line=source_file.line_count or 1,
            )
            self._put_mapping(mapping, file_node, file_source_info)
            self._put_mapping(mapping, file_label, file_source_info)
            file_symbols = symbols_by_file.get(source_file.id, [])
            if file_symbols:
                for symbol in file_symbols[:8]:
                    symbol_node = self._symbol_node_id("Sym", source_file, symbol)
                    symbol_label = safe_label(f"{symbol.kind}: {symbol.name}")
                    if not append(f'    {file_node} --> {symbol_node}["{symbol_label}"]', edge=True):
                        break
                    related_chunk = self._find_chunk_for_symbol(symbol, file_chunks)
                    info = self._source_info(
                        source_file,
                        start_line=symbol.start_line or 1,
                        end_line=symbol.end_line or symbol.start_line or 1,
                        code=related_chunk.content if related_chunk else symbol.signature or "",
                        symbol=symbol,
                    )
                    self._put_mapping(mapping, symbol_node, info)
                    self._put_mapping(mapping, symbol_label, info)
            else:
                for chunk in file_chunks[:5]:
                    chunk_node = self._stable_node_id(
                        "Chunk", source_file.relative_path, chunk.symbol_name or f"{chunk.start_line}-{chunk.end_line}"
                    )
                    chunk_label = f"代码块：{safe_label(chunk.symbol_name or chunk.chunk_type or '代码块')}"
                    if not append(f'    {file_node} --> {chunk_node}["{chunk_label}"]', edge=True):
                        break
                    info = self._source_info(
                        source_file, start_line=chunk.start_line, end_line=chunk.end_line, code=chunk.content
                    )
                    self._put_mapping(mapping, chunk_node, info)
                    self._put_mapping(mapping, chunk_label, info)

        if omitted:
            omitted_id = "UnresolvedOmitted"
            # 正文上限预留了提示空间，提示本身不能再次被正文预算拒绝。
            lines.append(f'    {omitted_id}["已省略部分内容；请缩小文件选择范围"]')
            mapping[omitted_id] = self._unresolved_source_info("达到流程图规模上限")
        return "\n".join(lines), mapping

    def _build_sequence_diagram(
        self,
        project_name: str,
        prompt: str,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> tuple[str, dict]:
        lines = ["sequenceDiagram"]
        mapping: dict = {}

        lines.append("    participant U as 用户")

        usable_files = source_files[:6]
        chunks_by_file = self._group_chunks_by_file(chunks)

        for source_file in usable_files:
            alias = self._stable_node_id("File", source_file.relative_path)
            display_name = safe_label(source_file.relative_path, 24)
            lines.append(f"    participant {alias} as {display_name}")

            file_source_info = self._source_info(
                source_file,
                code=self._merge_file_chunks(chunks_by_file.get(source_file.id, [])),
                start_line=1,
                end_line=source_file.line_count or 1,
            )
            self._put_mapping(mapping, alias, file_source_info)
            self._put_mapping(mapping, display_name, file_source_info)

        if not usable_files:
            lines.append("    Note over U: 暂无可验证源码证据，未生成业务调用链")
        elif len(usable_files) == 1:
            alias = self._stable_node_id("File", usable_files[0].relative_path)
            lines.append(f"    Note over {alias}: 仅列出解析到的文件参与者；未验证文件间关系")
        else:
            first = self._stable_node_id("File", usable_files[0].relative_path)
            last = self._stable_node_id("File", usable_files[-1].relative_path)
            lines.append(f"    Note over {first},{last}: 仅列出解析到的文件参与者；未验证文件间关系")

        return "\n".join(lines), mapping

    def _build_state_diagram(
        self,
        project_name: str,
        prompt: str,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> tuple[str, dict]:
        lines = [
            "stateDiagram-v2",
            "    [*] --> Parsed",
            '    state "源码已解析" as Parsed',
        ]

        mapping: dict = {
            "Parsed": self._unresolved_source_info("解析状态节点不对应单个源码位置")
        }

        chunks_by_file = self._group_chunks_by_file(chunks)

        for index, source_file in enumerate(source_files[:8], start=1):
            state_node = self._stable_node_id("File", source_file.relative_path)
            label = safe_label(source_file.relative_path, 24)

            lines.append(f'    state "{label}" as {state_node}')
            lines.append(f"    Parsed --> {state_node}")

            source_info = self._source_info(
                source_file,
                code=self._merge_file_chunks(chunks_by_file.get(source_file.id, [])),
                start_line=1,
                end_line=source_file.line_count or 1,
            )

            self._put_mapping(mapping, state_node, source_info)
            self._put_mapping(mapping, label, source_info)

        return "\n".join(lines), mapping

    def _build_class_diagram(
        self,
        project_name: str,
        prompt: str,
        source_files: list[SourceFile],
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> tuple[str, dict]:
        lines = ["classDiagram"]
        mapping: dict = {}
        node_count = 0
        omitted = False
        max_nodes = 80

        symbols_by_file = self._group_symbols_by_file(symbols)
        chunks_by_file = self._group_chunks_by_file(chunks)

        for source_file in source_files:
            if not source_file.relative_path.lower().endswith(".py"):
                continue
            if node_count >= max_nodes:
                omitted = True
                break
            file_symbols = symbols_by_file.get(source_file.id, [])
            class_symbols = [s for s in file_symbols if s.kind == "class"]
            callable_symbols = [s for s in file_symbols if s.kind in ("function", "method")]
            file_chunks = chunks_by_file.get(source_file.id, [])
            file_code = self._merge_file_chunks(file_chunks)
            file_source_info = self._source_info(source_file, code=file_code, start_line=1, end_line=source_file.line_count or 1)

            if not class_symbols:
                module_name = source_file.relative_path.rsplit("/", 1)[-1].replace(".py", "")
                module_id = self._stable_node_id("Module", source_file.relative_path, f"module:{source_file.relative_path}")
                module_label = safe_label(f"{source_file.relative_path} (模块)", 100).replace('"', "'")
                lines.append(f'    class {module_id}["{module_label}"] {{')
                node_count += 1
                for symbol in callable_symbols[:8]:
                    method_name = safe_label(symbol.name, 30)
                    lines.append(f"        +{method_name}()")
                    related_chunk = self._find_chunk_for_symbol(symbol, file_chunks)
                    info = self._source_info(
                        source_file, start_line=symbol.start_line or 1, end_line=symbol.end_line or symbol.start_line or 1,
                        code=related_chunk.content if related_chunk else symbol.signature or file_code, symbol=symbol
                    )
                    for key in (
                        self._symbol_node_id("Sym", source_file, symbol), symbol.qualified_name or "",
                        symbol.name, method_name, symbol.name.strip("_"), safe_label(symbol.name.strip("_"), 30),
                        f"{module_id}+{symbol.name}", f"{module_name}+{symbol.name}",
                    ):
                        self._put_mapping(mapping, key, info)
                lines.append("    }")
                self._put_mapping(mapping, module_id, file_source_info)
                self._put_mapping(mapping, module_name, file_source_info)
                self._put_mapping(mapping, source_file.relative_path, file_source_info)
                continue

            for class_symbol in class_symbols:
                if node_count >= max_nodes:
                    omitted = True
                    break
                class_id = self._symbol_node_id("Cls", source_file, class_symbol)
                class_label = safe_label(f"{class_symbol.qualified_name or class_symbol.name} ({source_file.relative_path})", 100).replace('"', "'")
                lines.append(f'    class {class_id}["{class_label}"] {{')
                node_count += 1
                related_methods = [
                    s for s in callable_symbols
                    if s.kind == "method"
                    and (s.qualified_name or "").rpartition(".")[0] == (class_symbol.qualified_name or class_symbol.name)
                    and (class_symbol.start_line or 0) <= (s.start_line or 0) <= (class_symbol.end_line or 10**9)
                ]
                related_chunk = self._find_chunk_for_symbol(class_symbol, chunks_by_file.get(source_file.id, []))
                class_info = self._source_info(
                    source_file, start_line=class_symbol.start_line or 1,
                    end_line=class_symbol.end_line or class_symbol.start_line or 1,
                    code=related_chunk.content if related_chunk else class_symbol.signature or file_code, symbol=class_symbol
                )
                self._put_mapping(mapping, class_id, class_info)
                self._put_mapping(mapping, class_symbol.qualified_name or class_symbol.name, class_info)
                self._put_mapping(mapping, class_symbol.name, class_info)
                self._put_mapping(mapping, source_file.relative_path, file_source_info)
                for method in related_methods[:8]:
                    lines.append(f"        +{safe_label(method.name, 30)}()")
                    method_chunk = self._find_chunk_for_symbol(method, chunks_by_file.get(source_file.id, []))
                    info = self._source_info(
                        source_file, start_line=method.start_line or 1, end_line=method.end_line or method.start_line or 1,
                        code=method_chunk.content if method_chunk else method.signature or class_info["code"], symbol=method
                    )
                    display = method.name.strip("_")
                    for key in (
                        self._symbol_node_id("Sym", source_file, method), method.qualified_name or "",
                        method.name, safe_label(method.name, 30), display, safe_label(display, 30),
                        f"{class_id}+{method.name}", f"{class_symbol.name}+{method.name}",
                    ):
                        self._put_mapping(mapping, key, info)
                lines.append("    }")

        if not lines or len(lines) == 1:
            lines.extend(["    class UnresolvedEvidence {", "        +仅结构视图()", "    }"])
        if omitted:
            lines.extend(["    class UnresolvedOmitted {", "        +已省略部分内容()", "    }"])
            lines.append('    note for UnresolvedOmitted "已省略部分内容；请缩小文件选择范围"')
            mapping["UnresolvedOmitted"] = self._unresolved_source_info("达到类图节点上限，请缩小文件选择范围")
        return "\n".join(lines), mapping

    def _group_symbols_by_file(self, symbols: list[Symbol]) -> dict[int, list[Symbol]]:
        result: dict[int, list[Symbol]] = {}

        for symbol in symbols:
            result.setdefault(symbol.file_id, []).append(symbol)

        return result

    def _group_chunks_by_file(self, chunks: list[CodeChunk]) -> dict[int, list[CodeChunk]]:
        result: dict[int, list[CodeChunk]] = {}

        for chunk in chunks:
            result.setdefault(chunk.file_id, []).append(chunk)

        return result

    def _merge_file_chunks(self, chunks: list[CodeChunk]) -> str:
        """合并同一文件的代码块，避免 class chunk 和 method chunk 重复显示。"""
        valid_chunks = [chunk for chunk in chunks if chunk.content and chunk.content.strip()]

        if not valid_chunks:
            return ""

        ordered = sorted(
            valid_chunks,
            key=lambda item: (
                item.start_line or 1,
                -(item.end_line or item.start_line or 1),
                item.id or 0,
            ),
        )
        kept: list[CodeChunk] = []
        for chunk in ordered:
            content = chunk.content.strip()
            start = chunk.start_line or 1
            end = chunk.end_line or start
            duplicate = False
            for prior in kept:
                prior_content = (prior.content or "").strip()
                prior_start = prior.start_line or 1
                prior_end = prior.end_line or prior_start
                same_position = start == prior_start and end == prior_end and content == prior_content
                same_range_contains = (
                    (prior_start <= start and end <= prior_end)
                    or (start <= prior_start and prior_end <= end)
                )
                overlapping_same_body = content == prior_content
                nested_body = content in prior_content or prior_content in content
                if same_position or (same_range_contains and (overlapping_same_body or nested_body)):
                    duplicate = True
                    break
            if not duplicate:
                kept.append(chunk)
        return "\n\n".join((chunk.content or "").strip() for chunk in kept)

    def _find_chunk_for_symbol(self, symbol: Symbol, chunks: list[CodeChunk]) -> CodeChunk | None:
        """优先按符号身份和精确边界定位，再取最小包含块。"""
        if symbol.start_line is None:
            return None

        symbol_end = symbol.end_line or symbol.start_line
        identities = {symbol.name}
        if symbol.qualified_name:
            identities.add(symbol.qualified_name)

        def smallest(items: list[CodeChunk]) -> CodeChunk | None:
            return min(
                items,
                key=lambda item: (
                    item.end_line - item.start_line,
                    item.start_line,
                    item.id or 0,
                ),
                default=None,
            )

        exact_identity = [
            chunk
            for chunk in chunks
            if chunk.symbol_name in identities
            and chunk.start_line == symbol.start_line
            and chunk.end_line == symbol_end
        ]
        if match := smallest(exact_identity):
            return match

        identity_matches = [
            chunk
            for chunk in chunks
            if chunk.symbol_name in identities
            and chunk.start_line <= symbol.start_line
            and chunk.end_line >= symbol_end
        ]
        if match := smallest(identity_matches):
            return match

        exact_bounds = [
            chunk
            for chunk in chunks
            if chunk.start_line == symbol.start_line and chunk.end_line == symbol_end
        ]
        if match := smallest(exact_bounds):
            return match

        containing = [
            chunk
            for chunk in chunks
            if chunk.start_line <= symbol.start_line and chunk.end_line >= symbol_end
        ]
        return smallest(containing)

    def _fallback(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str = "flowchart",
        reason: str = "缺少可验证源码证据，无法确认仓库业务语义",
    ) -> AgentResult:
        title = safe_label(reason, 60)
        diagram_type_key = (diagram_type or "flowchart").lower()

        if diagram_type_key in ("sequence", "sequencediagram"):
            mermaid = f"""sequenceDiagram
    participant Repo as 仓库结构
    Note over Repo: {title}
"""
        elif diagram_type_key in ("state", "statediagram"):
            mermaid = f"""stateDiagram-v2
    state \"{title}\" as Unresolved
    [*] --> Unresolved
"""
        elif diagram_type_key in ("architecture", "class", "classdiagram"):
            mermaid = """classDiagram
    class UnresolvedEvidence {
        +仅结构视图()
    }
"""
        else:
            mermaid = f"""flowchart TD
    A["结构降级视图：{title}"]
"""

        validation = validate_mermaid(mermaid)

        logs = [
            {
                "agent_name": "IntentAgent",
                "input_summary": prompt[:200],
                "output_summary": f"识别图表类型: {diagram_type}",
            },
            {
                "agent_name": "RetrievalAgent",
                "input_summary": project_name,
                "output_summary": f"未生成业务图：{reason}",
            },
            {
                "agent_name": "DiagramAgent",
                "input_summary": diagram_type,
                "output_summary": "已生成结构降级 Mermaid 源码",
            },
            {
                "agent_name": "ReviewAgent",
                "input_summary": "mermaid",
                "output_summary": "校验通过" if validation.valid else ";".join(validation.errors),
            },
        ]

        mapping = {"A": self._unresolved_source_info(reason)}

        logs.append(
            self._log(
                "GenerationQualityAgent",
                diagram_type,
                f"generation_mode=structural_fallback; quality_status=degraded; reason={reason}",
            )
        )

        return AgentResult(
            mermaid_code=mermaid,
            node_mapping=mapping,
            agent_logs=logs,
            generation_mode="structural_fallback",
            reason=reason,
            quality_status="degraded",
        )
