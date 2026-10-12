"""R04-A/B、R05-A：真实上传/解析/同步/分析边界，不替换业务服务。"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.context_builder import _names, build_code_context
from app.models.code_chunk import CodeChunk
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from test_r04_r06_contract import _analyze, _provider, _setup, _zip


DIAGRAM_TYPES = ["flowchart", "sequence", "state", "architecture"]


def _sync(client, headers, project_id):
    response = client.post(f"/api/projects/{project_id}/sync", headers=headers, json={"mode": "sync"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "success", response.text
    task_id = response.json()["data"]["task_id"]
    task = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert task.status_code == 200, task.text
    assert task.json()["data"]["status"] == "success"
    return task.json()["data"]["result_json"]


def _replace_temp_zip(test_database, upload_id, files):
    # 仅改 fixture 的临时上传对象；真实 scan/sync/parser/chunker 处理内容变化。
    with test_database["session_factory"]() as db:
        path = test_database["storage_path"] / db.get(Upload, upload_id).object_key
        assert path.resolve().is_relative_to(test_database["storage_path"].resolve())
        path.write_bytes(_zip(files))


def _index_rows(db, project_id):
    return {
        "files": [(s.id, s.relative_path, s.line_count, s.file_hash, s.parse_status)
                  for s in db.scalars(select(SourceFile).where(SourceFile.project_id == project_id).order_by(SourceFile.id))],
        "symbols": [(s.id, s.file_id, s.name, s.kind, s.start_line, s.end_line)
                    for s in db.scalars(select(Symbol).where(Symbol.project_id == project_id).order_by(Symbol.id))],
        "chunks": [(c.id, c.file_id, c.chunk_type, c.symbol_name, c.start_line, c.end_line, c.content)
                   for c in db.scalars(select(CodeChunk).where(CodeChunk.project_id == project_id).order_by(CodeChunk.id))],
    }


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("blank_lines", [1, 3], ids=["one-empty-tail", "three-empty-tails"])
@pytest.mark.parametrize("created_by", ["full", "incremental"])
def test_tail_empty_lines_keep_current_contract_and_diagrams(
    client, auth_header, test_database, monkeypatch, newline, blank_lines, created_by
):
    source = ("def target():\n    return 1\n" + "\n" * blank_lines).replace("\n", newline)
    files = {"target.py": source}
    if created_by == "full":
        project_id, upload_id = _setup(client, auth_header, files)
    else:
        files["base.py"] = "BASE = 1\n"
        project_id, upload_id = _setup(client, auth_header, {"base.py": files["base.py"]})
        _replace_temp_zip(test_database, upload_id, files)
        result = _sync(client, auth_header, project_id)
        assert result["added"] == ["target.py"] and result["modified"] == result["deleted"] == []
    calls = _provider(monkeypatch)
    generated = _analyze(client, auth_header, project_id, selected=["target.py"])
    assert generated.status_code == 200 and generated.json()["data"]["status"] == "success", generated.text
    diagram_id = generated.json()["data"]["diagram_id"]
    with test_database["session_factory"]() as db:
        revision = db.get(Project, project_id).last_index_version
        before = _index_rows(db, project_id)
        sf = db.scalar(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.relative_path == "target.py"))
        module = db.scalar(select(CodeChunk).where(CodeChunk.file_id == sf.id, CodeChunk.chunk_type == "module"))
        assert sf.line_count == len(source.splitlines()) == 2 + blank_lines
        assert module.content == "\n".join(source.splitlines())
        assert (module.start_line, module.end_line) == (1, sf.line_count)
        assert not db.get(Diagram, diagram_id).is_outdated
    result = _sync(client, auth_header, project_id)
    assert result["added"] == result["modified"] == result["deleted"] == []
    assert result["outdated_diagrams"] == 0
    with test_database["session_factory"]() as db:
        project = db.get(Project, project_id)
        assert project.status == "ready" and project.last_index_version == revision
        assert _index_rows(db, project_id) == before
        assert not db.get(Diagram, diagram_id).is_outdated
    again = _analyze(client, auth_header, project_id, selected=["target.py"])
    assert again.status_code == 200 and again.json()["data"]["status"] == "success", again.text
    assert len(calls) == 2 and all("return 1" in call for call in calls)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_changed_tail_module_is_checked_using_its_serialized_lines(client, auth_header, test_database, newline):
    original = "def target():\n    return 1\n\n\n".replace("\n", newline)
    project_id, upload_id = _setup(client, auth_header, {"target.py": original})
    with test_database["session_factory"]() as db:
        old_revision = db.get(Project, project_id).last_index_version
    updated = "def target():\n    return 2\n\n\n".replace("\n", newline)
    _replace_temp_zip(test_database, upload_id, {"target.py": updated})
    result = _sync(client, auth_header, project_id)
    assert result["modified"] == ["target.py"]
    with test_database["session_factory"]() as db:
        project = db.get(Project, project_id)
        assert project.status == "ready" and project.last_index_version != old_revision
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
        assert module.content == "\n".join(updated.splitlines())
    revision = project.last_index_version
    _sync(client, auth_header, project_id)
    with test_database["session_factory"]() as db:
        assert db.get(Project, project_id).last_index_version == revision


@pytest.mark.parametrize("diagram_type", DIAGRAM_TYPES)
@pytest.mark.parametrize("shadow", ["local", "parameter", "closure"])
def test_local_shadow_does_not_displace_real_global_evidence(
    client, auth_header, test_database, monkeypatch, diagram_type, shadow
):
    bodies = {
        "local": "def critical_route():\n    PADDING = 0\n    return actual_helper(REQUIRED) + PADDING\n",
        "parameter": "def critical_route(PADDING=0):\n    return actual_helper(REQUIRED) + PADDING\n",
        "closure": "def critical_route():\n    PADDING = 0\n    def inner():\n        return actual_helper(REQUIRED) + PADDING\n    return inner()\n",
    }
    source = ("from helper import actual_helper\nPADDING = " + repr("x" * 11700)
              + "\nREQUIRED = 123\n" + bodies[shadow] + "ENTRY = critical_route\n")
    project_id, _ = _setup(client, auth_header, {"route.py": source, "helper.py": "def actual_helper(value):\n    return value\n"})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["route.py"], "分析 critical_route")
    assert response.status_code == 200 and response.json()["data"]["status"] == "success", response.text
    assert len(calls) == 1
    context = calls[0].split("【源码上下文】\n", 1)[1].rstrip("\n")
    assert len(context) <= 12000
    for evidence in ["def critical_route(", "actual_helper(REQUIRED)", "REQUIRED = 123", "from helper import actual_helper", "ENTRY = critical_route"]:
        assert evidence in context
    assert "x" * 1000 not in context and "省略" in context
    assert context.count("def critical_route(") == 1 and "route.py | 行" in context
    with test_database["session_factory"]() as db:
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module", CodeChunk.content.contains("PADDING =")))
        assert module.content == "\n".join(source.splitlines())


def test_definition_time_dependencies_and_import_alias_bindings_reach_provider(client, auth_header, monkeypatch):
    source = ("PADDING = " + repr("x" * 11700) + "\n"
              "from helper import decorate as deco\nimport helper as alias\nimport helper.submodule\n"
              "from helper import actual_helper\nREQUIRED = 123\n"
              "@deco(REQUIRED)\ndef critical_route(PADDING=REQUIRED):\n"
              "    return alias.run(actual_helper(PADDING), helper.submodule.VALUE)\nENTRY = critical_route\n")
    project_id, _ = _setup(client, auth_header, {"route.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["route.py"], prompt="分析 critical_route")
    assert response.status_code == 200, response.text
    context = calls[0].split("【源码上下文】\n", 1)[1]
    for evidence in ["@deco(REQUIRED)", "PADDING=REQUIRED", "REQUIRED = 123", "from helper import decorate as deco",
                     "import helper as alias", "import helper.submodule", "from helper import actual_helper", "ENTRY = critical_route"]:
        assert evidence in context
    assert "x" * 1000 not in context


@pytest.mark.parametrize("diagram_type", DIAGRAM_TYPES)
@pytest.mark.parametrize("binding,prompt_name", [("REQUIRED", "required"), ("required", "REQUIRED"),
                                              ("REQUIRED", "REQUIRED"), ("required", "required")])
def test_explicit_configuration_binding_is_case_insensitive_for_prompt(client, auth_header, monkeypatch, diagram_type, binding, prompt_name):
    source = "PADDING = " + repr("x" * 11800) + f"\n{binding} = 123\n"
    project_id, _ = _setup(client, auth_header, {"config.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["config.py"], f"分析 {prompt_name}")
    assert response.status_code == 200 and response.json()["data"]["status"] == "success", response.text
    context = calls[0].split("【源码上下文】\n", 1)[1]
    assert f"{binding} = 123" in context and "x" * 1000 not in context
    assert len(context.rstrip("\n")) <= 12000 and "config.py | 行 2-2" in context


def test_python_dependencies_remain_case_sensitive(client, auth_header, monkeypatch):
    source = "required = " + repr("x" * 11700) + "\nREQUIRED = 123\ndef target():\n    return REQUIRED\nENTRY = target\n"
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 target")
    assert response.status_code == 200, response.text
    context = calls[0].split("【源码上下文】\n", 1)[1]
    assert "REQUIRED = 123" in context and "ENTRY = target" in context
    assert "x" * 1000 not in context


@pytest.mark.parametrize("code,expected,excluded", [
    ("def f():\n    PADDING = 0\n    return PADDING + REQUIRED", {"REQUIRED"}, {"PADDING"}),
    ("def f(PADDING):\n    return PADDING + REQUIRED", {"REQUIRED"}, {"PADDING"}),
    ("@deco(REQUIRED)\ndef f(REQUIRED=DEFAULT):\n    return REQUIRED", {"deco", "REQUIRED", "DEFAULT"}, set()),
    ("def f():\n    PADDING = 0\n    def inner():\n        return PADDING + REQUIRED\n    return inner()", {"REQUIRED"}, {"PADDING", "inner"}),
    ("class C:\n    def run(self, value):\n        return helper(value) + REQUIRED", {"helper", "REQUIRED"}, {"self", "value"}),
    ("def f():\n    global PADDING\n    PADDING = 1\n    return PADDING", {"PADDING"}, set()),
])
def test_dependency_collection_respects_python_scope(code, expected, excluded):
    names = _names(code)
    assert expected <= names and not (excluded & names)


def test_reverse_dependency_chain_includes_transitive_evidence():
    source = "\n".join(["A0 = 123"] + [f"A{i} = A{i-1}" for i in range(1, 101)] + ["def target():", "    return A100", "ENTRY = target"])
    sf = SimpleNamespace(id=1, relative_path="chain.py")
    symbol = SimpleNamespace(file_id=1, qualified_name=None, name="target", start_line=102, end_line=103, signature=None)
    chunk = SimpleNamespace(file_id=1, chunk_type="module", symbol_name=None, content=source)
    context = build_code_context([sf], [symbol], [chunk], "分析 target", 12000)
    assert "A0 = 123" in context and "A100 = A99" in context and "ENTRY = target" in context
    assert context.count("def target():") == 1 and len(context) <= 12000


@pytest.mark.parametrize("damage", ["missing-symbol", "missing-symbol-chunk", "symbol-range", "chunk-range",
                                    "chunk-content", "truncated-module", "line-count"])
def test_contract_indexing_still_rejects_corrupted_symbol_and_module_evidence(
    client, auth_header, test_database, monkeypatch, damage
):
    source = "@decorate\ndef target():\n    return 1\n\n\n"
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    generated = _analyze(client, auth_header, project_id, selected=["main.py"])
    assert generated.status_code == 200 and generated.json()["data"]["status"] == "success", generated.text
    diagram_id = generated.json()["data"]["diagram_id"]
    with test_database["session_factory"]() as db:
        revision = db.get(Project, project_id).last_index_version
        sf = db.scalar(select(SourceFile).where(SourceFile.project_id == project_id))
        symbol = db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target"))
        chunk = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == symbol.kind))
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
        if damage == "missing-symbol":
            db.delete(symbol)
        elif damage == "missing-symbol-chunk":
            db.delete(chunk)
        elif damage == "symbol-range":
            symbol.start_line += 1
        elif damage == "chunk-range":
            chunk.start_line += 1
        elif damage == "chunk-content":
            chunk.content = chunk.content.replace("return 1", "return 2")
        elif damage == "truncated-module":
            module.content = module.content.rstrip("\n")
        else:
            sf.line_count -= 1
        db.commit()
        before = _index_rows(db, project_id)
    synced = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={"mode": "sync"})
    assert synced.status_code == 200 and synced.json()["data"]["status"] == "failed", synced.text
    task = client.get(f"/api/tasks/{synced.json()['data']['task_id']}", headers=auth_header).json()["data"]
    assert task["status"] == "failed" and "全量解析" in task["message"]
    with test_database["session_factory"]() as db:
        project = db.get(Project, project_id)
        assert project.last_index_version == revision and project.status == "failed"
        assert _index_rows(db, project_id) == before
        assert not db.get(Diagram, diagram_id).is_outdated
    assert len(calls) == 1


def test_outer_symbol_keeps_nested_closure_without_module_padding(client, auth_header, test_database, monkeypatch):
    """parser 仅建立 outer；验证完整 outer 块内闭包，不证明 inner 独立选择。"""
    source = ("PADDING = " + repr("x" * 11700) + "\nREQUIRED = 123\n"
              "def outer():\n    PADDING = 0\n    def inner():\n        return REQUIRED + PADDING\n    return inner()\n")
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, selected=["main.py"], prompt="分析 inner")
    assert response.status_code == 200 and response.json()["data"]["status"] == "success", response.text
    context = calls[0].split("【源码上下文】\n", 1)[1]
    assert "def outer():" in context and "def inner():" in context and "REQUIRED = 123" in context
    assert "x" * 1000 not in context
    with test_database["session_factory"]() as db:
        names = db.scalars(select(Symbol.name).where(Symbol.project_id == project_id)).all()
        assert names == ["outer"]
