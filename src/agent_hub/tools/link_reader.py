"""链接读取工具（设计 §4.4）。

URL 只从 `raw_content.url` / `raw_content.canonical_url` 读取（AC-5，不新增 typed 字段）；
仅允许 http/https；抓取正文裁剪到 12k 字符。返回中立 ToolResult，失败可降级。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from agent_hub.tools.base import ToolResult

_MAX_CHARS = 12000
_FETCH_TIMEOUT_MS = 8000
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)


def extract_url(raw_content: dict) -> str | None:
    url = raw_content.get("url") or raw_content.get("canonical_url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    return None


def read_url(url: str, timeout_ms: int):
    from agent_hub.tools.base import ToolResult, ToolResultItem

    if not url.startswith(("http://", "https://")):
        return ToolResult(ok=False, error="invalid_scheme")

    timeout = min(timeout_ms, _FETCH_TIMEOUT_MS) / 1000
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return ToolResult(ok=False, error="fetch_failed")

    if resp.status_code >= 400:
        return ToolResult(ok=False, error=f"http_{resp.status_code}")

    text = _extract_text(resp.text)[:_MAX_CHARS]
    if not text:
        return ToolResult(ok=False, error="empty_body")
    return ToolResult(ok=True, items=[ToolResultItem(content=text, url=url)])


def _extract_text(html: str) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", html)
    stripped = _TAG_RE.sub(" ", without_scripts)
    return _WS_RE.sub(" ", stripped).strip()
