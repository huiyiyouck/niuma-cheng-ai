"""news-l1 工具适配层契约与默认实现（设计 §3 tool adapters）。

工具返回中立的 `ToolResult` / `ToolResultItem`（不依赖 graph 的 ContextItem，避免
循环导入），由 graph 节点转换为 ContextItem。`NewsTools` 协议使工具可注入，单测
注入 fake 覆盖路由与降级，不触外部网络；`DefaultNewsTools` 组合真实 adapter。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from agent_hub.tools.kb import kb_configured, search_kb
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
    """工具协议。

    三个做出网调用的方法为 async；`extract_url` **保持同步**——它是纯字典取值
    与前缀判定、无 IO 且耗时为微秒级，按 O-8 的划线判据（「无 IO 且耗时毫秒级
    保持同步」）不应改为协程。设计 §6.1 步 1 写「4 方法改 async」不够精确，
    照字面改会给一个纯计算函数套上协程调度开销。
    """

    tavily_configured: bool
    kb_configured: bool

    def extract_url(self, raw_content: dict) -> str | None: ...
    async def read_url(self, url: str, timeout_ms: int) -> ToolResult: ...
    async def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult: ...
    async def search_kb(self, query: str, top_n: int, timeout_ms: int, **kw) -> ToolResult: ...


class DefaultNewsTools:
    """真实工具组合：link 自抓 + Tavily 搜索 + xiaobao 库内检索（CN-002）。"""

    def __init__(self):
        self.tavily_configured = bool(os.getenv("TAVILY_API_KEY"))
        self.kb_configured = kb_configured()

    def extract_url(self, raw_content: dict) -> str | None:
        return extract_url(raw_content)

    async def read_url(self, url: str, timeout_ms: int) -> ToolResult:
        return await read_url(url, timeout_ms)

    async def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult:
        return await search_web(query, max_results, timeout_ms)

    async def search_kb(self, query: str, top_n: int, timeout_ms: int, **kw) -> ToolResult:
        return await search_kb(query, top_n, timeout_ms, **kw)


def get_news_tools() -> NewsTools:
    """FastAPI 依赖：注入工具。测试通过 dependency_overrides 替换。"""
    return DefaultNewsTools()
