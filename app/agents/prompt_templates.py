MERMAID_FLOW_PROMPT_TEMPLATE = """你是代码可视化助手。请严格输出 Mermaid 源码，不要输出解释文本。
图类型: {diagram_type}
用户需求: {user_prompt}

相关代码片段:
{code_context}

输出要求:
1. 第一行必须是合法 Mermaid 声明（如 flowchart TD / sequenceDiagram / stateDiagram-v2）
2. 节点和连线要体现业务步骤
3. 仅输出 Mermaid 代码
"""


def build_mermaid_prompt(diagram_type: str, user_prompt: str, code_context: str) -> str:
    return MERMAID_FLOW_PROMPT_TEMPLATE.format(
        diagram_type=diagram_type,
        user_prompt=user_prompt.strip(),
        code_context=code_context.strip() or "无检索结果",
    )
