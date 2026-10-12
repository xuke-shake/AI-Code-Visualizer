"""R04-A2/D/E：真实 API 和冻结快照的证据合同，不执行被分析源码。"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.context_builder import build_code_context
from app.models.code_chunk import CodeChunk
from app.models.symbol import Symbol
from test_r04_r06_contract import _analyze, _provider, _setup


DIAGRAMS = ["flowchart", "sequence", "state", "architecture"]
BODIES = {
    "lambda-default": "def target(PADDING=(lambda PADDING: PADDING)):\n    return REQUIRED\nENTRY = target\n",
    "comprehension-default": "def target(PADDING=[PADDING for PADDING in range(3)]):\n    return REQUIRED\nENTRY = target\n",
    "class-fallback": "class target:\n    REQUIRED = REQUIRED\nENTRY = target\n",
    "same-name-alias": "def target():\n    return REQUIRED\nPREVIOUS = target\ndef target():\n    return PREVIOUS()\nENTRY = target\n",
}


def _context(calls, response, client, headers):
    assert response.status_code == 200 and response.json()["data"]["status"] == "success", response.text
    assert len(calls) == 1
    task = client.get(f"/api/tasks/{response.json()['data']['task_id']}", headers=headers)
    assert task.status_code == 200 and task.json()["data"]["status"] == "success", task.text
    context = calls[0].split("【源码上下文】\n", 1)[1].rstrip("\n")
    assert len(context) <= 12000 and "main.py | 行" in context
    return context


@pytest.mark.parametrize("diagram_type", DIAGRAMS)
@pytest.mark.parametrize("sample", list(BODIES))
@pytest.mark.parametrize("pressure", [False, True], ids=["short-header", "literal-budget-pressure"])
def test_definition_evidence_reaches_real_provider(
    client, auth_header, test_database, monkeypatch, diagram_type, sample, pressure
):
    size = (11550 if sample == "same-name-alias" else 11700) if pressure else 8
    source = "PADDING = " + repr("x" * size) + "\nREQUIRED = 123\n" + BODIES[sample]
    # 确认测试确实写入大字面量，不是仅写一个短乘法表达式。
    if pressure:
        assert "x" * size in source and "* 11700" not in source
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["main.py"], "分析 target")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context
    assert "ENTRY = target" in context
    if pressure:
        assert "x" * 1000 not in context and "省略" in context
    with test_database["session_factory"]() as db:
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
        assert module.content == "\n".join(source.splitlines())
        assert (module.start_line, module.end_line) == (1, len(source.splitlines()))
        definitions = db.scalars(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target").order_by(Symbol.start_line)).all()
        if sample == "same-name-alias":
            assert [(s.start_line, s.end_line) for s in definitions] == [(3, 4), (6, 7)]
            assert "PREVIOUS = target" in context and context.count("def target():") == 2
            assert "行 3-4" in context and "行 6-7" in context
        else:
            assert len(definitions) == 1


@pytest.mark.parametrize("diagram_type", DIAGRAMS)
@pytest.mark.parametrize("body", [
    "    PADDING = 0\n    VALUE = PADDING\n",
    "    if REQUIRED:\n        PADDING = 0\n    else:\n        PADDING = 1\n    VALUE = PADDING\n",
    "    PADDING: int = 0\n    PADDING += 1\n    VALUE = PADDING\n",
], ids=["bound-before-read", "bound-on-both-branches", "annotated-and-augmented"])
def test_class_bound_locals_do_not_import_large_module_names(client, auth_header, monkeypatch, diagram_type, body):
    source = "PADDING = " + repr("x" * 11700) + "\nREQUIRED = 123\nclass target:\n" + body + "    RESULT = REQUIRED\nENTRY = target\n"
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["main.py"], "分析 target")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context and "ENTRY = target" in context
    assert "x" * 1000 not in context


def test_class_partial_branch_read_keeps_global_fallback(client, auth_header, monkeypatch):
    source = ("PADDING = " + repr("x" * 11700) + "\nREQUIRED = 123\nclass target:\n"
              "    if __name__ == '__main__':\n        REQUIRED = 0\n    VALUE = REQUIRED\nENTRY = target\n")
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 target")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context and "x" * 1000 not in context


def test_original_outer_closure_is_preserved_for_header_expressions(client, auth_header, monkeypatch):
    source = ("PADDING = " + repr("x" * 11700) + "\nREQUIRED = 123\n"
              "def outer():\n    PADDING = 0\n"
              "    def inner(value=(PADDING, lambda PADDING: PADDING, [PADDING for PADDING in range(3)])):\n"
              "        return REQUIRED\n    return inner()\nENTRY = outer\n")
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 outer")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context and "ENTRY = outer" in context and "x" * 1000 not in context


def test_range_identity_preserves_distinct_chunk_fallbacks():
    # 兼容旧块回退的普通 DTO 对照；不替代上面的真实 API 用例。
    file = SimpleNamespace(id=1, relative_path="main.py")
    symbols = [SimpleNamespace(file_id=1, name="target", qualified_name=None, start_line=start, end_line=start+1, signature=None) for start in (1, 5)]
    chunks = [SimpleNamespace(file_id=1, chunk_type="function", symbol_name="target", start_line=1, end_line=2, content="def target():\n    return REQUIRED"),
              SimpleNamespace(file_id=1, chunk_type="function", symbol_name="target", start_line=5, end_line=6, content="def target():\n    return PREVIOUS()")]
    context = build_code_context([file], symbols, chunks, "target", 12000)
    assert "return REQUIRED" in context and "return PREVIOUS()" in context
    assert "行 1-2" in context and "行 5-6" in context


def test_class_trailing_comment_keeps_parser_range_and_global_fallback(client, auth_header, test_database, monkeypatch):
    source = ("PADDING = " + repr("x" * 11550) + "\nREQUIRED = 123\n"
              "class target:\n    REQUIRED = REQUIRED\n    # class tail\nENTRY = target\n")
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 target")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context and "ENTRY = target" in context
    assert "# class tail" in context and "行 3-5" in context
    if "PADDING = " in context:
        assert context.index("REQUIRED = 123") < context.index("PADDING = ")
    with test_database["session_factory"]() as db:
        symbol = db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target"))
        assert (symbol.start_line, symbol.end_line) == (3, 5)


def test_class_name_matching_anonymous_scope_preserves_definition_identity(client, auth_header, monkeypatch):
    source = ("PADDING = " + repr("x" * 11700) + "\nREQUIRED = 123\n"
              "class listcomp: VALUES = [PADDING for PADDING in range(3)]; REQUIRED = REQUIRED\nENTRY = listcomp\n")
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 listcomp")
    context = _context(calls, response, client, auth_header)
    assert "REQUIRED = 123" in context and "ENTRY = listcomp" in context
    assert "x" * 1000 not in context
