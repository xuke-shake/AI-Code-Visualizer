"""R04-D4/D5：普通语句求值边界，真实 API 到本地 Provider 的证据回归。"""
import ast
import symtable

import pytest

from app.agents.context_builder import _class_reads
from test_r04_d2_d3_contract import _assert_api_evidence


DIAGRAMS = ["flowchart", "sequence", "state", "architecture"]
SAMPLES = {
    "d4-assert-optional-message": (
        "123", "    assert __name__, (REQUIRED := 0)\n    VALUE = REQUIRED\n", 11680,
    ),
    "assert-ordinary-message-control": (
        "123", "    assert __name__, 0\n    VALUE = REQUIRED\n", 11680,
    ),
    "d5-annotation-subscript-no-rhs": (
        "[0]", "    REQUIRED[0]: int\n    REQUIRED = 0\n", 11680,
    ),
    "annotation-subscript-with-rhs-control": (
        "[0]", "    REQUIRED[0]: int = 1\n    REQUIRED = 0\n", 11680,
    ),
    "d5-annotation-attribute-no-rhs": (
        "SimpleNamespace(value=0)", "    REQUIRED.value: int\n    REQUIRED = 0\n", 11600,
    ),
    "annotation-attribute-with-rhs-control": (
        "SimpleNamespace(value=0)", "    REQUIRED.value: int = 1\n    REQUIRED = 0\n", 11600,
    ),
}


@pytest.mark.parametrize("diagram_type", DIAGRAMS)
@pytest.mark.parametrize("sample", list(SAMPLES))
@pytest.mark.parametrize("pressure", [False, True], ids=["short-header", "literal-budget-pressure"])
def test_assert_and_annotation_evidence_reaches_real_provider(
    client, auth_header, test_database, monkeypatch, diagram_type, sample, pressure
):
    definition, body, size = SAMPLES[sample]
    # 共享 helper 用 repr("x" * size) 生成实际字面量，执行真实上传/解析/分析。
    # 检查实际唯一 Provider、任务、必要定义、目标行号、完整 module/Symbol 和预算。
    _assert_api_evidence(client, auth_header, test_database, monkeypatch, definition, body, size if pressure else 8, diagram_type)


# 最后两列是首部长度及 PADDING 是否真正回退到模块。
# 需要模块大常量的正例使用短首部，避免把合法的证据不足当作绑定缺陷；
# 负例在压力下保证局部绑定没有抢占必要 REQUIRED 的预算。
BOUNDARY_CASES = [
    ("assert-message-read", "123", "    assert __name__, REQUIRED\n    REQUIRED = 0\n", 11680, False),
    ("assert-message-rhs-read", "123", "    assert __name__, (LOCAL := REQUIRED)\n    REQUIRED = 0\n", 11680, False),
    ("assert-message-self-read", "123", "    assert __name__, (REQUIRED := REQUIRED)\n    REQUIRED = 0\n", 11680, False),
    ("assert-test-binding", "123", "    assert (PADDING := 1), 0\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11680, False),
    ("assert-test-read", "123", "    assert REQUIRED, 0\n    REQUIRED = 0\n", 11680, False),
    ("assert-no-message", "123", "    assert REQUIRED\n    REQUIRED = 0\n", 11680, False),
    ("assert-message-binding-isolated", "123", "    assert __name__, (PADDING := 0)\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 8, True),
    ("bare-name-does-not-bind", "123", "    REQUIRED: int\n    VALUE = REQUIRED\n", 11680, False),
    ("bare-name-keeps-existing-binding", "123", "    PADDING = 0\n    PADDING: int\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11680, False),
    ("local-subscript-object", "123", "    PADDING = [0]\n    PADDING[0]: int\n    RESULT = REQUIRED\n", 11680, False),
    ("local-attribute-object", "123", "    PADDING = object()\n    PADDING.value: int\n    RESULT = REQUIRED\n", 11680, False),
    ("subscript-object-binding", "123", "    (PADDING := [0])[0]: int\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11680, False),
    ("subscript-slice-binding", "[0]", "    REQUIRED[(PADDING := 0)]: int\n    VALUE = PADDING\n    REQUIRED = 0\n", 11640, False),
    ("subscript-object-before-slice-binding", "[0]", "    REQUIRED[(REQUIRED := 0)]: int\n    VALUE = REQUIRED\n", 11680, False),
    ("attribute-object-binding", "123", "    (PADDING := object()).value: int\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11680, False),
    ("annotation-expression-binding", "123", "    REQUIRED: (PADDING := int)\n    VALUE = PADDING\n    RESULT = REQUIRED\n", 11680, False),
    ("subscript-slice-conditional-binding", "[0]", "    REQUIRED[(PADDING := 0) if __name__ else 0]: int\n    VALUE = PADDING\n    REQUIRED = 0\n", 8, True),
    ("subscript-slice-lambda-isolated", "[0]", "    REQUIRED[(lambda PADDING: PADDING)(0)]: int\n    REQUIRED = 0\n", 11680, False),
    ("subscript-slice-comprehension-isolated", "[0]", "    REQUIRED[[PADDING for PADDING in [0]][0]]: int\n    REQUIRED = 0\n", 11680, False),
    ("local-subscript-with-rhs", "123", "    PADDING = [0]\n    PADDING[0]: int = 1\n    RESULT = REQUIRED\n", 11680, False),
]


@pytest.mark.parametrize("case,definition,body,size,padding_read", BOUNDARY_CASES, ids=[row[0] for row in BOUNDARY_CASES])
def test_statement_binding_boundaries_in_real_api(
    client, auth_header, test_database, monkeypatch, case, definition, body, size, padding_read
):
    _assert_api_evidence(client, auth_header, test_database, monkeypatch, definition, body, size)
    # API 证据之外再检查分类：短首部会容纳可选证据，不能靠其存在判断必要依赖。
    # 仅解析 AST/符号表，绝不执行或导入被分析源码。
    source = "PADDING = " + repr("x" * size) + "\nREQUIRED = " + definition + "\nclass target:\n" + body
    tree = ast.parse(source)
    module_scope = symtable.symtable(source, "<boundary>", "exec")
    dependencies, _ = _class_reads(tree.body[-1], module_scope.get_children()[0], module_scope)
    assert "REQUIRED" in dependencies
    assert ("PADDING" in dependencies) is padding_read
