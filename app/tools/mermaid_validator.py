import re
from pydantic import BaseModel


class MermaidValidateResult(BaseModel):
    valid: bool
    errors: list[str] = []


MERMAID_PREFIXES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram")


def validate_mermaid(code: str) -> MermaidValidateResult:
    errors: list[str] = []
    stripped = code.strip()
    if not stripped:
        errors.append("Mermaid源码不能为空")
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if first_line and not first_line.startswith(MERMAID_PREFIXES):
        errors.append("缺少合法的Mermaid图表声明")
    if stripped.count('"') % 2 != 0:
        errors.append("双引号未闭合")
    node_ids = re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*(?:\[|\()", stripped)
    invalid = [node for node in node_ids if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", node)]
    if invalid:
        errors.append(f"存在非法节点ID: {', '.join(invalid)}")
    return MermaidValidateResult(valid=not errors, errors=errors)
