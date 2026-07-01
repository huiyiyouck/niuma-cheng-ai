"""news-l1 工具适配层契约与默认实现（设计 §3 tool adapters）。

工具返回中立的 `ToolResult` / `ToolResultItem`（不依赖 graph 的 ContextItem，避免
循环导入），由 graph 节点转换为 ContextItem。`NewsTools` 协议使工具可注入，单测
注入 fake 覆盖路由与降级，不触外部网络；`DefaultNewsTools` 组合真实 adapter。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from agent_hub.tools.link_reader import extract_url, read_url
from agent_hub.tools.web_search import search_web


@dataclass
class ToolResultItem:
    content: str
    title: str | None = None
    url: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    ok: bool
    items: list[ToolResultItem] = field(default_factory=list)
    error: str | None = None


class NewsTools(Protocol):
    tavily_configured: bool

    def extract_url(self, raw_content: dict) -> str | None: ...
    def read_url(self, url: str, timeout_ms: int) -> ToolResult: ...
    def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult: ...


class DefaultNewsTools:
    """真实工具组合：link 自抓 + Tavily 搜索。KB 实时检索占位、默认禁用。"""

    def __init__(self):
        self.tavily_configured = bool(os.getenv("TAVILY_API_KEY"))

    def extract_url(self, raw_content: dict) -> str | None:
        return extract_url(raw_content)

    def read_url(self, url: str, timeout_ms: int) -> ToolResult:
        return read_url(url, timeout_ms)

    def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult:
        return search_web(query, max_results, timeout_ms)


def get_news_tools() -> NewsTools:
    """FastAPI 依赖：注入工具。测试通过 dependency_overrides 替换。"""
    return DefaultNewsTools()
