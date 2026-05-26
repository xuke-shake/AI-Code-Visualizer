from dataclasses import dataclass
import re

from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.tools.mermaid_validator import validate_mermaid


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
    """基于源码解析结果生成 Mermaid 图。

    当前版本不调用大模型，先从数据库读取 source_files / symbols / code_chunks，
    生成稳定可渲染的流程图、序列图、状态图和类图。
    """

    def run_analysis(
        self,
        project_name: str,
        prompt: str,
        diagram_type: str = "flowchart",
        db: Session | None = None,
        project_id: int | None = None,
        scope_paths: list[str] | None = None,
    ) -> AgentResult:
        if db is None or project_id is None:
            return self._fallback(project_name, prompt, diagram_type)

        try:
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
                return self._fallback(project_name, prompt, diagram_type)

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

            diagram_type_key = (diagram_type or "flowchart").lower()

            if diagram_type_key in ("sequence", "sequencediagram"):
                mermaid, mapping = self._build_sequence_diagram(
                    project_name, prompt, source_files, symbols, chunks
                )
            elif diagram_type_key in ("state", "statediagram"):
                mermaid, mapping = self._build_state_diagram(
                    project_name, prompt, source_files, symbols, chunks
                )
            elif diagram_type_key in ("architecture", "class", "classdiagram"):
                mermaid, mapping = self._build_class_diagram(
                    project_name, prompt, source_files, symbols, chunks
                )
            else:
                mermaid, mapping = self._build_flowchart(
                    project_name, prompt, source_files, symbols, chunks
                )

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
                    "output_summary": f"读取源码文件 {len(source_files)} 个，符号 {len(symbols)} 个，代码块 {len(chunks)} 个",
                },
                {
                    "agent_name": "DiagramAgent",
                    "input_summary": diagram_type,
                    "output_summary": "已根据源码解析结果生成 Mermaid 源码",
                },
                {
                    "agent_name": "ReviewAgent",
                    "input_summary": "mermaid",
                    "output_summary": "校验通过" if validation.valid else ";".join(validation.errors),
                },
            ]

            return AgentResult(mermaid_code=mermaid, node_mapping=mapping, agent_logs=logs)

        except Exception as exc:
            result = self._fallback(project_name, prompt, diagram_type)
            result.agent_logs.append(
                {
                    "agent_name": "ErrorGuard",
                    "input_summary": diagram_type,
                    "output_summary": f"生成异常，已降级为占位图: {exc}",
                }
            )
            return result

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