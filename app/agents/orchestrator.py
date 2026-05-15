from dataclasses import dataclass
from app.tools.mermaid_validator import validate_mermaid


@dataclass
class AgentResult:
    mermaid_code: str
    node_mapping: dict
    agent_logs: list[dict]


class AgentOrchestrator:
    """固定流水线多Agent占位实现。

    后续可替换为LangGraph或真实LLM调用。这里先保证图表接口返回可渲染Mermaid。
    """

    def run_analysis(self, project_name: str, prompt: str, diagram_type: str = "flowchart") -> AgentResult:
        title = prompt.strip().replace('"', "'")[:40]
        if diagram_type == "sequence":
            mermaid = f"""sequenceDiagram
    participant U as 用户
    participant FE as 前端工作台
    participant API as FastAPI后端
    participant AG as Agent编排器
    U->>FE: {title}
    FE->>API: 提交分析请求
    API->>AG: 检索代码并生成图表
    AG-->>API: 返回Mermaid与源码映射
    API-->>FE: 返回图表结果
    FE-->>U: 渲染可视化图表
"""
        elif diagram_type == "state":
            mermaid = """stateDiagram-v2
    [*] --> created
    created --> parsing: 触发解析
    parsing --> ready: 解析成功
    parsing --> failed: 解析失败
    ready --> analyzing: 生成图表
    analyzing --> ready: 保存图表
"""
        else:
            mermaid = f"""flowchart TD
    A[用户输入指令: {title}] --> B[后端校验项目权限]
    B --> C[检索代码块与符号]
    C --> D[Agent分析业务逻辑]
    D --> E[生成Mermaid图表]
    E --> F[质量审查与语法校验]
    F --> G[保存图表和源码映射]
    G --> H[前端渲染结果]
"""
        validation = validate_mermaid(mermaid)
        logs = [
            {"agent_name": "IntentAgent", "input_summary": prompt[:200], "output_summary": f"识别图表类型: {diagram_type}"},
            {"agent_name": "RetrievalAgent", "input_summary": project_name, "output_summary": "后端骨架阶段使用占位检索结果"},
            {"agent_name": "DiagramAgent", "input_summary": diagram_type, "output_summary": "已生成Mermaid源码"},
            {"agent_name": "ReviewAgent", "input_summary": "mermaid", "output_summary": "校验通过" if validation.valid else ";".join(validation.errors)},
        ]
        mapping = {
            "A": {"file_path": "待接入源码解析", "start_line": 1, "end_line": 1, "symbol": "user_prompt"},
            "D": {"file_path": "app/agents/orchestrator.py", "start_line": 1, "end_line": 1, "symbol": "AgentOrchestrator"},
        }
        return AgentResult(mermaid_code=mermaid, node_mapping=mapping, agent_logs=logs)
