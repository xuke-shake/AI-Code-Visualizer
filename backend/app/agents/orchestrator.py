from dataclasses import dataclass
import os
import re
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.tools.mermaid_validator import validate_mermaid

def _load_backend_env() -> None:
    """加载 backend/.env，保证 AgentOrchestrator 可以读到 LLM 配置。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = Path(__file__).resolve().parents[2] / ".env"

    if env_path.exists():
        load_dotenv(env_path, override=True)


_load_backend_env()
@dataclass
class AgentResult:
    mermaid_code: str
    node_mapping: dict
    agent_logs: list[dict]


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

    def __init__(self):
        # 再加载一次，避免热重载或导入顺序导致 .env 没进 os.environ
        _load_backend_env()

        flag = os.getenv("LLM_ENABLED", "auto").strip().lower()
        api_key = os.getenv("LLM_API_KEY")

        self.llm_enabled = (
            flag in {"1", "true", "yes", "on", "auto"}
            and bool(api_key)
        )

        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        self.max_context_chars = int(os.getenv("LLM_MAX_CONTEXT_CHARS", "12000") or "12000")

        # 临时调试：确认后端到底有没有读到 LLM 配置
        print(
            "DEBUG LLM CONFIG:",
            {
                "LLM_ENABLED": flag,
                "HAS_API_KEY": bool(api_key),
                "LLM_BASE_URL": os.getenv("LLM_BASE_URL"),
                "LLM_MODEL": self.llm_model,
                "should_use_llm": self.llm_enabled,
            },
        )

    def run_analysis(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str = "flowchart",
        db: Session | None = None,
        project_id: int | None = None,
        scope_paths: list[str] | None = None,
    ) -> AgentResult:
        """执行 DB 检索 -> Mermaid 生成 -> 可选 LLM 优化 -> 校验。"""
        if db is None or project_id is None:
            return self._run_without_db_or_fallback(project_name, prompt, diagram_type)

        logs: list[dict] = []

        try:
            start = time.time()
            source_files = (
                db.query(SourceFile)
                .filter(SourceFile.project_id == project_id)
                .order_by(SourceFile.relative_path.asc())
                .all()
            )

            if scope_paths:
                selected = set(scope_paths)
                source_files = [f for f in source_files if f.relative_path in selected]

            if not source_files:
                result = self._fallback(project_name, prompt, diagram_type)
                result.agent_logs.append(
                    self._log(
                        "RetrievalAgent",
                        project_name,
                        "未找到已解析源码文件，使用兜底 Mermaid",
                        start,
                    )
                )
                return result

            file_ids = [f.id for f in source_files]

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
            code_context = self._build_code_context(source_files, symbols, chunks)

            # 再尝试使用 agent 负责人提供的大模型链路增强图表表达。
            if self.llm_enabled:
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

                logs.append(
                    self._log(
                        "DiagramAgent",
                        f"Prompt长度: {len(prompt)}, 上下文长度: {len(code_context)}",
                        "LLM Mermaid 生成成功" if llm_mermaid else "LLM 不可用或生成无效，沿用规则图",
                        start,
                        llm_error,
                        model_name=self.llm_model,
                    )
                )
            else:
                logs.append(
                    self._log(
                        "DiagramAgent",
                        "LLM_ENABLED/LLM_API_KEY",
                        "未启用 LLM，沿用规则图",
                    )
                )

            start = time.time()
            validation = validate_mermaid(final_mermaid)
            review_error = None
            if not validation.valid:
                review_error = ";".join(validation.errors)
                final_mermaid = rule_mermaid if rule_validation.valid else self._fallback(project_name, prompt, diagram_type).mermaid_code

            logs.append(
                self._log(
                    "ReviewAgent",
                    "待校验的 Mermaid 文本",
                    "校验通过" if not review_error else "校验失败，已回退到规则图",
                    start,
                    review_error,
                )
            )

            return AgentResult(mermaid_code=final_mermaid, node_mapping=mapping, agent_logs=logs)

        except Exception as exc:
            result = self._fallback(project_name, prompt, diagram_type)
            result.agent_logs.append(
                self._log(
                    "ErrorGuard",
                    diagram_type,
                    f"生成异常，已降级为占位图: {exc}",
                    error=str(exc),
                )
            )
            return result

    def _run_without_db_or_fallback(self, project_name: str, prompt: str, diagram_type: str) -> AgentResult:
        """兼容 agent 负责人原始测试：没有 DB 时可尝试本地路径检索，否则回退。"""
        if not self.llm_enabled:
            return self._fallback(project_name, prompt, diagram_type)

        start = time.time()
        try:
            from app.agents.retrieval import simple_code_retrieval

            project_path = os.getenv("PROJECT_ROOT_PATH", ".")
            code_context = simple_code_retrieval(project_path, prompt[:20].strip())
            llm_mermaid, error = self._try_llm_mermaid(
                project_name=project_name,
                prompt=prompt,
                diagram_type=diagram_type,
                code_context=code_context,
                node_hints="A/B/C 等通用节点 ID",
                baseline_mermaid="",
            )
            if llm_mermaid:
                mapping = self._augment_mapping_for_mermaid(llm_mermaid, {}, code_context)
                return AgentResult(
                    mermaid_code=llm_mermaid,
                    node_mapping=mapping,
                    agent_logs=[self._log("RetrievalAgent", project_path, f"本地检索上下文长度: {len(code_context)}", start),
                                self._log("DiagramAgent", prompt[:200], "LLM Mermaid 生成成功", error=error, model_name=self.llm_model)],
                )
        except Exception:
            pass

        return self._fallback(project_name, prompt, diagram_type)

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
        try:
            from app.agents.llm_provider import LLMProvider
            from app.agents.prompts import MERMAID_SYSTEM_PROMPT, MERMAID_USER_TEMPLATE

            llm = LLMProvider(model=self.llm_model)
            user_content = MERMAID_USER_TEMPLATE.format(
                project_name=project_name,
                user_prompt=prompt,
                diagram_type=diagram_type,
                diagram_header=self._diagram_header(diagram_type),
                node_hints=node_hints,
                baseline_mermaid=baseline_mermaid[:4000],
                code_context=code_context,
            )
            mermaid_code = self._strip_markdown_fences(
                llm.chat(system_prompt=MERMAID_SYSTEM_PROMPT, user_prompt=user_content)
            )

            if (diagram_type or "").lower() in {"state", "statediagram", "statediagram-v2"}:
                mermaid_code = self._repair_state_diagram(mermaid_code)

            validation = validate_mermaid(mermaid_code)
            if not validation.valid:
                return None, ";".join(validation.errors)
            return mermaid_code, None
        except Exception as exc:
            return None, str(exc)
    
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

        for line in body_lines:
            stripped = line.strip()

            # 合法 state 定义行不要替换，否则会把 state "xxx" as S1 修坏
            if state_def_pattern.match(line):
                repaired_body.append(line)
                continue

            new_line = line

        # 只处理包含箭头的行
            if "-->" in line:
                for label in re.findall(r'"([^"]+)"', line):
                    state_id = new_state_id(label)
                    new_line = new_line.replace(f'"{label}"', state_id)

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
    ) -> str:
        symbols_by_file = self._group_symbols_by_file(symbols)
        chunks_by_file = self._group_chunks_by_file(chunks)
        blocks: list[str] = []
        total = 0

        for source_file in source_files[:30]:
            file_chunks = chunks_by_file.get(source_file.id, [])
            file_symbols = symbols_by_file.get(source_file.id, [])
            code = self._merge_file_chunks(file_chunks)
            if not code and file_symbols:
                code = "\n".join(s.signature or s.name for s in file_symbols[:20])
            if not code:
                continue

            symbol_names = ", ".join((s.qualified_name or s.name) for s in file_symbols[:20])
            block = (
                f"--- 文件路径: {source_file.relative_path} | 语言: {source_file.language or 'unknown'} ---\n"
                f"符号: {symbol_names or '无'}\n"
                f"{code}\n"
            )

            if total + len(block) > self.max_context_chars:
                remain = self.max_context_chars - total
                if remain > 200:
                    blocks.append(block[:remain])
                break

            blocks.append(block)
            total += len(block)

        return "\n".join(blocks) or "没有可用代码块；请基于项目元数据生成概览图。"

    def _build_node_hints(self, mapping: dict) -> str:
        hints: list[str] = []
        for key, info in mapping.items():
            key_text = str(key)
            if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", key_text):
                continue
            if not isinstance(info, dict):
                continue
            hints.append(
                f"{key_text}: {info.get('file_path', '')}:{info.get('start_line', 1)}-{info.get('end_line', 1)}"
            )
            if len(hints) >= 80:
                break
        return "\n".join(hints) or "无"

    def _augment_mapping_for_mermaid(self, mermaid_code: str, mapping: dict, code_context: str) -> dict:
        default_source = {
            "file_path": "LLM生成图 - 参考上下文",
            "start_line": 1,
            "end_line": 1,
            "code": code_context[:4000],
        }
        patterns = [
            r"\b([A-Za-z][A-Za-z0-9_]*)\s*(?:\[|\(|\{)",
            r"\bclass\s+([A-Za-z][A-Za-z0-9_]*)",
            r"\bparticipant\s+([A-Za-z][A-Za-z0-9_]*)",
            r"\bas\s+([A-Za-z][A-Za-z0-9_]*)",
        ]
        for pattern in patterns:
            for node_id in re.findall(pattern, mermaid_code):
                mapping.setdefault(node_id, default_source)
        return mapping

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
    ) -> dict:
        return {
            "agent_name": agent_name,
            "input_summary": (input_summary or "")[:500],
            "output_summary": (output_summary or "")[:1000],
            "duration_sec": round(time.time() - start_time, 3) if start_time else 0,
            "errors": error,
            "model_name": model_name,
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

        project_node = "P"
        project_label = f"项目：{safe_label(project_name)}"

        project_info = {
            "file_path": "项目根目录",
            "start_line": 1,
            "end_line": 1,
            "code": prompt,
        }

        lines.append(f'    {project_node}["{project_label}"]')
        mapping[project_node] = project_info
        mapping[project_label] = project_info

        symbols_by_file = self._group_symbols_by_file(symbols)
        chunks_by_file = self._group_chunks_by_file(chunks)

        for file_index, source_file in enumerate(source_files, start=1):
            file_node = f"F{file_index}"
            file_label = f"文件：{safe_label(source_file.relative_path)}"

            lines.append(f'    {project_node} --> {file_node}["{file_label}"]')

            file_chunks = chunks_by_file.get(source_file.id, [])
            file_code = self._merge_file_chunks(file_chunks)

            file_source_info = {
                "file_path": source_file.relative_path,
                "start_line": 1,
                "end_line": source_file.line_count or 1,
                "code": file_code,
            }

            mapping[file_node] = file_source_info
            mapping[file_label] = file_source_info

            file_symbols = symbols_by_file.get(source_file.id, [])

            if file_symbols:
                for symbol_index, symbol in enumerate(file_symbols[:8], start=1):
                    symbol_node = f"S{file_index}_{symbol_index}"
                    symbol_label = safe_label(f"{symbol.kind}: {symbol.name}")

                    lines.append(f'    {file_node} --> {symbol_node}["{symbol_label}"]')

                    related_chunk = self._find_chunk_for_symbol(
                        symbol,
                        chunks_by_file.get(source_file.id, []),
                    )

                    symbol_source_info = {
                        "file_path": source_file.relative_path,
                        "start_line": symbol.start_line or 1,
                        "end_line": symbol.end_line or symbol.start_line or 1,
                        "code": related_chunk.content if related_chunk else symbol.signature or "",
                    }

                    mapping[symbol_node] = symbol_source_info
                    mapping[symbol_label] = symbol_source_info
            else:
                for chunk_index, chunk in enumerate(file_chunks[:5], start=1):
                    chunk_node = f"C{file_index}_{chunk_index}"
                    chunk_label = f"代码块：{safe_label(chunk.symbol_name or chunk.chunk_type or '代码块')}"

                    lines.append(f'    {file_node} --> {chunk_node}["{chunk_label}"]')

                    chunk_source_info = {
                        "file_path": source_file.relative_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "code": chunk.content,
                    }

                    mapping[chunk_node] = chunk_source_info
                    mapping[chunk_label] = chunk_source_info

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

        for index, source_file in enumerate(usable_files, start=1):
            alias = f"F{index}"
            display_name = safe_label(source_file.relative_path, 24)

            lines.append(f"    participant {alias} as {display_name}")

            file_source_info = {
                "file_path": source_file.relative_path,
                "start_line": 1,
                "end_line": source_file.line_count or 1,
                "code": self._merge_file_chunks(chunks_by_file.get(source_file.id, [])),
            }

            mapping[alias] = file_source_info
            mapping[display_name] = file_source_info

        if usable_files:
            lines.append("    U->>F1: 发起业务入口")
            for index in range(len(usable_files) - 1):
                left = f"F{index + 1}"
                right = f"F{index + 2}"
                lines.append(f"    {left}->>{right}: 调用或依赖")
            lines.append(f"    F{len(usable_files)}-->>U: 返回处理结果")
        else:
            lines.append("    U->>U: 暂无可分析文件")

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
            "Parsed": {
                "file_path": "项目根目录",
                "start_line": 1,
                "end_line": 1,
                "code": prompt,
            }
        }

        chunks_by_file = self._group_chunks_by_file(chunks)

        for index, source_file in enumerate(source_files[:8], start=1):
            state_node = f"File{index}"
            label = safe_label(source_file.relative_path, 24)

            lines.append(f'    state "{label}" as {state_node}')
            lines.append(f"    Parsed --> {state_node}")

            source_info = {
                "file_path": source_file.relative_path,
                "start_line": 1,
                "end_line": source_file.line_count or 1,
                "code": self._merge_file_chunks(chunks_by_file.get(source_file.id, [])),
            }

            mapping[state_node] = source_info
            mapping[label] = source_info

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

        symbols_by_file = self._group_symbols_by_file(symbols)
        chunks_by_file = self._group_chunks_by_file(chunks)

        created_classes: list[str] = []

        for file_index, source_file in enumerate(source_files, start=1):
            file_symbols = symbols_by_file.get(source_file.id, [])
            class_symbols = [s for s in file_symbols if s.kind == "class"]
            callable_symbols = [s for s in file_symbols if s.kind in ("function", "method")]

            file_chunks = chunks_by_file.get(source_file.id, [])
            file_code = self._merge_file_chunks(file_chunks)

            file_source_info = {
                "file_path": source_file.relative_path,
                "start_line": 1,
                "end_line": source_file.line_count or 1,
                "code": file_code,
            }

            # 没有 class 的文件，比如 main.py，用 Module_xxx 表示模块
            if not class_symbols:
                module_name = source_file.relative_path.rsplit("/", 1)[-1].replace(".py", "")
                module_id = safe_id(f"Module_{module_name}", "Module")

                lines.append(f"    class {module_id} {{")

                for symbol in callable_symbols[:8]:
                    method_name = safe_label(symbol.name, 30)
                    lines.append(f"        +{method_name}()")

                    related_chunk = self._find_chunk_for_symbol(symbol, file_chunks)

                    method_source_info = {
                        "file_path": source_file.relative_path,
                        "start_line": symbol.start_line or 1,
                        "end_line": symbol.end_line or symbol.start_line or 1,
                        "code": related_chunk.content if related_chunk else symbol.signature or file_code,
                    }

                    # 兼容类图点击时返回的各种 key
                    method_display_name = symbol.name.strip("_")
                    method_display_label = safe_label(method_display_name, 30)

                    mapping[symbol.name] = method_source_info
                    mapping[method_name] = method_source_info
                    mapping[method_display_name] = method_source_info
                    mapping[method_display_label] = method_source_info

                    mapping[f"{module_id}+{symbol.name}"] = method_source_info
                    mapping[f"{module_id}+{method_name}"] = method_source_info
                    mapping[f"{module_id}+{method_display_name}"] = method_source_info
                    mapping[f"{module_id}+{method_display_label}"] = method_source_info

                    mapping[f"{module_name}+{symbol.name}"] = method_source_info
                    mapping[f"{module_name}+{method_name}"] = method_source_info
                    mapping[f"{module_name}+{method_display_name}"] = method_source_info
                    mapping[f"{module_name}+{method_display_label}"] = method_source_info

                lines.append("    }")

                created_classes.append(module_id)

                mapping[module_id] = file_source_info
                mapping[module_name] = file_source_info
                mapping[source_file.relative_path] = file_source_info
                continue

            for class_symbol in class_symbols:
                class_id = safe_id(class_symbol.name, "Cls")

                lines.append(f"    class {class_id} {{")

                related_methods = [
                    s for s in callable_symbols
                    if (class_symbol.start_line or 0)
                    <= (s.start_line or 0)
                    <= (class_symbol.end_line or 10**9)
                ]

                related_chunk = self._find_chunk_for_symbol(
                    class_symbol,
                    chunks_by_file.get(source_file.id, []),
                )

                class_source_info = {
                    "file_path": source_file.relative_path,
                    "start_line": class_symbol.start_line or 1,
                    "end_line": class_symbol.end_line or class_symbol.start_line or 1,
                    "code": related_chunk.content if related_chunk else class_symbol.signature or file_code,
                }

                mapping[class_id] = class_source_info
                mapping[class_symbol.name] = class_source_info
                mapping[source_file.relative_path] = file_source_info

                for method in related_methods[:8]:
                    method_name = safe_label(method.name, 30)
                    lines.append(f"        +{method_name}()")

                    method_chunk = self._find_chunk_for_symbol(
                        method,
                        chunks_by_file.get(source_file.id, []),
                    )

                    method_source_info = {
                        "file_path": source_file.relative_path,
                        "start_line": method.start_line or 1,
                        "end_line": method.end_line or method.start_line or 1,
                        "code": method_chunk.content if method_chunk else method.signature or class_source_info["code"],
                    }

                    # 兼容类图点击时返回的 key，例如 UserService+login
                    method_display_name = method.name.strip("_")
                    method_display_label = safe_label(method_display_name, 30)

                    mapping[method.name] = method_source_info
                    mapping[method_name] = method_source_info
                    mapping[method_display_name] = method_source_info
                    mapping[method_display_label] = method_source_info

                    mapping[f"{class_id}+{method.name}"] = method_source_info
                    mapping[f"{class_id}+{method_name}"] = method_source_info
                    mapping[f"{class_id}+{method_display_name}"] = method_source_info
                    mapping[f"{class_id}+{method_display_label}"] = method_source_info

                    mapping[f"{class_symbol.name}+{method.name}"] = method_source_info
                    mapping[f"{class_symbol.name}+{method_name}"] = method_source_info
                    mapping[f"{class_symbol.name}+{method_display_name}"] = method_source_info
                    mapping[f"{class_symbol.name}+{method_display_label}"] = method_source_info

                lines.append("    }")

                created_classes.append(class_id)

        # 简单补几条依赖关系，让类图不只是孤立方块
        if len(created_classes) >= 2:
            for left, right in zip(created_classes, created_classes[1:]):
                lines.append(f"    {left} ..> {right}")

        if len(lines) == 1:
            lines.append("    class EmptyProject")

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

        chunks_by_size = sorted(
            valid_chunks,
            key=lambda item: len(item.content or ""),
            reverse=True,
        )

        kept_contents: list[str] = []

        for chunk in chunks_by_size:
            content = chunk.content.strip()
            already_in_kept = any(content in kept for kept in kept_contents)

            if not already_in_kept:
                kept_contents.append(content)

        def get_start_line(content: str) -> int:
            for chunk in valid_chunks:
                if chunk.content and chunk.content.strip() == content:
                    return chunk.start_line or 1
            return 1

        kept_contents = sorted(kept_contents, key=get_start_line)

        return "\n\n".join(kept_contents)

    def _find_chunk_for_symbol(self, symbol: Symbol, chunks: list[CodeChunk]) -> CodeChunk | None:
        """根据符号所在行号，找到包含它的代码块。"""
        if symbol.start_line is None:
            return None

        for chunk in chunks:
            if chunk.start_line <= symbol.start_line <= chunk.end_line:
                return chunk

        return None

    def _fallback(self, project_name: str, prompt: str, diagram_type: str = "flowchart") -> AgentResult:
        title = prompt.strip().replace('"', "'")[:40]
        diagram_type_key = (diagram_type or "flowchart").lower()

        if diagram_type_key in ("sequence", "sequencediagram"):
            mermaid = f"""sequenceDiagram
    participant U as 用户
    participant FE as 前端工作台
    participant API as FastAPI后端
    participant AG as Agent编排器
    U->>FE: {title}
    FE->>API: 提交分析请求
    API->>AG: 生成图表
    AG-->>API: 返回Mermaid
    API-->>FE: 返回图表结果
    FE-->>U: 渲染图表
"""
        elif diagram_type_key in ("state", "statediagram"):
            mermaid = """stateDiagram-v2
    [*] --> created
    created --> parsing: 触发解析
    parsing --> ready: 解析成功
    parsing --> failed: 解析失败
    ready --> analyzing: 生成图表
    analyzing --> ready: 保存图表
"""
        elif diagram_type_key in ("architecture", "class", "classdiagram"):
            mermaid = """classDiagram
    class Project
    class SourceFile
    class Symbol
    class Diagram
    Project --> SourceFile
    SourceFile --> Symbol
    Project --> Diagram
"""
        else:
            mermaid = f"""flowchart TD
    A["用户输入指令: {title}"] --> B["后端校验项目权限"]
    B --> C["检索代码块与符号"]
    C --> D["Agent分析业务逻辑"]
    D --> E["生成Mermaid图表"]
    E --> F["质量审查与语法校验"]
    F --> G["保存图表和源码映射"]
    G --> H["前端渲染结果"]
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
                "output_summary": "未传入数据库上下文或生成异常，使用兜底结果",
            },
            {
                "agent_name": "DiagramAgent",
                "input_summary": diagram_type,
                "output_summary": "已生成 Mermaid 源码",
            },
            {
                "agent_name": "ReviewAgent",
                "input_summary": "mermaid",
                "output_summary": "校验通过" if validation.valid else ";".join(validation.errors),
            },
        ]

        mapping = {
            "A": {
                "file_path": "待接入源码解析",
                "start_line": 1,
                "end_line": 1,
                "code": prompt,
            }
        }

        return AgentResult(mermaid_code=mermaid, node_mapping=mapping, agent_logs=logs)