"""环境变量配置。

AI 推理走外部 API（OpenAI 兼容），本服务为 IO-bound 协调者（见提案 §12.3）。
多 provider fallback 配置见 ADR-0002：优先 `LLM_PROVIDERS_JSON`，缺失时回退到
单组 `OPENAI_*` 兼容路径。key 通过 `api_key_env` 指向环境变量，不写入 JSON。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Config:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8100"))

    # LLM（OpenAI 兼容外部 API）
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    l1_llm_model: str = os.getenv("L1_LLM_MODEL", "gpt-4o-mini")
    llm_timeout_ms: int = int(os.getenv("LLM_TIMEOUT_MS", "60000"))

    # 外部搜索
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))


config = Config()


class ProviderConfigError(ValueError):
    """LLM provider 配置非法（JSON 解析失败 / 缺必填字段）。"""


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str
    timeout_ms: Optional[int] = None
    supports_response_format: Optional[bool] = None
    temperature: Optional[float] = 0.2


_REQUIRED = ("name", "base_url", "api_key_env", "model")


def load_providers() -> list[ProviderConfig]:
    """解析 provider 列表。运行时读取环境变量，便于测试与热配置。

    优先级：`LLM_PROVIDERS_JSON` > 单组 `OPENAI_*` 兼容 > 空列表。
    """
    raw = os.getenv("LLM_PROVIDERS_JSON")
    if raw:
        return _parse_providers_json(raw)

    api_key_val = os.getenv("OPENAI_API_KEY", "")
    if api_key_val:
        return [
            ProviderConfig(
                name="default",
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key_env="OPENAI_API_KEY",
                model=os.getenv("L1_LLM_MODEL", "gpt-4o-mini"),
                timeout_ms=int(os.getenv("LLM_TIMEOUT_MS", "60000")),
            )
        ]
    return []


def _parse_providers_json(raw: str) -> list[ProviderConfig]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderConfigError(f"LLM_PROVIDERS_JSON 不是合法 JSON: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ProviderConfigError("LLM_PROVIDERS_JSON 必须是非空数组")

    providers: list[ProviderConfig] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ProviderConfigError(f"provider[{i}] 必须是对象")
        missing = [k for k in _REQUIRED if not item.get(k)]
        if missing:
            raise ProviderConfigError(f"provider[{i}] 缺少字段: {', '.join(missing)}")
        providers.append(
            ProviderConfig(
                name=item["name"],
                base_url=item["base_url"],
                api_key_env=item["api_key_env"],
                model=item["model"],
                timeout_ms=item.get("timeout_ms"),
                supports_response_format=item.get("supports_response_format"),
                temperature=item.get("temperature", 0.2),
            )
        )
    return providers
