"""C07–C11: public validation, scheduling and local SDK usage/lifecycle."""
import asyncio
from io import BytesIO
from time import monotonic, sleep
import sys
from types import SimpleNamespace

from fastapi import UploadFile
import httpx
import pytest
from sqlalchemy import event

from app.agents.llm_provider import LLMProvider
from app.core.config import Settings
from app.models.agent_run import AgentRun
from app.services.admin_service import AdminService
from app.tools import zip_safety
from test_r04_r06_contract import _setup, _analyze, _zip


@pytest.mark.parametrize('config', [
    {'enable_symbol_search': 'false'}, {'enable_symbol_search': False},
    {'max_tokens': '4000'}, {'retrieval_top_k': True},
    {'future_option': True}, {'retrieval_top_k': 12},
])
def test_config_bypass_is_rejected(client, auth_header, config):
    project, _ = _setup(client, auth_header)
    response = client.patch(f'/api/projects/{project}', headers=auth_header, json={'config_json': config})
    assert response.status_code in (400, 422), response.text


def test_config_replacement_is_complete_and_server_status_is_not_public(client, auth_header):
    project, _ = _setup(client, auth_header)
    status = client.patch(f'/api/projects/{project}', headers=auth_header, json={'status': 'ready-from-client'})
    assert status.status_code == 422
    response = client.patch(f'/api/projects/{project}', headers=auth_header, json={'config_json': {'enable_symbol_search': True}})
    assert response.status_code == 200, response.text
    assert response.json()['data']['config_json'] == {
        'chunking_strategy': 'function', 'retrieval_top_k': 8,
        'similarity_threshold': 0.35, 'enable_symbol_search': True,
        'model_name': None, 'max_tokens': 4000,
    }


def test_forged_mapping_cannot_be_restored_after_edit(client, auth_header):
    project, _ = _setup(client, auth_header)
    analysis = _analyze(client, auth_header, project)
    assert analysis.status_code == 200, analysis.text
    diagram = analysis.json()['data']['diagram_id']
    edited = client.patch(f'/api/diagrams/{diagram}', headers=auth_header, json={'mermaid_code': 'flowchart TD\nA[edited] --> B[done]'})
    assert edited.status_code == 200 and edited.json()['data']['node_mapping_json'] is None
    forged = client.patch(f'/api/diagrams/{diagram}', headers=auth_header, json={'node_mapping_json': {'A': {'file_path': 'main.py', 'start_line': 999999}}})
    assert forged.status_code == 422, forged.text
    saved = client.get(f'/api/diagrams/{diagram}', headers=auth_header).json()['data']
    assert saved['node_mapping_json'] is None and saved['generation_mode'] == 'edited'


async def responsive_while(work):
    gaps = []
    previous = monotonic()
    running = asyncio.create_task(work)
    while not running.done():
        await asyncio.sleep(0.01)
        current = monotonic()
        gaps.append(current - previous)
        previous = current
    result = await running
    assert max(gaps, default=0) < 0.12, gaps
    return result


def test_zip_validation_does_not_block_event_loop(test_database, monkeypatch):
    original = zip_safety.validate_zip_file
    def slow(path):
        sleep(0.2)
        return original(path)
    monkeypatch.setattr(zip_safety, 'validate_zip_file', slow)
    upload = UploadFile(filename='code.zip', file=BytesIO(_zip({'main.py': 'x=1\n'})))
    result = asyncio.run(responsive_while(zip_safety.save_upload_zip(upload, 1)))
    assert result['accepted_source_files'] == 1


def test_upload_orm_wait_does_not_block_event_loop(client, auth_header, test_database):
    def slow_insert(conn, cursor, statement, parameters, context, many):
        if statement.lower().lstrip().startswith('insert into uploads'):
            sleep(0.2)
    event.listen(test_database['engine'], 'before_cursor_execute', slow_insert)
    async def post():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as api:
            return await api.post('/api/uploads', headers=auth_header, files={'file': ('code.zip', _zip({'main.py': 'x=1\n'}), 'application/zip')})
    try:
        response = asyncio.run(responsive_while(post()))
        assert response.status_code == 200, response.text
    finally:
        event.remove(test_database['engine'], 'before_cursor_execute', slow_insert)


def sdk(monkeypatch, usage, content='flowchart TD\nA-->B', error=False):
    state = {'closed': 0, 'requests': 0}
    class OpenAI:
        def __init__(self, **kwargs):
            state['options'] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            state['requests'] += 1
            if error:
                raise RuntimeError('local simulated timeout')
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage)
        def close(self):
            state['closed'] += 1
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=OpenAI))
    return state


def test_sdk_retry_policy_and_typed_usage(monkeypatch):
    state = sdk(monkeypatch, SimpleNamespace(prompt_tokens=123, completion_tokens=17))
    provider = LLMProvider(settings=Settings(llm_api_key='local-only', llm_timeout_seconds=17))
    result = provider.chat('system', 'user')
    assert state['options']['max_retries'] == 0
    assert result.content == 'flowchart TD\nA-->B'
    assert (result.prompt_tokens, result.completion_tokens) == (123, 17)
    provider.close()
    assert state['closed'] == 1


@pytest.mark.parametrize('mode', ['success', 'invalid', 'missing', 'error'])
def test_model_usage_and_close_reach_real_api_and_admin(client, auth_header, test_database, monkeypatch, mode):
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'llm_enabled', 'model')
    monkeypatch.setattr(settings, 'llm_api_key', 'local-only')
    usage = None if mode in ('missing', 'error') else SimpleNamespace(prompt_tokens=123, completion_tokens=17)
    state = sdk(monkeypatch, usage, content='invalid' if mode == 'invalid' else 'flowchart TD\nA-->B', error=mode == 'error')
    project, _ = _setup(client, auth_header)
    response = _analyze(client, auth_header, project)
    assert response.status_code == 200, response.text
    assert state['requests'] == 1 and state['closed'] == 1
    with test_database['session_factory']() as db:
        row = db.query(AgentRun).filter_by(task_id=response.json()['data']['task_id'], agent_name='DiagramAgent').one()
        metrics = AdminService(db).metrics()
        if mode in ('success', 'invalid'):
            assert row.usage_collected is True
            assert (row.prompt_tokens, row.completion_tokens) == (123, 17)
            assert metrics['token_usage'] == 140 and metrics['usage_collected_calls'] == 1
        else:
            assert row.usage_collected is False
            assert metrics['token_usage'] is None and metrics['usage_unknown_calls'] == 1
