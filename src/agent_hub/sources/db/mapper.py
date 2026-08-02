"""DB 数据源的双向映射（`L1Mapper` 的 DB 实现，设计 §3.1、§3.3、§4.4）。

入向：`SourceRecord` → `L1Input`（按 `sources.type` 分发到适配器）。
出向：`L1Output` → `WriteBackPayload`（AC-4.6 字段表）。
"""
from __future__ import annotations

from typing import Any

from agent_hub.schemas import L1Input, L1Output
from agent_hub.sources.base import ClaimedItem, MappingError, SourceRecord, WriteBackPayload
from agent_hub.sources.db.adapters import map_domain_tags
from agent_hub.sources.registry import get_adapter
from agent_hub.sources.url import normalize_url

# 产出内容的语种。news-l1 的输出契约即中文输出，故固定 'zh'（AC-4.6 / C-7）；
# 原文语种当前不落任何列（CN-009 变更 3：对方 raw_items.language 系笔误，该列不存在）。
OUTPUT_LANGUAGE = "zh"


class DbL1Mapper:
    """DB 侧映射。HTTP 侧的对应实现见 `sources/http_source.py`。"""

    def to_l1_input(self, record: Any) -> L1Input:
        if not isinstance(record, SourceRecord):
            raise MappingError("client_error", "expected SourceRecord")

        parts = get_adapter(record.source_type).build(record)

        raw_content: dict = {"title": parts.title, **parts.extra_raw_content}
        # AC-2.4：URL 值得抓时必须回填规范化后的值，否则 _should_link_read 恒为
        # False，link_read 不报错、不降级、静默失效。
        # 但该 AC 隐含前提是「有 URL ⇒ 那是待补充的外部材料」——对 x_twitter 不
        # 成立（其 URL 指向内容自身）。故是否回填由适配层声明，见 url_adds_content。
        url = normalize_url(record.source_item_url) if parts.url_adds_content else None
        if url:
            raw_content["url"] = url

        try:
            return L1Input(
                source_identity=record.source_identity,
                domain_tags=map_domain_tags(record.source_domain_tags),
                raw_content=raw_content,
                raw_text=parts.raw_text,
                # DB 模式无预取方——KB 由「调用方预取」转为「ai 主动检索」，
                # tool_summary.kb_search 因此从 0 变为常态 ≥1（AC-8.2 已知差异）。
                kb_results=[],
                link_content=None,
                search_summary=None,
            )
        except Exception as exc:  # noqa: BLE001 — 统一归为不可重试的入向映射失败
            raise MappingError("client_error", f"invalid L1Input: {type(exc).__name__}") from exc

    def from_l1_output(self, output: L1Output, ctx: Any) -> WriteBackPayload:
        if not isinstance(ctx, ClaimedItem):
            raise MappingError("server_error", "expected ClaimedItem as ctx")
        try:
            return WriteBackPayload(
                raw_item_id=ctx.record.raw_item_id,
                title=output.title,
                summary=output.summary,
                translation=output.translation,
                context=output.context,
                # None 时写 SQL NULL 而非空串——对方前端为真值判断，NULL 语义更准（Q-3）
                analysis=output.analysis,
                score_dimensions=output.score_dimensions.model_dump(mode="json"),
                # 第五类是 processing 不是 sentiment（C-10 定案，与 HTTP v1 一致）
                tags_v2=output.tags.model_dump(mode="json"),
                language=OUTPUT_LANGUAGE,
                # 对方占位行当前写死 NULL 致待解析新闻沉底，ai 写入作双保险（AC-4.6）
                published_at=ctx.record.published_at,
                # CN-009：对方已补列，ai 写入。该信号 ai 本就在产出
                needs_context=output.needs_context,
            )
        except MappingError:
            raise
        except Exception as exc:  # noqa: BLE001 — 出向失败可重试
            raise MappingError("server_error", f"writeback mapping: {type(exc).__name__}") from exc
