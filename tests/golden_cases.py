"""黄金样本四类路径的用例定义（AC-9.4 / 设计 §6.2）。

本文件是 async 改造的**回归基线**：改造前录制快照，改造后用同一组输入与
同一组 mock 重跑并逐字段比对。快照（`tests/golden/*.json`）与本文件的写法
无关——改造时本文件的 fake 必须随协议改为 async，而快照不动，回归判据因此
独立于测试代码的改写（这正是 AC-9.4 要解的循环论证）。

**四类均不含「工具调用成功但无结果」的场景**——该场景是 AC-7 三分支有意
变更的对象（空结果不再进 degradations），混进样本会让「行为不变」与「有意
改变」在同一判据下打架。它由 §8 测试 17 独立覆盖，期望值是改造后的新语义。
"""
from __future__ import annotations

from agent_hub.config import ProviderConfig
from agent_hub.llm.client import ChainedAIClient, LLMResult, ProviderCallError
from agent_hub.schemas import L1Input, RunOptions
from agent_hub.tools.base import ToolResult, ToolResultItem

# ── 固定的 LLM 响应内容（四类共用，保证差异只来自被测路径）─────────────
GOLDEN_PARSED = {
    "title": "示例标题：某公司发布新一代推理芯片",
    "summary": "某公司发布新一代推理芯片，宣称能效比上代提升两倍。",
    "translation": {"zh": "某公司发布新一代推理芯片。"},
    "context": [
        {"url": "https://example.com/kb-1", "note": "背景一"},
        {"url": "https://example.com/never-cited", "note": "不在证据集内，应被过滤"},
    ],
    "analysis": "若能效比属实，将影响推理成本结构。",
    "scores": {
        "timeliness": {"score": 4, "reason": "当日发布"},
        "impact": {"score": 3, "reason": "影响特定行业"},
        "confidence": {"score": 4, "reason": "官方渠道"},
        "clarity": {"score": 5, "reason": "表述明确"},
    },
    "tags": {
        "domain": ["AI", "芯片"],
        "entity": ["某公司"],
        "event": ["产品发布"],
        "content_type": ["新闻"],
    },
    "needs_context": False,
}

GOLDEN_RAW_JSON = (
    '{"title": "示例标题：某公司发布新一代推理芯片", '
    '"summary": "某公司发布新一代推理芯片，宣称能效比上代提升两倍。", '
    '"translation": {"zh": "某公司发布新一代推理芯片。"}, '
    '"context": [{"url": "https://example.com/kb-1", "note": "背景一"}, '
    '{"url": "https://example.com/never-cited", "note": "不在证据集内，应被过滤"}], '
    '"analysis": "若能效比属实，将影响推理成本结构。", '
    '"scores": {"timeliness": {"score": 4, "reason": "当日发布"}, '
    '"impact": {"score": 3, "reason": "影响特定行业"}, '
    '"confidence": {"score": 4, "reason": "官方渠道"}, '
    '"clarity": {"score": 5, "reason": "表述明确"}}, '
    '"tags": {"domain": ["AI", "芯片"], "entity": ["某公司"], '
    '"event": ["产品发布"], "content_type": ["新闻"]}, '
    '"needs_context": false}'
)


def golden_input() -> L1Input:
    """四类共用的固定输入。

    `raw_text` 刻意短于 `_MIN_RAW_LEN`(300)，使证据不足判定为真、工具路由可达；
    预取字段全空，模拟 DB 模式的输入形状（AC-8.2 已知差异之一）。
    """
    return L1Input(
        source_identity="example_source",
        domain_tags=["AI"],
        raw_content={"title": "某公司发布新一代推理芯片", "url": "https://example.com/origin"},
        raw_text="某公司今日发布新一代推理芯片。",
        kb_results=[],
        link_content=None,
        search_summary=None,
        options=RunOptions(max_tool_calls=4, timeout_ms=180000),
    )


# ── Fake 实现（改造时随协议改 async，快照不变）─────────────────────────
class GoldenClient:
    """固定响应的 LLM client（样本 ①②用）。"""

    def __init__(self, provider_name: str = "primary"):
        self._provider_name = provider_name

    async def complete_json(self, messages: list[dict], timeout_ms: int) -> LLMResult:
        return LLMResult(
            provider_name=self._provider_name,
            parsed=dict(GOLDEN_PARSED),
            raw=GOLDEN_RAW_JSON,
            degradations=[],
        )


class GoldenTools:
    """可配置三工具行为的 fake；每项内容刻意短，使后续工具仍满足证据不足判定。"""

    def __init__(self, *, hit: bool, url: str | None = "https://example.com/origin"):
        self._hit = hit
        self._url = url
        self.tavily_configured = True
        self.kb_configured = True

    def extract_url(self, raw_content: dict) -> str | None:
        return self._url

    def _result(self, source: str, url: str) -> ToolResult:
        if not self._hit:
            return ToolResult(ok=False, error=f"{source}_unavailable")
        return ToolResult(
            ok=True,
            items=[ToolResultItem(content=f"{source} 证据片段。", title=f"{source} 标题", url=url)],
        )

    async def read_url(self, url: str, timeout_ms: int) -> ToolResult:
        return self._result("link", "https://example.com/origin")

    async def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult:
        return self._result("web", "https://example.com/web-1")

    async def search_kb(self, query: str, top_n: int, timeout_ms: int, **kw) -> ToolResult:
        return self._result("kb", "https://example.com/kb-1")


class SilentTools:
    """三工具均不触发（样本 ③④用，聚焦 LLM 层）。"""

    tavily_configured = False
    kb_configured = False

    def extract_url(self, raw_content: dict) -> str | None:
        return None

    async def read_url(self, url: str, timeout_ms: int) -> ToolResult:
        raise AssertionError("SilentTools.read_url 不应被调用")

    async def search_web(self, query: str, max_results: int, timeout_ms: int) -> ToolResult:
        raise AssertionError("SilentTools.search_web 不应被调用")

    async def search_kb(self, query: str, top_n: int, timeout_ms: int, **kw) -> ToolResult:
        raise AssertionError("SilentTools.search_kb 不应被调用")


def _providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            name="primary", base_url="https://p1.example/v1",
            api_key_env="GOLDEN_KEY_1", model="model-a", timeout_ms=30000,
        ),
        ProviderConfig(
            name="backup", base_url="https://p2.example/v1",
            api_key_env="GOLDEN_KEY_2", model="model-b", timeout_ms=30000,
        ),
    ]


async def _fenced_caller(provider, messages, timeout_ms) -> str:
    """样本 ③：返回 markdown fence 包裹的 JSON，走 `llm/json.py` 的 _repair 分支。"""
    return "```json\n" + GOLDEN_RAW_JSON + "\n```"


async def _timeout_then_ok_caller(provider, messages, timeout_ms) -> str:
    """样本 ④：primary 超时 → fallback 到 backup 成功。

    改造后此处的超时若变成 `asyncio.TimeoutError` 而未被认作 timeout kind，
    异常会穿透 `_attempt_provider` 导致整条完全失败——快照会立刻抓到。
    """
    if provider.name == "primary":
        raise ProviderCallError(kind="timeout")
    return GOLDEN_RAW_JSON


# ── 四类用例 ───────────────────────────────────────────────────────────
def case_normal_all_tools_hit():
    """① 全工具命中的正常路径：kb → link → web 依次触发且均有结果。"""
    return golden_input(), GoldenClient(), GoldenTools(hit=True)


def case_tools_all_failed():
    """② 工具全失败的降级路径：部分可用仍为 succeeded，degraded 标记齐全。"""
    return golden_input(), GoldenClient(), GoldenTools(hit=False)


def case_llm_json_repair():
    """③ LLM 返回非法 JSON（markdown fence）的解析容错。"""
    return golden_input(), ChainedAIClient(_providers(), caller=_fenced_caller), SilentTools()


def case_llm_timeout_fallback():
    """④ LLM 超时触发 provider fallback：产出应来自 backup。"""
    return (
        golden_input(),
        ChainedAIClient(_providers(), caller=_timeout_then_ok_caller),
        SilentTools(),
    )


CASES = {
    "01_normal_all_tools_hit": case_normal_all_tools_hit,
    "02_tools_all_failed": case_tools_all_failed,
    "03_llm_json_repair": case_llm_json_repair,
    "04_llm_timeout_fallback": case_llm_timeout_fallback,
}
