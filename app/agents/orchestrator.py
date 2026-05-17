import re
from dataclasses import dataclass
from time import perf_counter
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agents.llm_provider import LLMProvider, StubLLMProvider
from app.agents.prompt_templates import build_mermaid_prompt
from app.models.code_chunk import CodeChunk
from app.tools.mermaid_validator import validate_mermaid


@dataclass
class AgentResult:
    mermaid_code: str
    node_mapping: dict
    agent_logs: list[dict]


class AgentOrchestrator:
    """固定流程：检索 -> 理解 -> 生成 -> 校验。"""

    def __init__(self, db: Session | None = None, llm_provider: LLMProvider | None = None):
        self.db = db
        self.llm_provider = llm_provider or StubLLMProvider()

    def retrieve_code_chunks(self, project_id: int, keywords: list[str], limit: int = 5) -> list[CodeChunk]:
        if not self.db:
            return []
        chunks = self.db.scalars(select(CodeChunk).where(CodeChunk.project_id == project_id).limit(300)).all()
        if not keywords:
            return chunks[:limit]
        scored: list[tuple[int, CodeChunk]] = []
        for chunk in chunks:
            haystack = f"{chunk.symbol_name or ''}\n{chunk.summary or ''}\n{chunk.content}".lower()
            score = sum(haystack.count(keyword) for keyword in keywords)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def run_analysis(self, project_id: int, project_name: str, prompt: str, diagram_type: str = "flowchart") -> AgentResult:
        logs: list[dict] = []
        keywords = [word.lower() for word in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", prompt)][:8]

        retrieve_start = perf_counter()
        chunks = self.retrieve_code_chunks(project_id, keywords)
        logs.append(
            {
                "agent_name": "RetrievalAgent",
                "input_summary": f"{project_name} | {','.join(keywords)}",
                "output_summary": f"命中代码片段: {len(chunks)}",
                "latency_ms": int((perf_counter() - retrieve_start) * 1000),
            }
        )

        understand_start = perf_counter()
        context_lines = [
            f"- {chunk.file.relative_path}:{chunk.start_line}-{chunk.end_line} {chunk.symbol_name or chunk.chunk_type}"
            for chunk in chunks
        ]
        context_text = "\n".join(context_lines)
        logs.append(
            {
                "agent_name": "UnderstandAgent",
                "input_summary": prompt[:200],
                "output_summary": "已理解检索结果并整理上下文",
                "latency_ms": int((perf_counter() - understand_start) * 1000),
            }
        )

        generate_start = perf_counter()
        llm_prompt = build_mermaid_prompt(diagram_type, prompt, context_text)
        used_fallback = False
        try:
            llm_result = self.llm_provider.generate_mermaid(llm_prompt, diagram_type)
            mermaid = llm_result.content
            logs.append(
                {
                    "agent_name": "GenerateAgent",
                    "input_summary": diagram_type,
                    "output_summary": "模型生成Mermaid成功",
                    "model_name": llm_result.model_name,
                    "prompt_tokens": llm_result.prompt_tokens,
                    "completion_tokens": llm_result.completion_tokens,
                    "latency_ms": int((perf_counter() - generate_start) * 1000),
                }
            )
        except Exception as exc:
            used_fallback = True
            mermaid = self._fallback_mermaid(diagram_type, prompt)
            logs.append(
                {
                    "agent_name": "GenerateAgent",
                    "input_summary": diagram_type,
                    "output_summary": "模型失败，启用兜底Mermaid",
                    "latency_ms": int((perf_counter() - generate_start) * 1000),
                    "status": "failed",
                    "error_message": str(exc)[:500],
                }
            )

        validate_start = perf_counter()
        validation = validate_mermaid(mermaid)
        if not validation.valid:
            used_fallback = True
            mermaid = self._fallback_mermaid(diagram_type, prompt)
        logs.append(
            {
                "agent_name": "ValidateAgent",
                "input_summary": "mermaid",
                "output_summary": "校验通过" if validation.valid else ";".join(validation.errors),
                "latency_ms": int((perf_counter() - validate_start) * 1000),
                "status": "success" if validation.valid else "failed",
                "error_message": None if validation.valid else ";".join(validation.errors),
            }
        )
        if used_fallback:
            logs.append(
                {
                    "agent_name": "FallbackAgent",
                    "input_summary": diagram_type,
                    "output_summary": "已返回演示兜底Mermaid",
                    "latency_ms": 0,
                    "status": "success",
                }
            )

        mapping = {
            "A": {"file_path": "user_prompt", "start_line": 1, "end_line": 1, "symbol": "prompt"},
        }
        for index, chunk in enumerate(chunks, start=1):
            mapping[f"C{index}"] = {
                "file_path": chunk.file.relative_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "symbol": chunk.symbol_name or chunk.chunk_type,
            }
        return AgentResult(mermaid_code=mermaid, node_mapping=mapping, agent_logs=logs)

    def _fallback_mermaid(self, diagram_type: str, prompt: str) -> str:
        title = prompt.strip().replace('"', "'")[:40] or "业务流程"
        if diagram_type == "sequence":
            return f"""sequenceDiagram
    participant U as 用户
    participant AG as Agent
    U->>AG: {title}
    AG-->>U: 返回示例图
"""
        if diagram_type == "state":
            return """stateDiagram-v2
    [*] --> start
    start --> finished
"""
        return f"""flowchart TD
    A[用户需求: {title}] --> B[检索代码]
    B --> C[理解逻辑]
    C --> D[生成Mermaid]
    D --> E[返回结果]
"""
