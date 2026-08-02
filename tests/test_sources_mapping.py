"""数据源层映射测试（设计 §8 测试 10 / 11、AC-2.4 / AC-8.2 / AC-10）。

覆盖：三类 source type 映射、URL 规范化三例、`domain_tags` 归一化（含实机
存在的 `{}` 形态）、出向字段表、以及 `score_total` / `id` 不得出现的约束。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_hub.schemas import (
    L1Output,
    ScoreDimension,
    ScoreDimensions,
    Tags,
)
from agent_hub.sources.base import ClaimedItem, MappingError, SourceRecord
from agent_hub.sources.db.adapters import map_domain_tags
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.url import normalize_url

_MAPPER = DbL1Mapper()


def _record(**over) -> SourceRecord:
    base = dict(
        raw_item_id=uuid4(),
        source_type="x_twitter",
        source_identity="acct",
        content={"text": "某公司发布新一代推理芯片。", "author_username": "u1", "author_name": "U"},
        source_item_url="https://x.com/u1/status/1",
        source_domain_tags=["AI"],
        published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    base.update(over)
    return SourceRecord(**base)


# --- 测试 11：domain_tags 归一化（据 v1.9，真源为 sources.domain_tags）---
@pytest.mark.parametrize(
    "raw, expected",
    [
        (["AI", "芯片"], ["AI", "芯片"]),
        ({}, []),                       # ← 实机存在：object 而非 array
        ({"a": 1}, []),                 # ← `raw or []` 会漏过它
        (None, []),
        ([], []),
        ("AI", []),                     # 非数组
        (["", "  ", "AI"], ["AI"]),     # 空串被过滤（`['']` 是真值，会穿过 or None）
        (["AI", 3, None], ["AI"]),      # 非字符串元素被过滤
        (["direct_display"], []),       # 流程标记，非领域分类
    ],
    ids=["array", "empty_object", "nonempty_object", "null", "empty_array",
         "string", "blank_items", "non_str_items", "process_label"],
)
def test_map_domain_tags(raw, expected):
    assert map_domain_tags(raw) == expected


def test_empty_object_must_not_crash_mapping():
    """`{}` 必测：实机 5 条冒烟数据全是该形态。

    若按数组直接构造 `L1Input`（其 `domain_tags` 为 `list[str]`）会触发 pydantic
    校验失败 → `MappingError(client_error)` → 不可重试直接 `final_failed`，
    **整批冒烟一次报废**（CN-004 留痕 / CN-006 实机订正）。
    """
    inp = _MAPPER.to_l1_input(_record(source_domain_tags={}))
    assert inp.domain_tags == []


# --- 测试 10：URL 规范化三例（AC-2.4）---
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://x.com/a/status/1", "https://x.com/a/status/1"),
        ("x.com/a/status/1", "https://x.com/a/status/1"),   # C-13：rss/jin10 不保证前缀
        (None, None),
        ("", None),
        ("/relative/path", None),                            # 不猜——猜错比不抓更糟
        ("ftp://h/f", None),
    ],
    ids=["with_prefix", "no_prefix", "null", "empty", "relative", "other_scheme"],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_url_backfilled_into_raw_content():
    """入向映射必须回填 `raw_content["url"]`，否则 link_read 静默失效。"""
    inp = _MAPPER.to_l1_input(_record(source_item_url="x.com/u1/status/1"))
    assert inp.raw_content["url"] == "https://x.com/u1/status/1"


def test_unnormalizable_url_omits_key():
    inp = _MAPPER.to_l1_input(_record(source_item_url="/relative"))
    assert "url" not in inp.raw_content


# --- 测试 10：三类 source type 映射（AC-10.1）---
def test_x_twitter_builds_short_title_from_text():
    """该类无 title 键，需由正文构造短标题供 _build_query / _build_kb_query 使用。"""
    long_text = "长" * 200
    inp = _MAPPER.to_l1_input(_record(content={"text": long_text}))
    assert inp.raw_text == long_text
    assert inp.raw_content["title"] == long_text[:80]


@pytest.mark.parametrize("source_type", ["rss", "jin10_flash"])
def test_title_summary_types(source_type):
    """rss / jin10_flash：仅单测覆盖，无真实数据（AC-10.2 验收分层，不得声称已真实验收）。"""
    inp = _MAPPER.to_l1_input(
        _record(source_type=source_type, content={"title": "标题", "summary": "摘要"})
    )
    assert inp.raw_content["title"] == "标题"
    assert inp.raw_text == "摘要"


def test_rss_missing_author_key_does_not_crash():
    """R-5：`rss.author` 键**可能不存在**（非空串），须用 .get()。"""
    inp = _MAPPER.to_l1_input(_record(source_type="rss", content={"title": "t"}))
    assert inp.raw_text == ""


def test_unknown_source_type_is_client_error():
    with pytest.raises(MappingError) as ei:
        _MAPPER.to_l1_input(_record(source_type="telegram"))
    assert ei.value.kind == "client_error"  # 不可重试：脏数据重试不会变干净


def test_db_mode_prefetch_fields_are_empty():
    """DB 模式无预取方（AC-8.2 已知差异）。"""
    inp = _MAPPER.to_l1_input(_record())
    assert inp.kb_results == [] and inp.link_content is None and inp.search_summary is None


# --- 出向映射：AC-4.6 字段表 ---
def _output(**over) -> L1Output:
    dim = ScoreDimension(score=3, reason="r")
    base = dict(
        title="t", summary="s", translation={"zh": "z"}, context=[], analysis="a",
        score_dimensions=ScoreDimensions(timeliness=dim, impact=dim, confidence=dim, clarity=dim),
        tags=Tags(domain=["AI"], processing=["engine:agent_hub"]),
        needs_context=True,
    )
    base.update(over)
    return L1Output(**base)


def _claimed(record: SourceRecord) -> ClaimedItem:
    return ClaimedItem(
        task_id=uuid4(), record=record, attempt=1, max_attempts=3,
        lock_token="w#1", claimed_at=0.0,
    )


def test_writeback_field_table():
    rec = _record()
    payload = _MAPPER.from_l1_output(_output(), _claimed(rec))
    assert payload.raw_item_id == rec.raw_item_id
    assert payload.language == "zh"                    # C-7 定案
    assert payload.published_at == rec.published_at    # 双保险（AC-4.6）
    assert payload.needs_context is True               # CN-009
    assert set(payload.tags_v2) == {"domain", "entity", "event", "content_type", "processing"}


def test_writeback_has_no_score_total_or_id():
    """`score_total` 归 xiaobao 加权（O-1）、`id` 由 DB 生成——两者不得出现。"""
    payload = _MAPPER.from_l1_output(_output(), _claimed(_record()))
    assert not hasattr(payload, "score_total")
    assert not hasattr(payload, "id")


def test_analysis_none_stays_none():
    """None 时写 SQL NULL 而非空串（Q-3：对方前端为真值判断，NULL 语义更准）。"""
    payload = _MAPPER.from_l1_output(_output(analysis=None), _claimed(_record()))
    assert payload.analysis is None
