"""niuma-cheng-ai · AI 处理中枢 — FastAPI 入口。

新闻平台（niuma-cheng-xiaobao, Node.js）通过 HTTP 调用本服务处理新闻 L1。
当前为骨架：契约 + 流水线结构就位，处理节点为占位实现。
"""
import time
import uuid

from fastapi import FastAPI

from agent_hub.graphs.news_l1 import news_l1_graph
from agent_hub.schemas import L1Input, RunResponse, ToolSummary

app = FastAPI(title="niuma-cheng-ai", version="0.0.1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "niuma-cheng-ai"}


@app.post("/v1/runs/news-l1", response_model=RunResponse)
def run_news_l1(inp: L1Input) -> RunResponse:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    start = time.monotonic()
    try:
        result = news_l1_graph.invoke(
            {"inp": inp, "kb_hits": 0, "link_used": False, "search_used": False, "output": None}
        )
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResponse(
            run_id=run_id,
            status="succeeded",
            elapsed_ms=elapsed,
            tool_summary=ToolSummary(
                web_search=1 if result["search_used"] else 0,
                link_read=1 if result["link_used"] else 0,
                kb_search=result["kb_hits"],
            ),
            output=result["output"],
        )
    except Exception as e:  # noqa: BLE001 — 骨架阶段统一兜底，细分错误类型待架构定稿
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResponse(
            run_id=run_id,
            status="failed",
            elapsed_ms=elapsed,
            tool_summary=ToolSummary(),
            error=str(e),
        )
