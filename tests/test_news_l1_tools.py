"""news-l1 S3 工具真实化：条件路由、计数、降级测试（设计 §8 测试 4/5/8）。

用注入的 FakeTools 覆盖路由启发式与降级；真实 httpx 抓取 / Tavily 调用的连通性
由部署冒烟验证，不在单测覆盖。
"""
import pytest
from fastapi.testclient import TestClient

from agent_hub.llm.client import get_ai_client
from agent_hub.main import app
from agent_hub.tools.base import ToolResult, ToolResultItem, get_news_tools

from test_news_l1 import FakeClient, _payload


class FakeTools:
    def __init__(
        self, link=None, web=None, kb=None, tavily_configured=True, kb_configured=False, url=None
    ):
        self._link = link
        self._web = web
        self._kb = kb
        self.tavily_configured = tavily_configured
        self.kb_configured = kb_configured
        self._url = url
        self.link_calls = 0
        self.web_calls = 0
        self.kb_calls = 0

    def extract_url(self, raw_content):
        return self._url or raw_content.get("url") or raw_content.get("canonical_url")

    def read_url(self, url, timeout_ms):
        self.link_calls += 1
        return self._link or ToolResult(ok=False, error="failed")

    def search_web(self, query, max_results, timeout_ms):
        self.web_calls += 1
        return self._web or ToolResult(ok=False, error="failed")

    def search_kb(self, query, top_n, timeout_ms, **kw):
        self.kb_calls += 1
        return self._kb or ToolResult(ok=False, error="failed")


def make_client(tools, client=None):
    app.dependency_overrides[get_ai_client] = lambda: client or FakeClient()
    app.dependency_overrides[get_news_tools] = lambda: tools
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


_SHORT = "短新闻。"  # < 300 字 → 上下文不足


# --- 测试 4：有 URL 且上下文不足 → 触发 link read，计入 link_read ---
def test_link_read_triggered_when_context_insufficient():
    tools = FakeTools(
        link=ToolResult(ok=True, items=[ToolResultItem(content="抓取正文", url="https://x/a")]),
        url="https://x/a",
        tavily_configured=False,
    )
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(raw_text=_SHORT, raw_content={"url": "https://x/a"}),
    ).json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["link_read"] == 1
    assert tools.link_calls == 1


def test_link_not_triggered_when_prefetched():
    tools = FakeTools(url="https://x/a", tavily_configured=False)
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(
            raw_text=_SHORT,
            raw_content={"url": "https://x/a"},
            link_content="已预取正文",
        ),
    ).json()
    assert body["tool_summary"]["link_read"] == 0
    assert tools.link_calls == 0


# --- 测试 5：Tavily 未配置 → 不触发 web search，返回可降级结果 ---
def test_web_search_not_triggered_when_tavily_unconfigured():
    tools = FakeTools(tavily_configured=False)  # extract_url→None（无 url）
    c = make_client(tools)
    body = c.post("/v1/runs/news-l1", json=_payload(raw_text=_SHORT)).json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["web_search"] == 0
    assert tools.web_calls == 0


def test_web_search_triggered_when_configured_and_insufficient():
    tools = FakeTools(
        web=ToolResult(
            ok=True,
            items=[ToolResultItem(content="搜索结果", url="https://s/1", title="r")],
        ),
        tavily_configured=True,
    )
    c = make_client(tools)
    body = c.post("/v1/runs/news-l1", json=_payload(raw_text=_SHORT)).json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["web_search"] == 1
    assert tools.web_calls == 1


# --- 测试 8（完整）：工具失败但 LLM 成功 → succeeded + processing 含降级标记 ---
def test_link_fail_llm_ok_returns_succeeded_with_degradation():
    tools = FakeTools(
        link=ToolResult(ok=False, error="fetch_failed"),
        url="https://x/a",
        tavily_configured=False,
    )
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(raw_text=_SHORT, raw_content={"url": "https://x/a"}),
    ).json()
    assert body["status"] == "succeeded"
    # 发起即计数
    assert body["tool_summary"]["link_read"] == 1
    assert "degraded:link_read_failed" in body["output"]["tags"]["processing"]


# --- 测试（CN-002 / S5）：KB 主动检索 ---
def test_kb_search_triggered_first_when_configured():
    tools = FakeTools(
        kb=ToolResult(ok=True, items=[ToolResultItem(content="库内背景" * 200, title="bg")]),
        kb_configured=True,
        tavily_configured=True,
        url="https://x/a",
    )
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(raw_text=_SHORT, raw_content={"url": "https://x/a"}),
    ).json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["kb_search"] == 1
    assert tools.kb_calls == 1
    # KB 补足上下文后 link/web 跳过
    assert body["tool_summary"]["link_read"] == 0
    assert body["tool_summary"]["web_search"] == 0


def test_kb_not_triggered_when_prefetched():
    tools = FakeTools(kb_configured=True)
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(raw_text=_SHORT, kb_results=[{"title": "a", "summary": "b"}]),
    ).json()
    assert body["tool_summary"]["kb_search"] == 0
    assert tools.kb_calls == 0


def test_kb_not_triggered_when_unconfigured():
    tools = FakeTools(kb_configured=False)
    c = make_client(tools)
    body = c.post("/v1/runs/news-l1", json=_payload(raw_text=_SHORT)).json()
    assert body["tool_summary"]["kb_search"] == 0
    assert tools.kb_calls == 0


def test_kb_fail_degraded_but_succeeded():
    tools = FakeTools(
        kb=ToolResult(ok=False, error="http_500"),
        kb_configured=True,
        tavily_configured=False,
    )
    c = make_client(tools)
    body = c.post("/v1/runs/news-l1", json=_payload(raw_text=_SHORT)).json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["kb_search"] == 1  # 发起即计数
    assert "degraded:kb_search_failed" in body["output"]["tags"]["processing"]


# --- 上下文充分时不触发任何工具 ---
def test_sufficient_context_skips_tools():
    tools = FakeTools(url="https://x/a", tavily_configured=True)
    long_text = "新闻正文。" * 100  # > 300 字
    c = make_client(tools)
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(raw_text=long_text, raw_content={"url": "https://x/a"}),
    ).json()
    assert body["tool_summary"]["link_read"] == 0
    assert body["tool_summary"]["web_search"] == 0
    assert tools.link_calls == 0
    assert tools.web_calls == 0
