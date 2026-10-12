from app.tools.mermaid_validator import validate_mermaid
from app.schemas.diagram import AnalysisCreate
from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings
from app.models.source_file import SourceFile
from app.models.symbol import Symbol


def test_mermaid_expected_type_and_exact_declaration():
    assert not validate_mermaid("flowchart TD\nA-->B", expected_type="state").valid
    assert not validate_mermaid("flowchartXYZ\nA-->B").valid
    assert validate_mermaid("stateDiagram-v2\n[*] --> A", expected_type="state").valid


def test_prompt_is_trimmed_and_blank_rejected():
    assert AnalysisCreate(prompt="  生成流程图  ").prompt == "生成流程图"
    try:
        AnalysisCreate(prompt="   ")
    except Exception as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("blank prompt unexpectedly accepted")


def test_llm_output_type_mismatch_is_rejected(monkeypatch):
    class FakeProvider:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, **kwargs):
            return "flowchart TD\nA-->B"

    import app.agents.llm_provider as provider_module
    monkeypatch.setattr(provider_module, "LLMProvider", FakeProvider)
    result, error = AgentOrchestrator(Settings(llm_enabled="model", llm_api_key="test-key"))._try_llm_mermaid(
        "repo", "生成状态图", "state", "class Service: pass", "A", ""
    )
    assert result is None
    assert "图表类型不匹配" in (error or "")


def test_class_diagram_uses_readable_python_labels_and_skips_readme():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    py_file = SourceFile(id=1, project_id=1, relative_path="src/main.py", line_count=3)
    readme = SourceFile(id=2, project_id=1, relative_path="README.md", line_count=1)
    symbol = Symbol(id=1, project_id=1, file_id=1, name="Service", kind="class", start_line=1, end_line=3)
    code, _ = orchestrator._build_class_diagram("repo", "", [py_file, readme], [symbol], [])
    assert "src/main.py" in code
    assert "Service" in code
    assert "README" not in code
    assert "Module_" not in code.split("[")[-1]
