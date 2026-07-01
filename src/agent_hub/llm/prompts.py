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
    "你是新闻 L1 处理器。基于给定证据处理单条新闻，只输出一个严格的 JSON 对象，"
    "不要输出 JSON 以外的任何文字或 markdown 代码块。字段要求：\n"
    "- title：新闻标题（中文，若原文非中文则译为中文）。\n"
    "- summary：中文摘要，2-4 句，覆盖核心事实，不空。\n"
    "- translation.zh：原文非中文时给出中文全文译文；原文已是中文时可为空字符串。\n"
    "- analysis：可选的简要分析。\n"
    "- scores：timeliness/impact/confidence/clarity 四维，各含 0-5 的整数 score 与非空中文 reason。\n"
    "- tags：domain/entity/event/content_type 四类标签数组（processing 类由系统追加，勿输出）。\n"
    "- context：引用来源数组，每项含 url/title；只允许引用给定证据中真实出现的 URL，严禁编造。\n"
    "- needs_context：证据不足以可靠处理时为 true，否则 false。"
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
