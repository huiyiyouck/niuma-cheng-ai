"""Web 搜索工具（设计 §4.5，CN-001）。

ai 直连 Tavily API（不经 openclaw 网关），key 取自 `TAVILY_API_KEY` 环境变量。
未配置时返回 not_configured，由 graph 降级、不计数、不阻塞主流程。
留 search provider 薄抽象：未来加 SearXNG/Brave 只需新增 adapter，v0.1 不做多家。
"""
from __future__ import annotations

import os

import httpx

_TAVILY_URL = "https://api.tavily.com/search"


def search_web(query: str, max_results: int, timeout_ms: int):
    from agent_hub.tools.base import ToolResult, ToolResultItem

    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return ToolResult(ok=False, error="not_configured")

    try:
        resp = httpx.post(
            _TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=timeout_ms / 1000,
        )
    except httpx.HTTPError:
        return ToolResult(ok=False, error="search_failed")

    if resp.status_code >= 400:
        return ToolResult(ok=False, error=f"http_{resp.status_code}")

    try:
        results = resp.json().get("results", [])
    except ValueError:
        return ToolResult(ok=False, error="bad_response")

    items = [
        ToolResultItem(
            content=str(r.get("content", "")),
            title=r.get("title"),
            url=r.get("url"),
            metadata={"provider": "tavily"},
        )
        for r in results
        if r.get("url")
    ]
    return ToolResult(ok=True, items=items)
