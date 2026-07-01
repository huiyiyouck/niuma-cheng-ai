"""news-l1 处理图（LangGraph，ADR-0001 确定性条件图）。

S1 建立最小真实骨架与状态模型：
    ingest_context -> llm_process -> normalize_output
预取上下文在 ingest_context 归一化消费，但不计入 tool_summary（AC-5 口径）。
LLM 通过注入的 client 调用，全 provider 失败时降级为完全失败（output=None）。

主动工具（link/web）的条件分支与路由启发式留 S3；provider fallback 与
JSON 修复留 S2。本片工具计数保持 0。
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

_ENGINE_TAG = "engine:agent_hub"


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
    context_items: list[ContextItem]
    tool_summary: ToolSummary
    tool_budget_used: int
    needs_context: bool
    degradations: list[str]
    errors: list[StepError]
    llm_result: object  # LLMResult | None
    output: Optional[L1Output]


def init_news_l1_state(run_id: str, inp: L1Input, client: AIClient) -> L1State:
    return {
        "run_id": run_id,
        "inp": inp,
        "client": client,
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
        needs_context=bool(parsed.get("needs_context", state["needs_context"])),
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
    g.add_node("llm_process", llm_process_node)
    g.add_node("normalize_output", normalize_output_node)
    g.add_edge(START, "ingest_context")
    g.add_edge("ingest_context", "llm_process")
    g.add_edge("llm_process", "normalize_output")
    g.add_edge("normalize_output", END)
    return g.compile()


news_l1_graph = build_news_l1_graph()
