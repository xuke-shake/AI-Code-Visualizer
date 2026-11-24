from dataclasses import dataclass, field

from tree_sitter import Language, Parser
import tree_sitter_python as tsp

PY_LANGUAGE = Language(tsp.language())
_parser = Parser()
_parser.language = PY_LANGUAGE

NODE_KIND_MAP = {
    "function_definition": "function",
    "async_function_definition": "function",
    "class_definition": "class",
}


@dataclass
class SymbolInfo:
    name: str
    kind: str  # "function" | "method" | "class"
    qualified_name: str | None
    start_line: int
    end_line: int
    signature: str | None    #签名


@dataclass
class SyntaxNode:
    """嵌套语法树节点，用于表达控制流与函数调用结构。"""

    kind: str                 # 逻辑类型："if" / "for" / "while" / "return" / "call" 等
    label: str                # 简短可读文本，如 "if x > 0" / "print(i)"
    start_line: int           # 1-based，含
    end_line: int             # 1-based，含
    children: list["SyntaxNode"] = field(default_factory=list)



def _build_symbol(node, code_bytes: bytes, kind: str) -> SymbolInfo:
    name_node = node.child_by_field_name("name")
    name = code_bytes[name_node.start_byte:name_node.end_byte].decode() if name_node else "unknown"

    body = node.child_by_field_name("body")
    sig_end = body.start_byte if body else node.end_byte
    signature = code_bytes[node.start_byte:sig_end].decode().strip().rstrip(":")

    return SymbolInfo(
        name=name,
        kind=kind,
        qualified_name=name if kind != "method" else None,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=signature, 
    )



def parse_source(code: str) -> list[SymbolInfo]:
    """解析一段 Python 源码，返回顶层符号（含类内方法），忽略嵌套函数。"""
    if not code.strip():
        return []

    #把代码转成字节 → 让 tree-sitter 解析成语法树
    code_bytes = code.encode("utf-8")
    tree = _parser.parse(code_bytes)
    root = tree.root_node

    # tree-sitter keeps an ERROR node for malformed Python.  Treat it as a
    # parse failure so callers can persist a failed/partial diagnostic rather
    # than reporting a successful file with silently missing symbols.
    if root.has_error:
        raise SyntaxError("Python源码存在语法错误")

    symbols: list[SymbolInfo] = []

    for child in root.children:
        _extract_symbol(child, code_bytes, symbols)

    return symbols


def _extract_symbol(node, code_bytes: bytes, symbols: list[SymbolInfo], class_name: str | None = None):
    """递归处理节点：展开 decorated_definition，提取函数/类/方法"""
    # 装饰器包装：展开取出真正的定义节点
    if node.type == "decorated_definition":
        inner = node.child_by_field_name("definition")
        if inner:
            first = len(symbols)
            _extract_symbol(inner, code_bytes, symbols, class_name)
            if len(symbols) > first:
                symbols[first].start_line = node.start_point[0] + 1
        return

    if node.type == "function_definition":
        kind = "method" if class_name else "function"
        sym = _build_symbol(node, code_bytes, kind=kind)
        if class_name:
            sym.qualified_name = f"{class_name}.{sym.name}"
        symbols.append(sym)

    elif node.type == "async_function_definition":
        kind = "method" if class_name else "function"
        sym = _build_symbol(node, code_bytes, kind=kind)
        if class_name:
            sym.qualified_name = f"{class_name}.{sym.name}"
        symbols.append(sym)

    elif node.type == "class_definition":
        class_sym = _build_symbol(node, code_bytes, kind="class")
        class_sym.qualified_name = f"{class_name}.{class_sym.name}" if class_name else class_sym.name
        symbols.append(class_sym)
        body = node.child_by_field_name("body")
        if body:
            for method_node in body.children:
                _extract_symbol(method_node, code_bytes, symbols, class_sym.qualified_name)


# ---- 嵌套语法树：控制流 + 函数调用 ----

# 收集函数调用时不应向下钻取的结构容器
_STRUCTURE_TYPES = {
    "module",
    "block",
    "function_definition",
    "async_function_definition",
    "class_definition",
    "decorated_definition",
}


def _line_of(node) -> int:
    return node.start_point[0] + 1


def _end_line_of(node) -> int:
    return node.end_point[0] + 1


def _node_text(node, code_bytes: bytes) -> str:
    return code_bytes[node.start_byte:node.end_byte].decode()


def _call_node(node, code_bytes: bytes) -> SyntaxNode:
    callee = node.child_by_field_name("function")
    label = _node_text(callee, code_bytes) if callee else _node_text(node, code_bytes)
    return SyntaxNode(kind="call", label=label, start_line=_line_of(node), end_line=_end_line_of(node))


def _collect_calls(node, code_bytes: bytes, out: list[SyntaxNode]) -> None:
    """收集表达式子树中的函数调用（含 node 本身），不深入 call 参数与结构容器。"""
    if node.type == "call":
        out.append(_call_node(node, code_bytes))
        return
    if node.type in _STRUCTURE_TYPES:
        return
    for child in node.children:
        if child.type in _STRUCTURE_TYPES or child.type.endswith("_statement") or child.type.endswith("_clause"):
            continue
        _collect_calls(child, code_bytes, out)


def _body_block(node):
    """取节点 body：优先字段名 body，否则退回首个 block 具名子节点（except/finally 无字段名）。"""
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for child in node.named_children:
        if child.type == "block":
            return child
    return None


def _children(node, code_bytes: bytes) -> list[SyntaxNode]:
    """把 block / module 容器内的语句逐个转为树节点。"""
    out: list[SyntaxNode] = []
    for child in node.named_children:
        out.extend(_statement_nodes(child, code_bytes))
    return out


def _statement_nodes(node, code_bytes: bytes) -> list[SyntaxNode]:
    """把单个语句/定义节点转为 0..n 个 SyntaxNode。"""
    t = node.type

    if t == "decorated_definition":
        inner = node.child_by_field_name("definition")
        if inner is None:
            return []
        result = _statement_nodes(inner, code_bytes)
        if result:
            result[0].start_line = _line_of(node)
        return result

    if t in ("function_definition", "async_function_definition"):
        sym = _build_symbol(node, code_bytes, kind="function")
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        return [SyntaxNode(kind="function", label=sym.signature or sym.name,
                           start_line=sym.start_line, end_line=sym.end_line, children=kids)]

    if t == "class_definition":
        sym = _build_symbol(node, code_bytes, kind="class")
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        return [SyntaxNode(kind="class", label=sym.name,
                           start_line=sym.start_line, end_line=sym.end_line, children=kids)]

    if t == "if_statement":
        cond = node.child_by_field_name("condition")
        cons = node.child_by_field_name("consequence")
        kids = _children(cons, code_bytes) if cons else []
        for child in node.named_children:
            if child.type in ("elif_clause", "else_clause"):
                kids.extend(_statement_nodes(child, code_bytes))
        if cond is not None:
            _collect_calls(cond, code_bytes, kids)
        label = f"if {_node_text(cond, code_bytes)}" if cond else "if"
        return [SyntaxNode(kind="if", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "elif_clause":
        cond = node.child_by_field_name("condition")
        cons = node.child_by_field_name("consequence")
        kids = _children(cons, code_bytes) if cons else []
        if cond is not None:
            _collect_calls(cond, code_bytes, kids)
        label = f"elif {_node_text(cond, code_bytes)}" if cond else "elif"
        return [SyntaxNode(kind="elif", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "else_clause":
        body = _body_block(node)
        kids = _children(body, code_bytes) if body else []
        return [SyntaxNode(kind="else", label="else", start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t in ("for_statement", "async_for_statement"):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        if right is not None:
            _collect_calls(right, code_bytes, kids)
        label = f"for {_node_text(left, code_bytes)} in {_node_text(right, code_bytes)}" if (left and right) else "for"
        return [SyntaxNode(kind="for", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "while_statement":
        cond = node.child_by_field_name("condition")
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        if cond is not None:
            _collect_calls(cond, code_bytes, kids)
        label = f"while {_node_text(cond, code_bytes)}" if cond else "while"
        return [SyntaxNode(kind="while", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "return_statement":
        kids: list[SyntaxNode] = []
        for child in node.named_children:
            _collect_calls(child, code_bytes, kids)
        value_text = " ".join(_node_text(c, code_bytes) for c in node.named_children).strip()
        label = f"return {value_text}" if value_text else "return"
        return [SyntaxNode(kind="return", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "raise_statement":
        value_text = " ".join(_node_text(c, code_bytes) for c in node.named_children).strip()
        label = f"raise {value_text}" if value_text else "raise"
        return [SyntaxNode(kind="raise", label=label, start_line=_line_of(node), end_line=_end_line_of(node))]

    if t == "try_statement":
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        for child in node.named_children:
            if child.type in ("except_clause", "else_clause", "finally_clause"):
                kids.extend(_statement_nodes(child, code_bytes))
        return [SyntaxNode(kind="try", label="try", start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "except_clause":
        body = _body_block(node)
        kids = _children(body, code_bytes) if body else []
        exc_parts = [c for c in node.named_children if c.type != "block"]
        exc_text = " ".join(_node_text(c, code_bytes) for c in exc_parts).strip()
        label = f"except {exc_text}" if exc_text else "except"
        return [SyntaxNode(kind="except", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "finally_clause":
        body = _body_block(node)
        kids = _children(body, code_bytes) if body else []
        return [SyntaxNode(kind="finally", label="finally", start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "match_statement":
        subject = node.child_by_field_name("subject")
        body = node.child_by_field_name("body")
        kids = _children(body, code_bytes) if body else []
        if subject is not None:
            _collect_calls(subject, code_bytes, kids)
        label = f"match {_node_text(subject, code_bytes)}" if subject else "match"
        return [SyntaxNode(kind="match", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "case_clause":
        body = node.child_by_field_name("consequence")
        kids = _children(body, code_bytes) if body else []
        pattern_parts = [c for c in node.named_children if c.type != "block"]
        pattern_text = " ".join(_node_text(c, code_bytes) for c in pattern_parts).strip()
        label = f"case {pattern_text}" if pattern_text else "case"
        return [SyntaxNode(kind="case", label=label, start_line=_line_of(node), end_line=_end_line_of(node), children=kids)]

    if t == "break_statement":
        return [SyntaxNode(kind="break", label="break", start_line=_line_of(node), end_line=_end_line_of(node))]

    if t == "continue_statement":
        return [SyntaxNode(kind="continue", label="continue", start_line=_line_of(node), end_line=_end_line_of(node))]

    if t == "pass_statement":
        return [SyntaxNode(kind="pass", label="pass", start_line=_line_of(node), end_line=_end_line_of(node))]

    if t == "expression_statement":
        kids: list[SyntaxNode] = []
        for child in node.named_children:
            _collect_calls(child, code_bytes, kids)
        return kids

    return []


def parse_tree(code: str) -> SyntaxNode:
    """解析一段 Python 源码，返回以 module 为根的嵌套语法树（含控制流与函数调用）。"""
    if not code.strip():
        return SyntaxNode(kind="module", label="<module>", start_line=1, end_line=1)

    code_bytes = code.encode("utf-8")
    tree = _parser.parse(code_bytes)
    root = tree.root_node

    # 与 parse_source 一致：语法错误直接抛出，避免静默丢失节点。
    if root.has_error:
        raise SyntaxError("Python源码存在语法错误")

    return SyntaxNode(
        kind="module",
        label="<module>",
        start_line=_line_of(root),
        end_line=_end_line_of(root),
        children=_children(root, code_bytes),
    )


