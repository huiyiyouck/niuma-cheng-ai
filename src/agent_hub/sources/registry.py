"""源类型适配器注册表（设计 §3.3）。

新增一类 source type = 新增一个适配器 + 一行注册。不在 `DbL1Mapper` 里写
`if source_type == …` 三分支——后者每加一类都要改核心映射类（§7.1 决策 2）。
"""
from __future__ import annotations

from agent_hub.sources.base import MappingError, SourceTypeAdapter
from agent_hub.sources.db.adapters import Jin10FlashAdapter, RssAdapter, XTwitterAdapter

_REGISTRY: dict[str, SourceTypeAdapter] = {}


def register_adapter(adapter: SourceTypeAdapter) -> None:
    _REGISTRY[adapter.source_type] = adapter


def get_adapter(source_type: str) -> SourceTypeAdapter:
    """取适配器；未知 source type 属**入向映射失败**，不可重试（AC-2.5）。"""
    try:
        return _REGISTRY[source_type]
    except KeyError as exc:
        raise MappingError(
            "client_error", f"unsupported source_type: {source_type}"
        ) from exc


def supported_source_types() -> list[str]:
    return sorted(_REGISTRY)


for _adapter in (XTwitterAdapter(), RssAdapter(), Jin10FlashAdapter()):
    register_adapter(_adapter)
