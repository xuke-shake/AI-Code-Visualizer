from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

from app.agents.llm_provider import LLMProvider
from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings


def test_llm_settings_normalise_modes_and_bound_context():
    assert Settings(llm_enabled=True).llm_enabled == "model"
    assert Settings(llm_enabled=False).llm_enabled == "off"
    assert Settings(llm_enabled="rule").llm_model_enabled is False
    assert Settings(llm_enabled="auto", llm_api_key="key").llm_model_enabled is True
    assert Settings(llm_enabled="model").llm_model_enabled is False

    with pytest.raises(ValidationError):
        Settings(llm_max_context_chars=999)
    with pytest.raises(ValidationError):
        Settings(llm_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(llm_enabled="unexpected")


def test_non_development_rejects_placeholder_secret_and_disables_debug():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production", debug=True, secret_key="change-me-in-production")

    settings = Settings(app_env="production", debug=True, secret_key="x" * 48)
    assert settings.debug is False


def test_provider_uses_settings_for_client_and_request_options(monkeypatch):
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["request"] = kwargs
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="flowchart TD"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    settings = Settings(
        llm_enabled="model",
        llm_api_key="test-api-key",
        llm_base_url="https://example.test/",
        llm_model="test-model",
        llm_timeout_seconds=17,
        llm_max_output_tokens=321,
    )
    provider = LLMProvider(settings=settings)
    assert calls["client"] == {"api_key": "test-api-key", "base_url": "https://example.test", "timeout": 17, "max_retries": 0}

    assert provider.chat("system", "user").content == "flowchart TD"
    assert calls["request"]["model"] == "test-model"
    assert calls["request"]["max_tokens"] == 321
    assert calls["request"]["timeout"] == 17


def test_orchestrator_reads_settings_without_debug_output(capsys):
    settings = Settings(llm_enabled="rule", llm_max_context_chars=2345)
    orchestrator = AgentOrchestrator(settings=settings)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert orchestrator.llm_enabled is False
    assert orchestrator.max_context_chars == 2345
