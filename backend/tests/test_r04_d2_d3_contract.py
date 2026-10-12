"""R04-D2/D3：类体表达式及目标求值顺序，真实 API/本地 Provider。"""
import pytest
from sqlalchemy import select

from app.models.code_chunk import CodeChunk
from app.models.symbol import Symbol
from test_r04_a2_de_contract import _context
from test_r04_r06_contract import _analyze, _provider, _setup


DIAGRAMS = ["flowchart", "sequence", "state", "architecture"]
SAMPLES = {
    "d2-named-expression": ("123", "    (PADDING := 0)\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11700),
    "d3-mixed-unpack": ("[0]", "    (LOCAL, REQUIRED[0]) = (1, 2)\n    REQUIRED = 0\n", 11640),
    "ordinary-assignment-control": ("123", "    PADDING = 0\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11700),
    "standalone-subscript-control": ("[0]", "    REQUIRED[0] = 2\n    REQUIRED = 0\n", 11640),
}


def _assert_api_evidence(client, auth_header, test_database, monkeypatch, definition, body, size, diagram_type="flowchart"):
    imports = "from types import SimpleNamespace\n" if definition.startswith("SimpleNamespace") else ""
    padding = "PADDING = " + repr("x" * size)
    required = "REQUIRED = " + definition
    source = imports + padding + "\n" + required + "\nclass target:\n" + body + "ENTRY = target\n"
    assert repr("x" * size) in source  # 源码含实际大字面量，不是短乘法表达式。
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["main.py"], "分析 target")
    context = _context(calls, response, client, auth_header)
    assert required in context
    assert "class target:" in context and "ENTRY = target" in context
    assert all(line in context for line in body.splitlines())
    if size > 1000 and padding in context:
        # 可选常量装得下时允许展示；必要证据必须先选入。
        assert context.index(required) < context.index(padding)
    start = 3 + len(imports.splitlines())
    end = start + len(body.splitlines())
    assert f"行 {start}-{end}" in context
    with test_database["session_factory"]() as db:
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
        assert module.content == "\n".join(source.splitlines())
        assert (module.start_line, module.end_line) == (1, len(source.splitlines()))
        symbol = db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target"))
        assert (symbol.start_line, symbol.end_line) == (start, end)


@pytest.mark.parametrize("diagram_type", DIAGRAMS)
@pytest.mark.parametrize("sample", list(SAMPLES))
@pytest.mark.parametrize("pressure", [False, True], ids=["short-header", "literal-budget-pressure"])
def test_new_class_boundaries_and_controls_reach_real_provider(
    client, auth_header, test_database, monkeypatch, diagram_type, sample, pressure
):
    definition, body, size = SAMPLES[sample]
    _assert_api_evidence(client, auth_header, test_database, monkeypatch, definition, body, size if pressure else 8, diagram_type)


ORDER_CASES = [
    ("walrus-rhs-before-bind", "123", "    (REQUIRED := REQUIRED)\n    RESULT = REQUIRED\n"),
    ("same-expression-bind-before-read", "123", "    VALUE = ((PADDING := 0), PADDING)\n    RESULT = REQUIRED\n"),
    ("same-expression-read-before-bind", "123", "    VALUE = (REQUIRED, (REQUIRED := 0))\n"),
    ("and-optional-binding", "123", "    VALUE = __name__ and (REQUIRED := 0)\n    RESULT = REQUIRED\n"),
    ("or-optional-binding", "123", "    VALUE = __name__ or (REQUIRED := 0)\n    RESULT = REQUIRED\n"),
    ("and-first-binding", "123", "    VALUE = (PADDING := 0) and PADDING\n    RESULT = REQUIRED\n"),
    ("and-later-path-binding", "123", "    VALUE = __name__ and (PADDING := 0) and PADDING\n    RESULT = REQUIRED\n"),
    ("conditional-one-arm", "123", "    VALUE = (REQUIRED := 0) if __name__ else 0\n    RESULT = REQUIRED\n"),
    ("conditional-both-arms", "123", "    VALUE = (PADDING := 0) if __name__ else (PADDING := 1)\n    CHECK = PADDING\n    RESULT = REQUIRED\n"),
    ("conditional-test-binding", "123", "    VALUE = 1 if (PADDING := 0) else 2\n    CHECK = PADDING\n    RESULT = REQUIRED\n"),
    ("lambda-body-binding-isolated", "123", "    FN = lambda: (REQUIRED := 0)\n    VALUE = REQUIRED\n    REQUIRED = 0\n"),
    ("lambda-parameter-isolated", "123", "    FN = lambda PADDING: PADDING\n    RESULT = REQUIRED\n"),
    ("lambda-default-outer-binding", "123", "    FN = lambda value=(PADDING := 0): value\n    CHECK = PADDING\n    RESULT = REQUIRED\n"),
    ("comprehension-binding-isolated", "123", "    VALUE = [REQUIRED for REQUIRED in range(2)]\n    RESULT = REQUIRED\n    REQUIRED = 0\n"),
    ("comprehension-local-filter", "123", "    VALUE = [PADDING for PADDING in range(2)]\n    RESULT = REQUIRED\n"),
    ("list-target-container-read", "[0]", "    [LOCAL, REQUIRED[0]] = [1, 2]\n    REQUIRED = 0\n"),
    ("starred-target-container-read", "[0]", "    LOCAL, *REQUIRED[0] = [1, 2, 3]\n    REQUIRED = 0\n"),
    ("attribute-target-object-read", "SimpleNamespace(value=0)", "    (LOCAL, REQUIRED.value) = (1, 2)\n    REQUIRED = 0\n"),
    ("unpack-bind-before-container-read", "123", "    (PADDING, PADDING[0]) = ([0], 2)\n    RESULT = REQUIRED\n"),
    ("unpack-container-read-before-bind", "[0]", "    (REQUIRED[0], REQUIRED) = (2, 0)\n"),
    ("unpack-bind-before-index-read", "123", "    (LOCAL, LOCAL[REQUIRED]) = ({}, 2)\n    REQUIRED = 0\n"),
    ("subscript-index-walrus-binding", "123", "    LOCAL = {}\n    LOCAL[(PADDING := 0)] = 1\n    VALUE = PADDING\n    RESULT = REQUIRED\n"),
    ("dict-key-before-value", "123", "    VALUE = {(PADDING := 0): PADDING}\n    RESULT = REQUIRED\n"),
    ("comparison-first-binding", "123", "    VALUE = (PADDING := 0) < 1 < PADDING\n    RESULT = REQUIRED\n"),
    ("comparison-optional-binding", "123", "    VALUE = 1 < 0 < (REQUIRED := 0)\n    RESULT = REQUIRED\n"),
    ("lambda-global-read-skips-class", "123", "    FN = lambda: REQUIRED\n    REQUIRED = 0\n    RESULT = REQUIRED\n"),
]


@pytest.mark.parametrize("case,definition,body", ORDER_CASES, ids=[row[0] for row in ORDER_CASES])
def test_class_expression_and_target_order_in_real_api(client, auth_header, test_database, monkeypatch, case, definition, body):
    size = 11700 if definition == "123" else 11640
    _assert_api_evidence(client, auth_header, test_database, monkeypatch, definition, body, size)
