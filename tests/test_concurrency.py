"""AC-9.5：HTTP 模式并发不退化（设计 §8 测试 2）。

这是 AC-9.1「改造彻底性」的**唯一客观检验**——只靠 code review 看不出漏了
哪个同步点。端点改 `async def` 后 FastAPI 不再把它派发到线程池，任一处遗漏
都会让 HTTP 模式从「线程池并发」退化为「event loop 串行」，**比 v0.1 更糟**。

判据（AC-9.5）：并发 N≥3 个请求、LLM 走 mock 固定延时，总耗时 < 1.5 × 单条。
串行化时总耗时会趋近 N × 单条，与判据拉开明显距离。
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from agent_hub.llm.client import LLMResult, get_ai_client
from agent_hub.main import app
from agent_hub.tools.base import get_news_tools
from tests.test_news_l1 import NullTools, make_parsed

_LLM_DELAY_S = 0.3
_CONCURRENCY = 3


class SlowClient:
    """固定延时的 LLM client：延时必须是 `await`，才能反映真实的 IO 等待。"""

    async def complete_json(self, messages, timeout_ms):
        await asyncio.sleep(_LLM_DELAY_S)
        return LLMResult(provider_name="slow", parsed=make_parsed(), raw="{}")


@pytest.fixture(autouse=True)
def _overrides():
    app.dependency_overrides[get_ai_client] = SlowClient
    app.dependency_overrides[get_news_tools] = NullTools
    yield
    app.dependency_overrides.clear()


def _payload() -> dict:
    return {
        "source_identity": "demo",
        "domain_tags": ["test"],
        "raw_text": "示例新闻文本。",
        "raw_content": {},
        "kb_results": [],
        "link_content": None,
        "search_summary": None,
    }


async def test_http_mode_concurrency_does_not_degrade():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.monotonic()
        responses = await asyncio.gather(
            *(client.post("/v1/runs/news-l1", json=_payload()) for _ in range(_CONCURRENCY))
        )
        elapsed = time.monotonic() - start

    assert all(r.status_code == 200 for r in responses)
    assert all(r.json()["status"] == "succeeded" for r in responses)

    limit = _LLM_DELAY_S * 1.5
    assert elapsed < limit, (
        f"并发 {_CONCURRENCY} 条耗时 {elapsed:.2f}s，超过判据 {limit:.2f}s"
        f"（单条 {_LLM_DELAY_S}s）——async 改造有遗漏的同步阻塞点，"
        f"HTTP 模式已退化为 event loop 串行"
    )
