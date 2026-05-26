from dataclasses import dataclass

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
            _extract_symbol(inner, code_bytes, symbols, class_name)
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
        sym.name = "async " + sym.name
        if class_name:
            sym.qualified_name = f"{class_name}.{sym.name}"
        symbols.append(sym)

    elif node.type == "class_definition":
        class_sym = _build_symbol(node, code_bytes, kind="class")
        symbols.append(class_sym)
        body = node.child_by_field_name("body")
        if body:
            for method_node in body.children:
                _extract_symbol(method_node, code_bytes, symbols, class_sym.name)


