"""parse_tree() 嵌套语法树解析的单元测试。

覆盖 if/elif/else、for/while、return、raise、try/except/finally、
函数调用、match/case、break/continue/pass、嵌套函数，以及向后兼容。
"""
import pytest

from app.parsing.tree_parser import parse_source, parse_tree


def _walk(node):
    """先序遍历，返回 [(kind, label, start_line, end_line), ...]。"""
    out = [(node.kind, node.label, node.start_line, node.end_line)]
    for child in node.children:
        out.extend(_walk(child))
    return out


def _kinds(node):
    return [item[0] for item in _walk(node)]


def test_parse_tree_if_elif_else():
    tree = parse_tree("if a:\n    x()\nelif b:\n    y()\nelse:\n    z()\n")
    assert tree.kind == "module"

    if_node = tree.children[0]
    assert if_node.kind == "if"
    assert if_node.label == "if a"
    assert if_node.start_line == 1
    assert if_node.end_line == 6

    # 顺序：if 分支体里的调用，随后是 elif 与 else
    assert [c.kind for c in if_node.children] == ["call", "elif", "else"]
    assert if_node.children[0].label == "x"
    assert if_node.children[1].label == "elif b"
    assert if_node.children[1].start_line == 3
    assert if_node.children[2].label == "else"
    assert [c.kind for c in if_node.children[2].children] == ["call"]


def test_parse_tree_loops_with_break_continue():
    code = "for i in range(3):\n    print(i)\n    break\nwhile x:\n    continue\n"
    tree = parse_tree(code)

    for_node = tree.children[0]
    assert for_node.kind == "for"
    assert for_node.label == "for i in range(3)"
    assert [c.kind for c in for_node.children] == ["call", "break", "call"]
    assert for_node.children[0].label == "print"
    assert for_node.children[1].kind == "break"
    assert for_node.children[2].label == "range"

    while_node = tree.children[1]
    assert while_node.kind == "while"
    assert while_node.label == "while x"
    assert [c.kind for c in while_node.children] == ["continue"]


def test_parse_tree_return_and_raise():
    code = "def f(x):\n    return x\n    return g(x)\n    raise\n    raise e\n"
    tree = parse_tree(code)
    fn = tree.children[0]
    assert fn.kind == "function"

    returns = [c for c in fn.children if c.kind == "return"]
    assert [r.label for r in returns] == ["return x", "return g(x)"]
    assert [c.kind for c in returns[1].children] == ["call"]
    assert returns[1].children[0].label == "g"

    raises = [c for c in fn.children if c.kind == "raise"]
    assert [r.label for r in raises] == ["raise", "raise e"]


def test_parse_tree_try_except_finally():
    code = (
        "try:\n"
        "    y = g(x)\n"
        "except ValueError as e:\n"
        "    raise e\n"
        "except KeyError:\n"
        "    raise\n"
        "finally:\n"
        "    pass\n"
    )
    tree = parse_tree(code)
    try_node = tree.children[0]
    assert try_node.kind == "try"
    assert try_node.label == "try"

    assert [c.kind for c in try_node.children] == ["call", "except", "except", "finally"]
    assert try_node.children[0].label == "g"
    assert try_node.children[1].label == "except ValueError as e"
    assert [c.kind for c in try_node.children[1].children] == ["raise"]
    assert try_node.children[2].label == "except KeyError"
    assert [c.kind for c in try_node.children[3].children] == ["pass"]


def test_parse_tree_function_calls():
    code = "def h(obj, x):\n    obj.meth(1, key=2)\n    return g(x)\n"
    tree = parse_tree(code)
    fn = tree.children[0]

    method_call = fn.children[0]
    assert method_call.kind == "call"
    assert method_call.label == "obj.meth"

    ret = fn.children[1]
    assert ret.kind == "return"
    assert ret.children[0].kind == "call"
    assert ret.children[0].label == "g"


def test_parse_tree_match_case():
    code = "match x:\n    case 0:\n        pass\n    case _:\n        h(x)\n"
    tree = parse_tree(code)
    match_node = tree.children[0]
    assert match_node.kind == "match"
    assert match_node.label == "match x"

    assert [c.kind for c in match_node.children] == ["case", "case"]
    assert match_node.children[0].label == "case 0"
    assert [c.kind for c in match_node.children[0].children] == ["pass"]
    assert match_node.children[1].label == "case _"
    assert match_node.children[1].children[0].kind == "call"
    assert match_node.children[1].children[0].label == "h"


def test_parse_tree_nested_function():
    code = "def outer():\n    def inner(x):\n        if x:\n            return x\n    return inner()\n"
    tree = parse_tree(code)
    outer = tree.children[0]

    inner = outer.children[0]
    assert inner.kind == "function"
    assert inner.label == "def inner(x)"

    if_node = inner.children[0]
    assert if_node.kind == "if"
    assert [c.kind for c in if_node.children] == ["return"]

    ret = outer.children[1]
    assert ret.kind == "return"
    assert ret.children[0].kind == "call"
    assert ret.children[0].label == "inner"


def test_parse_tree_syntax_error():
    with pytest.raises(SyntaxError):
        parse_tree("def f(:\n    return 1\n")


def test_parse_tree_empty():
    for code in ("", "   \n\t"):
        tree = parse_tree(code)
        assert tree.kind == "module"
        assert tree.children == []


def test_parse_source_unchanged():
    code = "def f(x):\n    return x\n\nclass A:\n    def m(self):\n        pass\n"
    symbols = parse_source(code)
    assert [(s.name, s.kind, s.start_line, s.end_line) for s in symbols] == [
        ("f", "function", 1, 2),
        ("A", "class", 4, 6),
        ("m", "method", 5, 6),
    ]
