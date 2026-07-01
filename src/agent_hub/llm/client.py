"""OpenAI 兼容 LLM client（ADR-0002）。

- `AIClient` 协议 + `LLMResult` 返回类型；
- `ChainedAIClient`：多 provider 顺序 fallback + provider quirk 调整 + JSON 修复，
  fallback 判定矩阵见设计 §3；
- `UnconfiguredClient`：无 provider 配置时占位，调用即失败（触发 AC-6 完全失败）；
- `get_ai_client`：FastAPI 依赖，测试可通过 `app.dependency_overrides` 注入 fake。

真实 provider 调用走 `_http_call_provider`；单测通过注入 fake caller 覆盖编排逻辑，
真实连通性由部署冒烟验证。
"""
from __future__ import annotations

import dataclasses
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import httpx

from agent_hub.config import ProviderConfig, load_providers
from agent_hub.llm.json import JSONParseError, parse_json_lenient


@dataclass
class LLMResult:
    provider_name: str
    parsed: dict
    raw: str | None = None
    degradations: list[str] = field(default_factory=list)


class AIClient(Protocol):
    def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult: ...


class ProviderCallError(Exception):
    """单次 provider 调用失败，应 fallback 到下一个 provider。

    kind ∈ {rate_limited, timeout, server_error, auth, empty}。
    """

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


class ProviderQuirkError(Exception):
    """provider 不支持某参数（response_format / temperature），需调整参数同 provider 重试。"""

    def __init__(self, param: str):
        super().__init__(param)
        self.param = param


class AllProvidersFailedError(RuntimeError):
    """所有 provider 均失败，无可用输出。"""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{name}:{tag}" for name, tag in errors) or "no providers")


class ProvidersNotConfiguredError(RuntimeError):
    """未配置任何 LLM provider。"""


ProviderCaller = Callable[[ProviderConfig, list[dict], int], str]

_KIND_TAG = {
    "rate_limited": "provider_rate_limited",
    "timeout": "provider_timeout",
    "server_error": "provider_5xx",
    "auth": "provider_auth_or_forbidden",
    "empty": "provider_empty_response",
}


class UnconfiguredClient:
    def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult:
        raise ProvidersNotConfiguredError("no LLM provider configured")


class ChainedAIClient:
    """按 provider 顺序尝试，失败自动 fallback；总耗时受 timeout budget 约束。"""

    def __init__(
        self,
        providers: list[ProviderConfig],
        caller: ProviderCaller | None = None,
        budget_ms: int | None = None,
    ):
        self._providers = providers
        self._call = caller or _http_call_provider
        self._budget_ms = budget_ms

    def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult:
        budget = timeout_ms if self._budget_ms is None else min(self._budget_ms, timeout_ms)
        start = time.monotonic()
        errors: list[tuple[str, str]] = []

        for provider in self._providers:
            elapsed = int((time.monotonic() - start) * 1000)
            remaining = budget - elapsed
            if remaining <= 0:
                errors.append((provider.name, "budget_exhausted"))
                break
            call_timeout = min(provider.timeout_ms or remaining, remaining)
            result = self._attempt_provider(provider, messages, call_timeout, errors)
            if result is not None:
                return result

        raise AllProvidersFailedError(errors)

    def _attempt_provider(
        self,
        provider: ProviderConfig,
        messages: list[dict],
        timeout_ms: int,
        errors: list[tuple[str, str]],
    ) -> LLMResult | None:
        degradations: list[str] = []
        active = provider
        # 至多 2 次：原始调用 + provider quirk 参数调整后重试
        for attempt in range(2):
            try:
                raw = self._call(active, messages, timeout_ms)
            except ProviderQuirkError as quirk:
                if attempt == 0:
                    active = _disable_quirk(active, quirk.param)
                    degradations.append(f"provider_quirk_adjusted:{provider.name}:{quirk.param}")
                    continue
                errors.append((provider.name, "provider_quirk_retry_failed"))
                return None
            except ProviderCallError as err:
                errors.append((provider.name, _KIND_TAG.get(err.kind, err.kind)))
                return None

            if not raw or not raw.strip():
                errors.append((provider.name, "provider_empty_response"))
                return None
            try:
                parsed = parse_json_lenient(raw)
            except JSONParseError:
                errors.append((provider.name, "provider_parse_error"))
                return None
            return LLMResult(
                provider_name=provider.name,
                parsed=parsed,
                raw=raw,
                degradations=degradations,
            )
        return None


def _disable_quirk(provider: ProviderConfig, param: str) -> ProviderConfig:
    if param == "response_format":
        return dataclasses.replace(provider, supports_response_format=False)
    if param == "temperature":
        return dataclasses.replace(provider, temperature=None)
    return provider


def _http_call_provider(provider: ProviderConfig, messages: list[dict], timeout_ms: int) -> str:
    """真实 OpenAI 兼容 chat completions 调用。错误翻译为 fallback 异常。"""
    api_key = os.getenv(provider.api_key_env, "")
    payload: dict = {"model": provider.model, "messages": messages}
    if provider.temperature is not None:
        payload["temperature"] = provider.temperature
    if provider.supports_response_format is not False:
        payload["response_format"] = {"type": "json_object"}

    url = provider.base_url.rstrip("/") + "/chat/completions"
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_ms / 1000,
        )
    except httpx.TimeoutException as exc:
        raise ProviderCallError(kind="timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderCallError(kind="timeout", message="network error") from exc

    status = resp.status_code
    if status == 400:
        body = resp.text.lower()
        if "response_format" in body:
            raise ProviderQuirkError(param="response_format")
        if "temperature" in body:
            raise ProviderQuirkError(param="temperature")
        raise ProviderCallError(kind="server_error")
    if status in (401, 403):
        raise ProviderCallError(kind="auth")
    if status == 429:
        raise ProviderCallError(kind="rate_limited")
    if status >= 500:
        raise ProviderCallError(kind="server_error")
    if status >= 400:
        raise ProviderCallError(kind="server_error")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderCallError(kind="empty") from exc
    return content or ""


def build_ai_client() -> AIClient:
    """从配置装配 client：有 provider → ChainedAIClient；否则占位 UnconfiguredClient。"""
    providers = load_providers()
    if not providers:
        return UnconfiguredClient()
    return ChainedAIClient(providers)


def get_ai_client() -> AIClient:
    """FastAPI 依赖：注入 LLM client。测试通过 dependency_overrides 替换。"""
    return build_ai_client()
