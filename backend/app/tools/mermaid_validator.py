import re
from pydantic import BaseModel


class MermaidValidateResult(BaseModel):
    valid: bool
    errors: list[str] = []


MERMAID_PREFIXES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2", "classDiagram")
UNSAFE_PATTERNS = (
    re.compile(r"%%\s*\{", re.I),
    re.compile(r"(?im)^\s*click(?:\s|$)"),
    re.compile(r"\bjavascript\s*:", re.I),
    re.compile(r"\bdata\s*:\s*(?:text/html|text/javascript|application/javascript|application/x-javascript|image/svg\+xml)", re.I),
    re.compile(r"\bhref\s*=", re.I),
    re.compile(r"<\s*script\b", re.I),
)


def validate_mermaid(code: str, expected_type: str | None = None) -> MermaidValidateResult:
    """Perform a conservative pre-check; browser Mermaid render is authoritative."""
    errors: list[str] = []
    stripped = code.strip()
    if not stripped:
        errors.append("Mermaid源码不能为空")
    if len(stripped) > 50000:
        errors.append("Mermaid源码超过50000字符限制")
    if any(pattern.search(stripped) for pattern in UNSAFE_PATTERNS):
        errors.append("Mermaid内容包含被禁止的安全配置、链接或回调")
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    declaration = first_line.split()[0] if first_line else ""
    if first_line and declaration not in MERMAID_PREFIXES:
        errors.append("缺少合法的Mermaid图表声明")
    if expected_type and declaration:
        expected = expected_type.lower()
        allowed = {
            "flowchart": {"flowchart", "graph"},
            "flowchartdiagram": {"flowchart", "graph"},
            "sequence": {"sequenceDiagram"},
            "sequencediagram": {"sequenceDiagram"},
            "state": {"stateDiagram", "stateDiagram-v2"},
            "statediagram": {"stateDiagram", "stateDiagram-v2"},
            "architecture": {"classDiagram"},
            "class": {"classDiagram"},
            "classdiagram": {"classDiagram"},
        }.get(expected)
        if allowed and declaration not in allowed:
            errors.append(f"图表类型不匹配：期望 {expected_type}，实际 {declaration}")
    if stripped.count('"') % 2 != 0:
        errors.append("双引号未闭合")
    if re.search(r"(?im)^\s*Note\s+over\s+[^:\n,]+\s*,\s*[^:\n,]+\s*,", stripped):
        errors.append("时序图 Note over 最多支持两个参与者")
    node_ids = re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*(?:\[|\()", stripped)
    invalid = [node for node in node_ids if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", node)]
    if invalid:
        errors.append(f"存在非法节点ID: {', '.join(invalid)}")
    return MermaidValidateResult(valid=not errors, errors=errors)
