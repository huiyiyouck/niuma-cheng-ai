"""ChainedAIClient fallback 矩阵与 JSON 修复测试（S2，AC-7 / ADR-0002）。

用注入的 fake caller 覆盖设计 §3 fallback 判定矩阵；真实 httpx 调用
(`_http_call_provider`) 的连通性由部署冒烟验证，不在单测覆盖。
"""
import asyncio

import httpx
import pytest

from agent_hub.config import ProviderConfig
from agent_hub.llm.client import (
    AllProvidersFailedError,
    ChainedAIClient,
    _http_call_provider,
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

    async def caller(provider, messages, timeout_ms):
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
async def test_parse_plain_json():
    assert parse_json_lenient(_GOOD)["title"] == "t"


async def test_parse_fenced_json():
    text = "```json\n" + _GOOD + "\n```"
    assert parse_json_lenient(text)["summary"] == "s"


async def test_parse_json_with_surrounding_text():
    text = "这是结果：" + _GOOD + " 完毕"
    assert parse_json_lenient(text)["title"] == "t"


async def test_parse_unrecoverable_raises():
    with pytest.raises(JSONParseError):
        parse_json_lenient("完全不是 JSON")


# --- fallback 矩阵 ---
async def test_first_provider_success():
    client = ChainedAIClient(_providers("p1", "p2"), caller=_caller({"p1": _GOOD}))
    result = await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p1"
    assert result.parsed["title"] == "t"


@pytest.mark.parametrize("kind", ["rate_limited", "timeout", "server_error", "auth", "empty"])
async def test_fallback_to_next_provider(kind):
    if kind == "empty":
        p1 = ""  # 空响应
    else:
        p1 = ProviderCallError(kind=kind)
    client = ChainedAIClient(
        _providers("p1", "p2"), caller=_caller({"p1": p1, "p2": _GOOD})
    )
    result = await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"


async def test_parse_error_falls_back():
    client = ChainedAIClient(
        _providers("p1", "p2"),
        caller=_caller({"p1": "彻底不是 json", "p2": _GOOD}),
    )
    result = await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"


async def test_all_providers_fail_raises():
    client = ChainedAIClient(
        _providers("p1", "p2"),
        caller=_caller(
            {"p1": ProviderCallError(kind="server_error"), "p2": ProviderCallError(kind="timeout")}
        ),
    )
    with pytest.raises(AllProvidersFailedError):
        await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)


async def test_quirk_adjusted_retries_same_provider():
    # p1 首次抛 quirk（不支持 response_format），调整后同 provider 重试成功
    caller = _caller({"p1": [ProviderQuirkError(param="response_format"), _GOOD]})
    client = ChainedAIClient(_providers("p1", "p2"), caller=caller)
    result = await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p1"
    assert caller.calls["p1"] == 2
    assert any("quirk" in d for d in result.degradations)


async def test_quirk_retry_fail_falls_back():
    # p1 quirk 调整后仍失败 → 换 p2
    caller = _caller(
        {"p1": [ProviderQuirkError(param="temperature"), ProviderCallError(kind="server_error")], "p2": _GOOD}
    )
    client = ChainedAIClient(_providers("p1", "p2"), caller=caller)
    result = await client.complete_json([{"role": "user", "content": "x"}], timeout_ms=5000)
    assert result.provider_name == "p2"


# --- async 改造新增：两种超时异常都须被翻译为 timeout kind（设计 §6.2/§7.2）---
@pytest.mark.parametrize(
    "raised",
    [httpx.TimeoutException("timed out"), asyncio.TimeoutError()],
    ids=["httpx.TimeoutException", "asyncio.TimeoutError"],
)
async def test_http_call_translates_both_timeout_types(monkeypatch, raised):
    """`_http_call_provider` 须同时认这两种异常为 timeout kind。

    同步实现下只会抛 `httpx.TimeoutException`；改 async 后，调用若被
    `asyncio.wait_for` 之类包裹则抛 `asyncio.TimeoutError`。只认前者会让
    异常穿透 `_attempt_provider`，**fallback 链静默失效、整条变完全失败**
    ——这是本次改造中最容易静默变化的一处（设计 §6.2 样本 ④ 注）。
    """

    async def _raise(*args, **kwargs):
        raise raised

    monkeypatch.setattr(httpx.AsyncClient, "post", _raise)
    provider = _providers("p1")[0]

    with pytest.raises(ProviderCallError) as ei:
        await _http_call_provider(provider, [{"role": "user", "content": "x"}], 1000)
    assert ei.value.kind == "timeout"
