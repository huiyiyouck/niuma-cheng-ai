"""news-l1 处理图（LangGraph，ADR-0001 确定性条件图）。

条件图（设计 §4.3）：
    ingest_context
      -> [证据不足且有 URL] link_read
      -> [证据仍不足且 Tavily 已配置] web_search
      -> llm_process -> normalize_output

预取上下文在 ingest_context 归一化消费，但不计入 tool_summary（AC-5 口径）。
主动 link/web 工具「发起即计数」并受 max_tool_calls 预算约束；失败可降级继续。
主动 KB 实时检索在 xiaobao 契约落地前不触发，缺口以 needs_context 标记。
LLM 通过注入的 client 调用，全 provider 失败时降级为完全失败（output=None）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_hub.llm.client import AIClient
from agent_hub.llm.prompts import build_news_l1_messages
from agent_hub.schemas import (
    L1Input,
    L1Output,
    ScoreDimension,
    ScoreDimensions,
    Tags,
    ToolSummary,
)
from agent_hub.tools.base import NewsTools

_ENGINE_TAG = "engine:agent_hub"
# 上下文充分性启发式阈值（设计 §4.3）
_MIN_RAW_LEN = 300
_MIN_CTX_LEN = 500
_LINK_TIMEOUT_MS = 8000
_QUERY_MAX_LEN = 180


@dataclass
class ContextItem:
    """归一化的上下文片段（预取或主动工具产出）。"""

    source_type: Literal["kb", "link", "web", "raw"]
    content: str
    title: Optional[str] = None
    url: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class StepError:
    step: str
    kind: str
    message: str
    recoverable: bool


class L1State(TypedDict):
    run_id: str
    inp: L1Input
    client: AIClient
    tools: NewsTools
    context_items: list[ContextItem]
    tool_summary: ToolSummary
    tool_budget_used: int
    needs_context: bool
    degradations: list[str]
    errors: list[StepError]
    llm_result: object  # LLMResult | None
    output: Optional[L1Output]


def init_news_l1_state(
    run_id: str, inp: L1Input, client: AIClient, tools: NewsTools
) -> L1State:
    return {
        "run_id": run_id,
        "inp": inp,
        "client": client,
        "tools": tools,
        "context_items": [],
        "tool_summary": ToolSummary(),
        "tool_budget_used": 0,
        "needs_context": False,
        "degradations": [],
        "errors": [],
        "llm_result": None,
        "output": None,
    }


def ingest_context_node(state: L1State) -> dict:
    """把调用方预取的上下文归一化为 context_items；不计入 tool_summary。"""
    inp = state["inp"]
    items: list[ContextItem] = []

    if inp.raw_text.strip():
        items.append(ContextItem(source_type="raw", content=inp.raw_text))

    for kb in inp.kb_results:
        content = str(kb.get("summary") or kb.get("content") or "").strip()
        if content:
            items.append(
                ContextItem(
                    source_type="kb",
                    title=kb.get("title"),
                    content=content,
                    metadata={"prefetch": True},
                )
            )

    if inp.link_content and inp.link_content.strip():
        items.append(
            ContextItem(
                source_type="link",
                content=inp.link_content.strip(),
                url=_extract_url(inp.raw_content),
                metadata={"prefetch": True},
            )
        )

    if inp.search_summary and inp.search_summary.strip():
        items.append(
            ContextItem(
                source_type="web",
                content=inp.search_summary.strip(),
                metadata={"prefetch": True},
            )
        )

    return {"context_items": items}


def link_read_node(state: L1State) -> dict:
    """从 raw_content 约定 key 抓取链接正文。发起即计数，失败可降级继续。"""
    inp = state["inp"]
    tools = state["tools"]
    url = tools.extract_url(inp.raw_content)
    timeout = min(inp.options.timeout_ms, _LINK_TIMEOUT_MS)
    result = tools.read_url(url, timeout)

    updates: dict = {
        "tool_summary": _bump_tool(state["tool_summary"], "link_read"),
        "tool_budget_used": state["tool_budget_used"] + 1,
    }
    if result.ok and result.items:
        updates["context_items"] = state["context_items"] + [
            ContextItem(
                source_type="link",
                content=item.content,
                title=item.title,
                url=item.url or url,
                metadata={"active": True},
            )
            for item in result.items
        ]
    else:
        updates["errors"] = state["errors"] + [
            StepError("link_read", "fetch_error", result.error or "failed", True)
        ]
        updates["degradations"] = state["degradations"] + ["link_read_failed"]
    return updates


def web_search_node(state: L1State) -> dict:
    """Tavily 搜索补充上下文。发起即计数，失败可降级继续。"""
    inp = state["inp"]
    tools = state["tools"]
    result = tools.search_web(_build_query(inp), inp.options.max_tool_calls, inp.options.timeout_ms)

    updates: dict = {
        "tool_summary": _bump_tool(state["tool_summary"], "web_search"),
        "tool_budget_used": state["tool_budget_used"] + 1,
    }
    if result.ok and result.items:
        updates["context_items"] = state["context_items"] + [
            ContextItem(
                source_type="web",
                content=item.content,
                title=item.title,
                url=item.url,
                metadata={"active": True, **item.metadata},
            )
            for item in result.items
        ]
    else:
        updates["errors"] = state["errors"] + [
            StepError("web_search", "search_error", result.error or "failed", True)
        ]
        updates["degradations"] = state["degradations"] + ["web_search_failed"]
    return updates


def route_after_ingest(state: L1State) -> str:
    if _should_link_read(state):
        return "link_read"
    if _should_web_search(state):
        return "web_search"
    return "llm_process"


def route_after_link(state: L1State) -> str:
    if _should_web_search(state):
        return "web_search"
    return "llm_process"


def _should_link_read(state: L1State) -> bool:
    inp = state["inp"]
    has_url = state["tools"].extract_url(inp.raw_content) is not None
    prefetched = bool(inp.link_content and inp.link_content.strip())
    return (
        has_url
        and not prefetched
        and _budget_ok(state)
        and _context_insufficient(state)
    )


def _should_web_search(state: L1State) -> bool:
    inp = state["inp"]
    prefetched = bool(inp.search_summary and inp.search_summary.strip())
    return (
        state["tools"].tavily_configured
        and not prefetched
        and _budget_ok(state)
        and _context_insufficient(state)
    )


def _budget_ok(state: L1State) -> bool:
    return state["tool_budget_used"] < state["inp"].options.max_tool_calls


def _context_insufficient(state: L1State) -> bool:
    """证据不足启发式：raw_text <300 字，且非 raw 上下文有效内容 <500 字。"""
    raw_len = len(state["inp"].raw_text.strip())
    ctx_len = sum(
        len(ci.content) for ci in state["context_items"] if ci.source_type != "raw"
    )
    return raw_len < _MIN_RAW_LEN and ctx_len < _MIN_CTX_LEN


def _bump_tool(ts: ToolSummary, field_name: str) -> ToolSummary:
    return ToolSummary(
        web_search=ts.web_search + (1 if field_name == "web_search" else 0),
        link_read=ts.link_read + (1 if field_name == "link_read" else 0),
        kb_search=ts.kb_search,
    )


def _build_query(inp: L1Input) -> str:
    parts = [
        inp.raw_content.get("title", "") if isinstance(inp.raw_content, dict) else "",
        inp.raw_text[:120],
        inp.source_identity,
    ]
    return " ".join(p for p in parts if p).strip()[:_QUERY_MAX_LEN]


def llm_process_node(state: L1State) -> dict:
    """调用注入的 LLM client。失败时记录 recoverable=False 错误、不抛异常。"""
    client: AIClient = state["client"]
    inp = state["inp"]
    messages = build_news_l1_messages(inp, state["context_items"])
    try:
        result = client.complete_json(messages, timeout_ms=inp.options.timeout_ms)
    except Exception as exc:  # noqa: BLE001 — 全 provider 失败统一降级为完全失败
        err = StepError(
            step="llm_process",
            kind="provider_error",
            message=_redact(exc),
            recoverable=False,
        )
        return {"errors": state["errors"] + [err], "llm_result": None}
    return {"llm_result": result}


def normalize_output_node(state: L1State) -> dict:
    """把 LLMResult 映射为 L1Output；无结果则保持 output=None（完全失败）。"""
    result = state["llm_result"]
    if result is None:
        return {"output": None}

    parsed: dict = result.parsed or {}
    scores = parsed.get("scores") or {}

    def dim(name: str) -> ScoreDimension:
        d = scores.get(name) or {}
        return ScoreDimension(
            score=_clamp_score(d.get("score", 0)),
            reason=str(d.get("reason", "")),
        )

    # context 引用校验：只保留证据（预取 / 工具结果）中真实出现的 URL，过滤 LLM 编造
    evidence_urls = {ci.url for ci in state["context_items"] if ci.url}
    context = [
        item
        for item in (parsed.get("context") or [])
        if isinstance(item, dict) and item.get("url") in evidence_urls
    ]

    raw_tags = parsed.get("tags") or {}
    processing = [_ENGINE_TAG, f"llm:{result.provider_name}"]
    processing.extend(f"degraded:{d}" for d in state["degradations"])
    processing.extend(f"degraded:{d}" for d in result.degradations)

    output = L1Output(
        title=str(parsed.get("title") or state["inp"].raw_text[:40]),
        summary=str(parsed.get("summary") or ""),
        translation=parsed.get("translation") or {},
        context=context,
        analysis=parsed.get("analysis"),
        score_dimensions=ScoreDimensions(
            timeliness=dim("timeliness"),
            impact=dim("impact"),
            confidence=dim("confidence"),
            clarity=dim("clarity"),
        ),
        tags=Tags(
            domain=list(raw_tags.get("domain") or []),
            entity=list(raw_tags.get("entity") or []),
            event=list(raw_tags.get("event") or []),
            content_type=list(raw_tags.get("content_type") or []),
            processing=processing,
        ),
        needs_context=bool(parsed.get("needs_context", False))
        or _context_insufficient(state),
    )
    return {"output": output, "needs_context": output.needs_context}


def _clamp_score(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, n))


def _extract_url(raw_content: dict) -> Optional[str]:
    url = raw_content.get("url") or raw_content.get("canonical_url")
    return url if isinstance(url, str) and url else None


def _redact(exc: Exception) -> str:
    """脱敏错误摘要：只保留异常类型与短消息，避免泄漏 key / prompt。"""
    msg = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {msg[:200]}"


def build_news_l1_graph():
    g = StateGraph(L1State)
    g.add_node("ingest_context", ingest_context_node)
    g.add_node("link_read", link_read_node)
    g.add_node("web_search", web_search_node)
    g.add_node("llm_process", llm_process_node)
    g.add_node("normalize_output", normalize_output_node)
    g.add_edge(START, "ingest_context")
    g.add_conditional_edges(
        "ingest_context",
        route_after_ingest,
        {"link_read": "link_read", "web_search": "web_search", "llm_process": "llm_process"},
    )
    g.add_conditional_edges(
        "link_read",
        route_after_link,
        {"web_search": "web_search", "llm_process": "llm_process"},
    )
    g.add_edge("web_search", "llm_process")
    g.add_edge("llm_process", "normalize_output")
    g.add_edge("normalize_output", END)
    return g.compile()


news_l1_graph = build_news_l1_graph()
