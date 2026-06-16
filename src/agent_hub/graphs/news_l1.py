"""news-l1 处理流水线（LangGraph StateGraph）。

按提案 §12.4 定为「固定流水线」：kb_search → link_read → web_search → llm_process。

当前为骨架：各节点为占位实现，LLM 节点返回结构化占位输出，保证 L1Output 契约
可被新闻平台接住；真实逻辑（外部检索 / 链接读取 / LLM 调用）待 v0.6.1 架构定稿后填充。
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_hub.schemas import L1Input, L1Output, ScoreDimension, ScoreDimensions, Tags


class L1State(TypedDict):
    inp: L1Input
    kb_hits: int
    link_used: bool
    search_used: bool
    output: Optional[L1Output]


def kb_search_node(state: L1State) -> dict:
    # 库内检索由新闻平台预取并通过 kb_results 传入；此处仅统计命中数
    return {"kb_hits": len(state["inp"].kb_results)}


def link_read_node(state: L1State) -> dict:
    return {"link_used": state["inp"].link_content is not None}


def web_search_node(state: L1State) -> dict:
    return {"search_used": state["inp"].search_summary is not None}


def llm_process_node(state: L1State) -> dict:
    inp = state["inp"]
    # TODO(v0.6.1): 接入外部 LLM（OpenAI 兼容），产出真实 L1Output
    output = L1Output(
        title=inp.raw_text[:40] or "（占位标题）",
        summary=inp.raw_text[:120] or "（占位摘要）",
        translation={"zh": ""},
        context=[],
        analysis=None,
        score_dimensions=ScoreDimensions(
            timeliness=ScoreDimension(score=3, reason="占位"),
            impact=ScoreDimension(score=3, reason="占位"),
            confidence=ScoreDimension(score=3, reason="占位"),
            clarity=ScoreDimension(score=3, reason="占位"),
        ),
        tags=Tags(processing=["engine:agent_hub", "stub"]),
        needs_context=False,
    )
    return {"output": output}


def build_news_l1_graph():
    g = StateGraph(L1State)
    g.add_node("kb_search", kb_search_node)
    g.add_node("link_read", link_read_node)
    g.add_node("web_search", web_search_node)
    g.add_node("llm_process", llm_process_node)
    g.add_edge(START, "kb_search")
    g.add_edge("kb_search", "link_read")
    g.add_edge("link_read", "web_search")
    g.add_edge("web_search", "llm_process")
    g.add_edge("llm_process", END)
    return g.compile()


news_l1_graph = build_news_l1_graph()
