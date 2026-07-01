"""ChainedAIClient fallback 矩阵与 JSON 修复测试（S2，AC-7 / ADR-0002）。

用注入的 fake caller 覆盖设计 §3 fallback 判定矩阵；真实 httpx 调用
(`_http_call_provider`) 的连通性由部署冒烟验证，不在单测覆盖。
"""
import pytest

from agent_hub.config import ProviderConfig
from agent_hub.llm.client import (
    AllProvidersFailedError,
    ChainedAIClient,
    ProviderCallError,
    ProviderQuirkError,
)
from agent_hub.llm.json import JSONParseError, parse_json_lenient

_GOOD = '{"title":"t","summary":"s","scores":{}}'


def _providers(*names):
    return [
        ProviderConfig(name=n, base_url=f"https://{n}/v1", api_key_env="K", model="m")
        for n in names
    ]


def _caller(script):
    """script: dict[provider_name] -> str(raw) | Exception 实例 | list(顺序返回/抛)。"""
    calls = {}

    def caller(provider, messages, timeout_ms):
        calls.setdefault(provider.name, 0)
        idx = calls[provider.name]
        calls[provider.name] += 1
        item = script[provider.name]
        if isinstance(item, list):
            item = item[idx]
        if isinstance(item, Exception):
            raise item
        return item

    caller.calls = calls
    return caller


# --- JSON 修复 ---
def test_parse_plain_json():
    assert parse_json_lenient(_GOOD)["title"] == "t"


def test_parse_fenced_json():
    text = "```json\n" + _GOOD + "\n```"
    assert parse_json_lenient(text)["summary"] == "s"


def test_parse_json_with_surrounding_text():
    text = "这是结果：" + _GOOD + " 完毕"
    assert parse_json_lenient(text)["title"] == "t"


def test_parse_unrecoverable_raises():
    with pytest.raises(JSONParseError):
        parse_json_lenient("完全不是 JSON")


# --- fallback 矩阵 ---
def test_first_provider_success():
    client = ChainedAIClient(_providers("p1", "p2"), caller=_caller({"p1": _GOOD}))
    result = client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p1"
    assert result.parsed["title"] == "t"


@pytest.mark.parametrize("kind", ["rate_limited", "timeout", "server_error", "auth", "empty"])
def test_fallback_to_next_provider(kind):
    if kind == "empty":
        p1 = ""  # 空响应
    else:
        p1 = ProviderCallError(kind=kind)
    client = ChainedAIClient(
        _providers("p1", "p2"), caller=_caller({"p1": p1, "p2": _GOOD})
    )
    result = client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"


def test_parse_error_falls_back():
    client = ChainedAIClient(
        _providers("p1", "p2"),
        caller=_caller({"p1": "彻底不是 json", "p2": _GOOD}),
    )
    result = client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"


def test_all_providers_fail_raises():
    client = ChainedAIClient(
        _providers("p1", "p2"),
        caller=_caller(
            {"p1": ProviderCallError(kind="server_error"), "p2": ProviderCallError(kind="timeout")}
        ),
    )
    with pytest.raises(AllProvidersFailedError):
        client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)


def test_quirk_adjusted_retries_same_provider():
    # p1 首次抛 quirk（不支持 response_format），调整后同 provider 重试成功
    caller = _caller({"p1": [ProviderQuirkError(param="response_format"), _GOOD]})
    client = ChainedAIClient(_providers("p1", "p2"), caller=caller)
    result = client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p1"
    assert caller.calls["p1"] == 2
    assert any("quirk" in d for d in result.degradations)


def test_quirk_retry_fail_falls_back():
    # p1 quirk 调整后仍失败 → 换 p2
    caller = _caller(
        {"p1": [ProviderQuirkError(param="temperature"), ProviderCallError(kind="server_error")], "p2": _GOOD}
    )
    client = ChainedAIClient(_providers("p1", "p2"), caller=caller)
    result = client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"
