"""First-semester C05/C06/C12–C15: real upload/index/task/diagram evidence."""
from io import BytesIO
import re
from zipfile import ZipFile

import pytest

from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from test_r04_r06_contract import _analyze, _upload


def create(client, headers, files):
    upload = _upload(client, headers, files)
    response = client.post('/api/projects', headers=headers, json={
        'name': 'final-index', 'source_type': 'zip', 'upload_id': upload,
    })
    assert response.status_code == 200, response.text
    return response.json()['data']['project']['id'], upload


def run_task(client, headers, project, operation='parse'):
    response = client.post(f'/api/projects/{project}/{operation}', headers=headers, json={'mode': 'sync'})
    assert response.status_code == 200, response.text
    task = client.get(f"/api/tasks/{response.json()['data']['task_id']}", headers=headers)
    assert task.status_code == 200, task.text
    return task.json()['data']


def inventory_snapshot(db, project):
    return (
        [(x.id, x.relative_path, x.file_hash, x.parse_status) for x in db.query(SourceFile).filter_by(project_id=project).order_by(SourceFile.id)],
        [(x.id, x.file_id, x.qualified_name, x.start_line, x.end_line) for x in db.query(Symbol).filter_by(project_id=project).order_by(Symbol.id)],
        [(x.id, x.file_id, x.content) for x in db.query(CodeChunk).filter_by(project_id=project).order_by(CodeChunk.id)],
    )


def overwrite(test_database, upload, files):
    with test_database['session_factory']() as db:
        path = test_database['storage_path'] / db.get(Upload, upload).object_key
    with ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_first_failure_has_public_diagnostics_and_no_claim_of_retained_index(client, auth_header):
    project, _ = create(client, auth_header, {'healthy.py': 'def ok():\n    return 1\n', 'broken.py': 'def broken(:\n'})
    task = run_task(client, auth_header, project)
    assert task['status'] == 'failed' and task['progress'] == 100
    assert task['result_json']['retained_old_index'] is False
    assert any(d['relative_path'] == 'broken.py' and d['status'] == 'failed' for d in task['result_json']['diagnostics'])
    assert '尚未建立' in task['message'] and '旧索引已保留' not in task['message']


@pytest.mark.parametrize('operation', ['parse', 'sync'])
def test_failed_reparse_retains_index_and_exposes_file_reason(client, auth_header, test_database, operation):
    project, upload = create(client, auth_header, {'main.py': 'def target():\n    return 1\n'})
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        before = inventory_snapshot(db, project)
        revision = db.get(Project, project).last_index_version
    overwrite(test_database, upload, {'main.py': 'def broken(:\n'})
    task = run_task(client, auth_header, project, operation)
    assert task['status'] == 'failed'
    assert task['result_json']['retained_old_index'] is True
    assert any(d['relative_path'] == 'main.py' and d['status'] == 'failed' for d in task['result_json']['diagnostics'])
    with test_database['session_factory']() as db:
        assert inventory_snapshot(db, project) == before
        assert db.get(Project, project).last_index_version == revision


@pytest.mark.parametrize('encoding', ['gbk', 'latin-1', 'utf-8-sig'])
def test_python_declared_encoding_is_indexed(client, auth_header, test_database, encoding):
    text = '中文' if encoding == 'gbk' else 'café'
    content = f'# coding: {encoding}\nMESSAGE = {text!r}\ndef target():\n    return MESSAGE\n'
    project, _ = create(client, auth_header, {'main.py': content.encode(encoding)})
    task = run_task(client, auth_header, project)
    assert task['status'] == 'success' and task['result_json']['python_files'] == 1
    with test_database['session_factory']() as db:
        module = db.query(CodeChunk).filter_by(project_id=project, chunk_type='module').one()
        assert text in module.content


@pytest.mark.parametrize('raw', [b'# coding: made-up-codec\nx=1\n', b'# coding: utf-8\nx="\xff"\n'])
def test_decode_failure_is_not_silently_skipped(client, auth_header, raw):
    project, _ = create(client, auth_header, {'broken.py': raw, 'good.py': 'x=1\n'})
    task = run_task(client, auth_header, project)
    assert task['status'] == 'failed'
    assert any(d['relative_path'] == 'broken.py' and '编码' in d['message'] for d in task['result_json']['diagnostics'])


def test_zero_python_is_not_semantic_parse_success(client, auth_header):
    project, _ = create(client, auth_header, {'README.md': '# document\n'})
    task = run_task(client, auth_header, project)
    assert task['status'] == 'failed'
    assert 'Python' in task['message']


def test_unchanged_full_parse_keeps_revision_ids_and_diagram(client, auth_header, test_database):
    project, _ = create(client, auth_header, {'main.py': 'def target():\n    return 1\n', 'notes.md': 'notes\n'})
    assert run_task(client, auth_header, project)['status'] == 'success'
    generated = _analyze(client, auth_header, project)
    assert generated.status_code == 200, generated.text
    diagram = generated.json()['data']['diagram_id']
    with test_database['session_factory']() as db:
        before = inventory_snapshot(db, project)
        revision = db.get(Project, project).last_index_version
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        assert db.get(Project, project).last_index_version == revision
        assert inventory_snapshot(db, project) == before
    saved = client.get(f'/api/diagrams/{diagram}', headers=auth_header).json()['data']
    assert saved['is_outdated'] is False
    assert run_task(client, auth_header, project, 'sync')['status'] == 'success'


def test_changed_sync_and_full_parse_use_same_content_revision_and_non_python_status(client, auth_header, test_database):
    project, upload = create(client, auth_header, {'main.py': 'x=1\n'})
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        old = db.get(Project, project).last_index_version
    overwrite(test_database, upload, {'main.py': 'x=2\n', 'README.md': 'new\n'})
    assert run_task(client, auth_header, project, 'sync')['status'] == 'success'
    with test_database['session_factory']() as db:
        revision = db.get(Project, project).last_index_version
        assert revision != old
        assert db.query(SourceFile).filter_by(project_id=project, relative_path='README.md').one().parse_status == 'skipped'
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        assert db.get(Project, project).last_index_version == revision


@pytest.mark.parametrize('files,source,target,symbol', [
    ({'pkg/main.py': 'from .sub import helper\n', 'pkg/sub/__init__.py': '', 'pkg/sub/helper.py': 'x=1\n'}, 'pkg/main.py', 'pkg/sub/helper.py', None),
    ({'pkg/main.py': 'from .sub import helper\n', 'pkg/sub/helper.py': 'x=1\n'}, 'pkg/main.py', 'pkg/sub/helper.py', None),
    ({'main.py': 'from pkg import helper\n', 'pkg/__init__.py': 'def helper():\n    pass\n', 'pkg/helper.py': 'x=1\n'}, 'main.py', 'pkg/__init__.py', 'helper'),
    ({'main.py': 'from pkg import helper\n', 'pkg/__init__.py': 'helper=1\n', 'pkg/helper.py': 'x=1\n'}, 'main.py', 'pkg/__init__.py', None),
    ({'main.py': 'from pkg import helper\n', 'pkg/__init__.py': 'from external import helper\n', 'pkg/helper.py': 'x=1\n'}, 'main.py', 'pkg/__init__.py', None),
    ({'main.py': 'from pkg import helper\n', 'pkg/__init__.py': 'def __getattr__(name):\n    return 1\n', 'pkg/helper.py': 'x=1\n'}, 'main.py', None, None),
    ({'main.py': 'import pkg.consumer\n', 'pkg/consumer.py': 'import json\n', 'pkg/json.py': 'x=1\n'}, 'pkg/consumer.py', None, None),
    ({'main.py': 'from helper import greet\n', 'helper.py': 'class C:\n    def greet(self):\n        pass\ndef greet():\n    pass\n'}, 'main.py', 'helper.py', 'greet'),
    ({'main.py': 'from helper import greet\n', 'helper.py': 'class C:\n    def greet(self):\n        pass\n'}, 'main.py', None, None),
    ({'main.py': 'from mod import helper\n', 'mod.py': 'x=1\n', 'mod/helper.py': 'x=1\n'}, 'main.py', None, None),
])
def test_imports_follow_module_scope_and_package_semantics(client, auth_header, test_database, files, source, target, symbol):
    project, _ = create(client, auth_header, files)
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        source_file = db.query(SourceFile).filter_by(project_id=project, relative_path=source).one()
        dependency = db.query(Dependency).filter_by(source_file_id=source_file.id).one()
        target_file = db.get(SourceFile, dependency.target_file_id) if dependency.target_file_id else None
        target_symbol = db.get(Symbol, dependency.target_symbol_id) if dependency.target_symbol_id else None
        assert (target_file.relative_path if target_file else None) == target
        assert (target_symbol.qualified_name if target_symbol else None) == symbol


def test_nested_class_qualified_names_and_direct_method_membership(client, auth_header, test_database):
    code = 'class Outer:\n    class Inner:\n        def run(self):\n            return 1\n    def outer(self):\n        pass\nclass Outer:\n    def second(self):\n        pass\n'
    project, _ = create(client, auth_header, {'main.py': code})
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        names = [s.qualified_name for s in db.query(Symbol).filter_by(project_id=project).order_by(Symbol.start_line)]
        assert names == ['Outer', 'Outer.Inner', 'Outer.Inner.run', 'Outer.outer', 'Outer', 'Outer.second']
    generated = _analyze(client, auth_header, project, 'architecture')
    assert generated.status_code == 200, generated.text
    diagram = client.get(f"/api/diagrams/{generated.json()['data']['diagram_id']}", headers=auth_header).json()['data']['mermaid_code']
    groups = re.findall(r'class [^\n]+\["([^\"]+)"\] \{([^}]+)\}', diagram)
    assert len(groups) == 3, diagram
    assert '+outer()' in groups[0][1] and '+run()' not in groups[0][1] and '+second()' not in groups[0][1]
    assert '+run()' in groups[1][1] and 'Outer.Inner' in groups[1][0]
    assert '+second()' in groups[2][1] and '+outer()' not in groups[2][1]


@pytest.mark.parametrize('source,statement,extra', [
    ('main.py', 'import pkg.sub', {}),
    ('main.py', 'from pkg.sub import helper', {}),
    ('pkg/consumer.py', 'from .sub import helper', {}),
    ('main.py', 'import pkg.middle.sub', {'pkg/middle.py': 'x=1\n', 'pkg/middle/sub.py': 'x=1\n'}),
])
def test_dotted_import_cannot_cross_an_ordinary_module_parent(client, auth_header, test_database, source, statement, extra):
    files = {'pkg.py': 'x=1\n', 'pkg/sub.py': 'def helper():\n    pass\n', source: statement + '\n', **extra}
    if extra:
        files.pop('pkg.py')  # A namespace root still cannot cross pkg/middle.py.
    project, _ = create(client, auth_header, files)
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        source_file = db.query(SourceFile).filter_by(project_id=project, relative_path=source).one()
        dependency = db.query(Dependency).filter_by(source_file_id=source_file.id).one()
        assert dependency.target_file_id is None
        assert dependency.target_symbol_id is None
        assert float(dependency.confidence) == 50


def test_full_upgrade_rebuilds_legacy_import_evidence_even_when_content_matches(client, auth_header, test_database):
    files = {'main.py': 'from helper import greet\n', 'helper.py': 'class C:\n    def greet(self):\n        pass\ndef greet():\n    pass\n'}
    project, upload = create(client, auth_header, files)
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        wrong = db.query(Symbol).filter_by(project_id=project, qualified_name='C.greet').one()
        dependency = db.query(Dependency).filter_by(project_id=project).one()
        dependency.target_symbol_id = wrong.id
        db.get(Project, project).last_index_version = f'upload:{upload}:' + 'a' * 32
        db.commit()
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        dependency = db.query(Dependency).filter_by(project_id=project).one()
        assert db.get(Symbol, dependency.target_symbol_id).qualified_name == 'greet'


def test_legacy_revision_cannot_skip_import_contract_upgrade_with_sync(client, auth_header, test_database):
    project, upload = create(client, auth_header, {'main.py': 'x=1\n'})
    assert run_task(client, auth_header, project)['status'] == 'success'
    with test_database['session_factory']() as db:
        db.get(Project, project).last_index_version = f'upload:{upload}:' + 'a' * 32
        db.commit()
    assert run_task(client, auth_header, project, 'sync')['status'] == 'failed'
    assert _analyze(client, auth_header, project).status_code == 409
