"""库内检索（KB）工具（设计 §4.3，O-3 / CN-001 / CN-002）。

预取 KB 上下文（`L1Input.kb_results`）由 graph 的 ingest_context 直接消费，不经本模块。
主动实时 KB 检索（CN-002 纳入 v0.1）：ai 用提炼的短查询词回调 xiaobao
`POST /v1/kb-search`（契约 coordination `contracts/kb-search.md` v1），结果计入
`tool_summary.kb_search`。未配置 `KB_SEARCH_URL` 时降级为 not_configured、不阻塞主流程。
"""
from __future__ import annotations

import os

import httpx

_MAX_QUERY_CHARS = 300


def kb_configured() -> bool:
    return bool(os.getenv("KB_SEARCH_URL", "").strip())


def search_kb(
    query: str,
    top_n: int,
    timeout_ms: int,
    *,
    exclude_raw_item_id: str | None = None,
    source_id: str | None = None,
    domain_tags: list[str] | None = None,
):
    from agent_hub.tools.base import ToolResult, ToolResultItem

    url = os.getenv("KB_SEARCH_URL", "").strip()
    if not url:
        return ToolResult(ok=False, error="not_configured")

    headers = {}
    token = os.getenv("KB_ADMIN_TOKEN", "").strip()
    if token:
        headers["x-admin-token"] = token

    body: dict = {"query": query[:_MAX_QUERY_CHARS], "top_n": max(1, min(10, top_n))}
    if exclude_raw_item_id:
        body["exclude_raw_item_id"] = exclude_raw_item_id
    if source_id:
        body["source_id"] = source_id
    if domain_tags:
        body["domain_tags"] = domain_tags

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=timeout_ms / 1000)
    except httpx.HTTPError:
        return ToolResult(ok=False, error="kb_search_failed")

    if resp.status_code >= 400:
        return ToolResult(ok=False, error=f"http_{resp.status_code}")

    try:
        results = resp.json().get("results", [])
    except ValueError:
        return ToolResult(ok=False, error="bad_response")

    items = [
        ToolResultItem(
            content=str(r.get("content") or r.get("summary") or ""),
            title=r.get("title"),
            url=r.get("url"),
            metadata={"source": "kb", "news_id": r.get("news_id")},
        )
        for r in results
        if (r.get("content") or r.get("summary"))
    ]
    return ToolResult(ok=True, items=items)
