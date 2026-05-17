from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model_name: str = "stub-mermaid-v1"
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider:
    def generate_mermaid(self, prompt: str, diagram_type: str) -> LLMResponse:
        raise NotImplementedError


class StubLLMProvider(LLMProvider):
    """可替换的大模型调用占位实现。"""

    def __init__(self, model_name: str = "stub-mermaid-v1"):
        self.model_name = model_name

    def generate_mermaid(self, prompt: str, diagram_type: str) -> LLMResponse:
        title = prompt.strip().replace('"', "'").splitlines()[0][:40] or "业务流程"
        if diagram_type == "sequence":
            content = f"""sequenceDiagram
    participant U as 用户
    participant API as 后端
    participant AG as Agent
    U->>API: {title}
    API->>AG: 生成流程图
    AG-->>API: 返回Mermaid
"""
        elif diagram_type == "state":
            content = """stateDiagram-v2
    [*] --> created
    created --> analyzing
    analyzing --> ready
"""
        else:
            content = f"""flowchart TD
    A[需求输入] --> B[检索相关代码]
    B --> C[理解代码逻辑]
    C --> D[生成Mermaid图]
    D --> E[返回可视化结果: {title}]
"""
        return LLMResponse(content=content, model_name=self.model_name)
