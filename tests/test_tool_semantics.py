"""AC-7 三分支与预算跳过（设计 §8 测试 17 / 18、§4.11、§4.5）。

v0.1 的两分支缺陷：`if result.ok and result.items` 把「调用成功但无结果」并进了
故障分支，空结果会产出 `degraded:{tool}_failed`——「没搜到」看起来像「服务挂了」。
DB 模式下预取上下文消失、KB 转主动检索，空结果从边缘情形变成常态，噪声会淹没
真故障，而日志与降级信号的区分度正是「高可用」的立足点。

这些用例覆盖的是**改造后的新语义**，与黄金样本互补：黄金样本四类刻意不含空结果
场景（那是本组测试的对象），两者不会在同一判据下打架。
"""
from __future__ import annotations

import pytest

from agent_hub.budget import ItemBudget
from agent_hub.schemas import L1Input
from agent_hub.tasks import run_task
from agent_hub.tools.base import ToolResult, ToolResultItem
from tests.test_news_l1 import FakeClient

_TOOLS = ["kb_search", "link_read", "web_search"]


class ScriptedTools:
    """按 `outcome` 统一控制三工具的返回形态。"""

    def __init__(self, outcome: str):
        self._outcome = outcome
        self.tavily_configured = True
        self.kb_configured = True

    def extract_url(self, raw_content):
        return "https://example.com/a"

    def _result(self) -> ToolResult:
        if self._outcome == "hit":
            return ToolResult(ok=True, items=[ToolResultItem(content="证据。", url="https://e/1")])
        if self._outcome == "empty":
            return ToolResult(ok=True, items=[])          # 调用成功但无匹配
        return ToolResult(ok=False, error="unavailable")  # 调用故障

    async def read_url(self, url, timeout_ms):
        return self._result()

    async def search_web(self, query, max_results, timeout_ms):
        return self._result()

    async def search_kb(self, query, top_n, timeout_ms, **kw):
        return self._result()


def _input() -> L1Input:
    return L1Input(
        source_identity="demo",
        domain_tags=["t"],
        raw_text="短文本。",
        raw_content={"url": "https://example.com/a"},
    )


async def _run(tools, budget=None):
    return await run_task("news-l1", "run_sem", _input(), client=FakeClient(),
                          tools=tools, budget=budget)


# --- 测试 17：AC-7 三分支 ---
async def test_hit_counts_and_no_degradation():
    r = await _run(ScriptedTools("hit"))
    assert r.degradations == []
    assert all(getattr(r.tool_summary, t) == 1 for t in _TOOLS)


async def test_empty_result_counts_but_not_degraded():
    """空结果：计入 tool_summary（发起即计数），但**不进 degradations**。"""
    r = await _run(ScriptedTools("empty"))
    assert r.degradations == [], f"空结果不应产生降级标记，实际 {r.degradations}"
    assert all(getattr(r.tool_summary, t) == 1 for t in _TOOLS)
    processing = r.output.tags.processing
    assert not any(d.startswith("degraded:") for d in processing), processing


async def test_call_failure_is_degraded():
    r = await _run(ScriptedTools("failed"))
    assert sorted(r.degradations) == sorted(f"{t}_failed" for t in _TOOLS)
    assert all(getattr(r.tool_summary, t) == 1 for t in _TOOLS)


async def test_empty_and_failure_are_distinguishable():
    """本组测试的要点：两种情形必须能被区分，否则观测面失效。"""
    empty = await _run(ScriptedTools("empty"))
    failed = await _run(ScriptedTools("failed"))
    assert empty.degradations != failed.degradations


# --- 测试 18：预算跳过与工具故障可区分 ---
@pytest.mark.parametrize("total_ms", [0, 500], ids=["exhausted", "below_min_segment"])
async def test_budget_skip_is_not_reported_as_tool_failure(total_ms):
    """预算不足时跳过调用，记 `{tool}_budget_exhausted` 而非 `{tool}_failed`。

    500ms 这一例是关键：它 > 0（`exhausted()` 为假）但 < `min_segment_ms`，
    若只判 `exhausted()` 就会用 500ms 去发起一次必然超时的调用，被 AC-7.2
    记成调用故障——预算耗尽被误报为下游服务挂了。
    """
    budget = ItemBudget(total_ms=total_ms, min_segment_ms=1000)
    r = await _run(ScriptedTools("hit"), budget=budget)

    assert sorted(r.degradations) == sorted(f"{t}_budget_exhausted" for t in _TOOLS)
    assert not any(d.endswith("_failed") for d in r.degradations)
    # 未发起调用：既不计 tool_summary，也不消耗 max_tool_calls 配额
    assert all(getattr(r.tool_summary, t) == 0 for t in _TOOLS)
