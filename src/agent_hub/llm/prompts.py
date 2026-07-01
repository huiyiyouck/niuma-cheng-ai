"""news-l1 prompt 模板。

S1 提供最小可用的 system/user 消息构造，保证端到端可跑通。
完整 prompt（五类标签要求、四维 0-5 评分约定、翻译目标语言 zh、不编造 URL、
只输出 JSON 等，设计 §4.6 与 PM 非阻塞建议）由 S2 详化。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent_hub.schemas import L1Input

if TYPE_CHECKING:
    from agent_hub.graphs.news_l1 import ContextItem


_SYSTEM = (
    "你是新闻 L1 处理器。基于给定证据，输出严格 JSON，包含："
    "title、summary、translation.zh、analysis、needs_context、"
    "scores（timeliness/impact/confidence/clarity 各含 0-5 整数 score 与非空 reason）、"
    "tags（domain/entity/event/content_type 五类，processing 由系统追加）、context。"
    "不要编造来源 URL，只使用给定证据。只输出 JSON。"
)


def build_news_l1_messages(inp: L1Input, context_items: list["ContextItem"]) -> list[dict]:
    parts = [f"来源标识：{inp.source_identity}"]
    if inp.domain_tags:
        parts.append(f"领域标签：{', '.join(inp.domain_tags)}")
    if inp.raw_text.strip():
        parts.append(f"原文：\n{inp.raw_text}")
    for item in context_items:
        if item.source_type == "raw":
            continue
        label = {"kb": "库内检索", "link": "链接正文", "web": "搜索摘要"}.get(
            item.source_type, item.source_type
        )
        parts.append(f"[{label}]{item.title or ''}\n{item.content}")

    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
