"""三类 source type 的 `content` → `L1Input` 映射（设计 §3.3，据 R-5 结构说明）。

三类均实现（AC-10.1），避免将来接入时再动适配层；但**验收分层**：只有
`x_twitter` 有真实数据可做端到端，`rss` / `jin10_flash` 仅单测覆盖并标注
「待接入 AI 链路后补真实验收」——不得声称三类均已真实验收通过（AC-10.3）。
"""
from __future__ import annotations

from agent_hub.sources.base import L1InputParts, SourceRecord

_TITLE_MAX = 80

# 已实测确认的**流程标记**取值，非领域分类，须从 domain_tags 排除。
# CN-006 后 domain_tags 的真源已改为 sources.domain_tags，此集合是对
# l0_label 误用的历史防御，保留以防将来有人把它接回来。
NON_DOMAIN_LABELS = frozenset({"direct_display"})


def map_domain_tags(raw) -> list[str]:
    """`sources.domain_tags`(jsonb) → `list[str]`。

    与 xiaobao `l1-processor.ts:257-278` 的归一化对齐。**必须做类型判定**：
    实机核出该列类型不统一（4 行中 2 行 `array`、2 行 `object {}`），而
    `L1Input.domain_tags` 是 `list[str]`——按数组直接构造会触发 pydantic 校验
    失败 → 归 `MappingError(client_error)` → 不可重试直接 `final_failed`，
    冒烟数据会全批报废（CN-004 留痕 / CN-006 实机订正）。

    **不得「优化」成 `raw or []`**：`{}` 是 falsy 恰好蒙对，但 `{"a": 1}` 会
    漏过去——这正是该写法的危险之处。
    """
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value and value not in NON_DOMAIN_LABELS:
            out.append(value)
    return out


class XTwitterAdapter:
    """`x_twitter`：该类**无 title 键**，需由正文构造短标题。

    短标题供 `_build_query` / `_build_kb_query` 使用——它们优先取
    `raw_content["title"]`，缺失时才回退 `raw_text` 切片。
    """

    source_type = "x_twitter"

    def build(self, record: SourceRecord) -> L1InputParts:
        content = record.content or {}
        text = str(content.get("text") or "")
        return L1InputParts(
            title=text[:_TITLE_MAX],
            raw_text=text,
            extra_raw_content={
                "author_username": content.get("author_username") or "",
                "author_name": content.get("author_name") or "",
            },
            # 该源的 source_item_url 指向推文自身，正文已在上面的 text 里；
            # 抓它是重复劳动且必然失败（x.com 需认证）。理由详见 L1InputParts。
            url_adds_content=False,
        )


class _TitleSummaryAdapter:
    """`rss` / `jin10_flash` 共用形状：title + summary。

    R-5 明确 `rss.author` 键**可能不存在**（非空串），故一律用 `.get()`。
    """

    source_type = ""

    def build(self, record: SourceRecord) -> L1InputParts:
        content = record.content or {}
        return L1InputParts(
            title=str(content.get("title") or ""),
            raw_text=str(content.get("summary") or ""),
        )


class RssAdapter(_TitleSummaryAdapter):
    source_type = "rss"


class Jin10FlashAdapter(_TitleSummaryAdapter):
    source_type = "jin10_flash"
