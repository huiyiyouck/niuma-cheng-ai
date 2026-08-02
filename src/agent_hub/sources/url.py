"""URL 规范化（AC-2.4 / 设计 §3.5）。

**为什么必须规范化后回填 `raw_content["url"]`**：决定 link_read 是否触发的是
`tools/link_reader.py:extract_url`，它额外要求 `http(s)://` 前缀；而
`graphs/news_l1.py:_extract_url`（只用于给 context 条目标 url）不检查前缀——
两处判定不一致。若把 `raw_items.content` 原样塞入而不回填规范化后的 URL，
`_should_link_read` 恒为 False，**link_read 不报错、不降级、静默失效**，
是最难归因的一类问题。规范化让两处拿到同一个值，判定因此归一。

C-13 已确认 `rss` / `jin10_flash` 的 `source_item_url` **不保证带协议前缀**，
故本模块的补前缀分支是必需的，不是防御性冗余。

**适用范围**：以上只对「URL 指向外部补充材料」的源成立。`x_twitter` 的
`source_item_url` 指向推文自身、正文已在 `content.text` 里，其映射不回填
URL（见 `L1InputParts.url_adds_content`）——那不是静默失效，是有意不抓。
"""
from __future__ import annotations

import re

# 形如域名：至少一个点、顶级域为 2+ 字母，可带路径
_DOMAIN_LIKE = re.compile(r"^[\w.-]+\.[A-Za-z]{2,}(/.*)?$")


def normalize_url(raw: str | None) -> str | None:
    """把 `source_item_url` 规范化为带协议前缀的 URL；无法规范化返回 `None`。

    对「其他」一律返回 `None` 而不猜测——**猜错会让 link_read 抓到错误页面，
    比不抓更糟**（§3.5）。
    """
    if not raw or not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    if _DOMAIN_LIKE.match(value):
        return "https://" + value
    return None
