import pytest

from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.tools.mermaid_validator import validate_mermaid


def test_cors_origins_accepts_csv_json_and_list():
    assert Settings(cors_origins="http://a,http://b").cors_origins == ["http://a", "http://b"]
    assert Settings(cors_origins='["http://a", "http://b"]').cors_origins == ["http://a", "http://b"]
    assert Settings(cors_origins=["http://a", "http://b"]).cors_origins == ["http://a", "http://b"]


def test_cors_origins_accepts_csv_and_json_env_files(tmp_path):
    csv_env = tmp_path / "csv.env"
    csv_env.write_text("CORS_ORIGINS=http://a,http://b\n", encoding="utf-8")
    json_env = tmp_path / "json.env"
    json_env.write_text('CORS_ORIGINS=["http://a", "http://b"]\n', encoding="utf-8")

    assert Settings(_env_file=csv_env).cors_origins == ["http://a", "http://b"]
    assert Settings(_env_file=json_env).cors_origins == ["http://a", "http://b"]


@pytest.mark.parametrize("file_count", [1, 2, 3, 6])
def test_sequence_note_uses_at_most_two_participants(file_count):
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    files = [SourceFile(id=i, project_id=1, relative_path=f"src/{i}.py", line_count=1) for i in range(1, file_count + 1)]
    code, _ = orchestrator._build_sequence_diagram("repo", "", files, [], [])
    assert "Note over" in code
    assert validate_mermaid(code).valid
    note = next(line for line in code.splitlines() if "Note over" in line)
    assert note.split(":", 1)[0].count(",") <= 1


def test_sequence_precheck_rejects_three_but_accepts_two_participants():
    assert validate_mermaid("sequenceDiagram\nNote over A,B: valid").valid
    assert not validate_mermaid("sequenceDiagram\nNote over A,B,C: invalid").valid


def test_large_flowchart_is_bounded_and_has_omission_notice():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    files = [SourceFile(id=i, project_id=1, relative_path=f"src/{i}.py", line_count=1) for i in range(1, 600)]
    code, mapping = orchestrator._build_flowchart("repo", "", files, [], [])
    assert code.count("-->") <= 450
    assert len(code) <= 50000
    assert "已省略部分内容" in code
    assert mapping["UnresolvedOmitted"]["unresolved"] is True


def test_large_class_diagram_is_bounded_and_complete():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    files = [SourceFile(id=i, project_id=1, relative_path=f"src/{i}.py", line_count=3) for i in range(1, 100)]
    symbols = [
        Symbol(
            id=i,
            project_id=1,
            file_id=i,
            name=f"Class{i}",
            kind="class",
            start_line=1,
            end_line=3,
            signature=f"class Class{i}",
        )
        for i in range(1, 100)
    ]
    code, mapping = orchestrator._build_class_diagram("repo", "", files, symbols, [])
    assert code.count("class ") <= 81
    assert len(code) <= 50000
    assert not code.rstrip().endswith("{")
    assert "UnresolvedOmitted" in code
    assert mapping["UnresolvedOmitted"]["unresolved"] is True


def test_mermaid_validator_rejects_oversized_source():
    result = validate_mermaid("flowchart TD\n" + ("A-->B\n" * 10000))
    assert result.valid is False
    assert any("50000" in item for item in result.errors)


def test_hundred_files_with_multiple_symbols_are_bounded():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    files = [SourceFile(id=i, project_id=1, relative_path=f"src/module_{i}.py", line_count=30) for i in range(1, 101)]
    symbols = []
    for file in files:
        symbols.append(Symbol(id=len(symbols) + 1, project_id=1, file_id=file.id, name=f"Service{file.id}", kind="class", start_line=1, end_line=30))
        symbols.extend(Symbol(id=1000 + file.id * 10 + j, project_id=1, file_id=file.id, name=f"method_{j}", kind="method", start_line=j + 2, end_line=j + 3) for j in range(8))
    flow, flow_mapping = orchestrator._build_flowchart("repo", "", files, symbols, [])
    classes, class_mapping = orchestrator._build_class_diagram("repo", "", files, symbols, [])
    for code, mapping in [(flow, flow_mapping), (classes, class_mapping)]:
        assert len(code) <= 50000
        assert "已省略部分内容" in code
        assert mapping["UnresolvedOmitted"]["unresolved"] is True
        assert validate_mermaid(code).valid
        # 完全省略的文件不能残留定位映射。
        assert not any(info.get("file_id") == 100 for info in mapping.values())
    assert flow.count("-->") <= 450
    assert classes.count("{") == classes.count("}")
    assert classes.count("class ") <= 81
