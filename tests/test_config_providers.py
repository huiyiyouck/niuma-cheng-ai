"""LLM provider 配置解析测试（S2，AC-7 / ADR-0002）。"""
import pytest

from agent_hub.config import ProviderConfigError, load_providers

_ENV_KEYS = [
    "LLM_PROVIDERS_JSON",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "L1_LLM_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_load_from_providers_json(monkeypatch):
    monkeypatch.setenv(
        "LLM_PROVIDERS_JSON",
        '[{"name":"primary","base_url":"https://a/v1","api_key_env":"OPENAI_API_KEY","model":"m-a"},'
        '{"name":"backup","base_url":"https://b/v1","api_key_env":"BACKUP_KEY","model":"m-b"}]',
    )
    providers = load_providers()
    assert [p.name for p in providers] == ["primary", "backup"]
    assert providers[0].base_url == "https://a/v1"
    assert providers[0].api_key_env == "OPENAI_API_KEY"
    assert providers[1].model == "m-b"


def test_single_provider_compat(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat/v1")
    monkeypatch.setenv("L1_LLM_MODEL", "gpt-x")
    providers = load_providers()
    assert len(providers) == 1
    assert providers[0].base_url == "https://compat/v1"
    assert providers[0].api_key_env == "OPENAI_API_KEY"
    assert providers[0].model == "gpt-x"


def test_empty_when_nothing_configured():
    assert load_providers() == []


def test_invalid_json_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS_JSON", "{not json")
    with pytest.raises(ProviderConfigError):
        load_providers()


def test_missing_required_field_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS_JSON", '[{"name":"x","model":"m"}]')
    with pytest.raises(ProviderConfigError):
        load_providers()
