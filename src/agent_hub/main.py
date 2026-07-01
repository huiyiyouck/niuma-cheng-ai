"""niuma-cheng-ai · AI 处理中枢 — FastAPI 入口。

新闻平台（niuma-cheng-xiaobao, Node.js）通过 HTTP 调用本服务处理新闻 L1。
对外契约保持 news-l1 v1 不变：`POST /v1/runs/news-l1`，内部按 task registry 分发。
降级 / 失败语义对齐 AC-6：部分可用 = succeeded；完全不可用 = failed + output=null。
"""
import time
import uuid

from fastapi import Depends, FastAPI

from agent_hub.llm.client import AIClient, get_ai_client
from agent_hub.schemas import L1Input, RunResponse, ToolSummary
from agent_hub.tasks import run_task

app = FastAPI(title="niuma-cheng-ai", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "niuma-cheng-ai"}


@app.post("/v1/runs/news-l1", response_model=RunResponse)
def run_news_l1(
    inp: L1Input, client: AIClient = Depends(get_ai_client)
) -> RunResponse:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    start = time.monotonic()
    try:
        result = run_task("news-l1", run_id, inp, client=client)
    except Exception as exc:  # noqa: BLE001 — 入口兜底，未预期异常统一转失败响应
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResponse(
            run_id=run_id,
            status="failed",
            elapsed_ms=elapsed,
            tool_summary=ToolSummary(),
            error=f"{type(exc).__name__}",
        )

    elapsed = int((time.monotonic() - start) * 1000)
    if result.output is None:
        return RunResponse(
            run_id=run_id,
            status="failed",
            elapsed_ms=elapsed,
            tool_summary=result.tool_summary,
            error=result.error or "processing failed",
        )
    return RunResponse(
        run_id=run_id,
        status="succeeded",
        elapsed_ms=elapsed,
        tool_summary=result.tool_summary,
        output=result.output,
    )
