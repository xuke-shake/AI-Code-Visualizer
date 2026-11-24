"""控制流图（build_cfg）的结构契约测试。"""
import pytest

from app.parsing.control_flow_analyzer import build_cfg


def _fn(g, name):
    return [n for n in g.nodes if n.function == name]


def _kinds(g, name):
    return [n.kind for n in _fn(g, name)]


def _edges_of(g, node_id):
    return [e for e in g.edges if e.source == node_id]


def _edge_kinds(g):
    return sorted(e.kind for e in g.edges)


def test_simple_function_return_path():
    g = build_cfg("def f(x):\n    return x + 1\n")
    assert sorted(_kinds(g, "f")) == ["entry", "exit", "return"]
    ret = next(n for n in _fn(g, "f") if n.kind == "return")
    assert [e.kind for e in _edges_of(g, ret.id)] == ["return"]


def test_if_else_branches():
    g = build_cfg("def f(x):\n    if x:\n        a()\n    else:\n        b()\n    c()\n")
    assert "if" in _kinds(g, "f")
    if_node = next(n for n in _fn(g, "f") if n.kind == "if")
    outgoing = [e.kind for e in _edges_of(g, if_node.id)]
    assert "true" in outgoing and "false" in outgoing
    assert len([n for n in _fn(g, "f") if n.kind == "stmt"]) == 3  # a / b / c


def test_loop_with_break_and_continue():
    g = build_cfg("def f():\n    for i in range(3):\n        if i:\n            break\n        continue\n    return\n")
    kinds = _kinds(g, "f")
    for expected in ("for", "loop_exit", "break", "continue", "return", "exit"):
        assert expected in kinds
    assert "break" in _edge_kinds(g)
    assert "continue" in _edge_kinds(g)


def test_try_except_finally_and_raise():
    g = build_cfg(
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError:\n"
        "        raise\n"
        "    finally:\n"
        "        h()\n"
    )
    kinds = _kinds(g, "f")
    for expected in ("try", "except", "finally", "raise", "exit"):
        assert expected in kinds
    # 异常路径：try -> except 与 raise -> exit
    try_node = next(n for n in _fn(g, "f") if n.kind == "try")
    assert [e.kind for e in _edges_of(g, try_node.id) if e.kind == "exception"]
    raise_node = next(n for n in _fn(g, "f") if n.kind == "raise")
    assert [e.kind for e in _edges_of(g, raise_node.id)] == ["exception"]


def test_match_case_branches():
    g = build_cfg(
        "def f(x):\n"
        "    match x:\n"
        "        case 1:\n"
        "            a()\n"
        "        case _:\n"
        "            b()\n"
    )
    kinds = _kinds(g, "f")
    assert kinds.count("case") == 2
    assert "match" in kinds
    assert _edge_kinds(g).count("case") == 2


def test_nested_function_gets_own_cfg():
    g = build_cfg("def outer():\n    def inner():\n        return 1\n    return inner()\n")
    assert "return" in _kinds(g, "outer.inner")
    assert "return" in _kinds(g, "outer")


def test_method_and_module_level():
    g = build_cfg(
        "class C:\n"
        "    def m(self):\n"
        "        if self.x:\n"
        "            return\n"
        "print(1)\n"
    )
    assert "if" in _kinds(g, "C.m")
    assert "entry" in _kinds(g, "<module>")
    assert any(n.kind == "stmt" for n in _fn(g, "<module>"))


def test_syntax_error_raises():
    with pytest.raises(SyntaxError):
        build_cfg("def f(:\n    pass\n")


def test_empty_code():
    g = build_cfg("")
    assert _kinds(g, "<module>") == ["entry"]
