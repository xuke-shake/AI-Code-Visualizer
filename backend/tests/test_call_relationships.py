"""函数级调用关系识别（extract_calls）的契约测试。"""
from test_final_index_contract import create, run_task

from app.models.dependency import Dependency
from app.models.symbol import Symbol


def _call_edges(db, project):
    """返回 [(source_qualified_name, target_qualified_name)]，target 未解析时为 None。"""
    edges = []
    for dep in db.query(Dependency).filter_by(project_id=project, relation_type="calls").all():
        src = db.get(Symbol, dep.source_symbol_id) if dep.source_symbol_id else None
        tgt = db.get(Symbol, dep.target_symbol_id) if dep.target_symbol_id else None
        edges.append((src.qualified_name if src else None, tgt.qualified_name if tgt else None))
    return sorted(edges)


def test_same_file_function_call(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == [("main", "helper")]


def test_cross_file_call_via_from_import(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "from helpers import greet\n\ndef main():\n    return greet()\n",
        "helpers.py": "def greet():\n    return 'hi'\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == [("main", "greet")]


def test_cross_file_call_via_import(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "import helpers\n\ndef main():\n    return helpers.greet()\n",
        "helpers.py": "def greet():\n    return 'hi'\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == [("main", "greet")]


def test_method_call_resolves_within_class(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "class C:\n    def helper(self):\n        return 1\n    def main(self):\n        return self.helper()\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == [("C.main", "C.helper")]


def test_builtin_calls_are_not_recorded(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "def main():\n    print('x')\n    return len([1, 2])\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == []


def test_duplicate_calls_are_deduplicated(client, auth_header, test_database):
    project, _ = create(client, auth_header, {
        "main.py": "def helper():\n    return 1\n\ndef main():\n    return helper() + helper()\n",
    })
    assert run_task(client, auth_header, project)["status"] == "success"
    with test_database["session_factory"]() as db:
        assert _call_edges(db, project) == [("main", "helper")]
