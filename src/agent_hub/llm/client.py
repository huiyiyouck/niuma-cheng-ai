"""OpenAI 兼容 LLM client 抽象与装配点（ADR-0002）。

S1 只建立抽象与依赖注入接口：
- `AIClient` 协议 + `LLMResult` 返回类型；
- `UnconfiguredClient` 占位（无 provider 配置时调用即失败，触发 AC-6 完全失败路径）；
- `get_ai_client` 作为 FastAPI 依赖，测试可通过 `app.dependency_overrides` 注入 fake。

真实的 `ChainedAIClient`（多 provider 顺序 fallback、provider quirk、JSON 修复）由 S2 实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMResult:
    """LLM 单次结构化 JSON 调用的结果。

    字段最小集（设计 Developer 实现提示 1）：
    - provider_name：命中的 provider，用于 tags.processing 与 fallback 日志；
    - parsed：解析后的结构化 JSON（news-l1 输出约定，见 llm/prompts）；
    - raw：原始响应文本（脱敏日志用，可空）；
    - degradations：本次调用产生的降级标记（如 provider quirk 调整）。
    """

    provider_name: str
    parsed: dict
    raw: str | None = None
    degradations: list[str] = field(default_factory=list)


class AIClient(Protocol):
    def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult: ...


class ProvidersNotConfiguredError(RuntimeError):
    """未配置任何 LLM provider 时抛出，由 llm_process 节点捕获降级为完全失败。"""


class UnconfiguredClient:
    """S1 占位 client：无 provider 配置时使用，调用即失败。"""

    def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult:
        raise ProvidersNotConfiguredError("no LLM provider configured")


def build_ai_client() -> AIClient:
    """从配置装配 client。S2 将在此返回真实 ChainedAIClient。"""
    return UnconfiguredClient()


def get_ai_client() -> AIClient:
    """FastAPI 依赖：注入 LLM client。测试通过 dependency_overrides 替换。"""
    return build_ai_client()
