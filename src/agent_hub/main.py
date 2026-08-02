"""niuma-cheng-ai · AI 处理中枢 — FastAPI 入口。

新闻平台（niuma-cheng-xiaobao, Node.js）通过 HTTP 调用本服务处理新闻 L1。
对外契约保持 news-l1 v1 不变：`POST /v1/runs/news-l1`，内部按 task registry 分发。
降级 / 失败语义对齐 AC-6：部分可用 = succeeded；完全不可用 = failed + output=null。
"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from agent_hub.config import load_and_validate_worker_settings
from agent_hub.health import build_health
from agent_hub.llm.client import AIClient, get_ai_client, build_ai_client
from agent_hub.obs.logging import init_logging, redact
from agent_hub.schemas import L1Input, RunResponse, ToolSummary
from agent_hub.tasks import run_task
from agent_hub.tools.base import DefaultNewsTools, NewsTools, get_news_tools
from agent_hub.worker.state import WorkerState, make_lock_token

log = logging.getLogger("agent_hub")


def _on_worker_done(state: WorkerState, task: asyncio.Task) -> None:
    """AC-9.3「worker 生死」的实现核心。

    **必须取出 `task.exception()`**：worker 若以 `asyncio.create_task` 跑在
    同一 event loop 上，其未捕获异常**不会终止进程、不会打断 loop**——只在
    task 被 gc 且异常从未取出时于 stderr 打一行
    `Task exception was never retrieved`。此时 worker 已死，而进程、HTTP、
    `mode` 全部正常，**探针会完整地报告「健康」**，托管层永远不会重启它。
    """
    if task.cancelled():
        state.mark_dead("cancelled")
        return
    exc = task.exception()
    if exc is not None:
        log.error(
            "worker_loop_crashed",
            extra={"fields": {"step": "worker", "status": "failed",
                              "error_kind": "server_error", "error_message": redact(exc)}},
        )
        state.mark_dead(redact(exc))
    else:
        state.mark_stopped()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """进程启动与 worker 托管（AC-1、AC-9.3 / 设计 §4.1）。"""
    settings = app.state.settings
    init_logging()

    if settings.run_mode != "db":
        # HTTP 模式：不建连接池、不起 worker，端点行为与 v0.1 等价（AC-1.1）
        yield
        return

    # 延迟导入：HTTP 模式不需要 psycopg
    from agent_hub.sources.db.pool import create_pool
    from agent_hub.sources.db.source import DbPullSource
    from agent_hub.sources.db.mapper import DbL1Mapper
    from agent_hub.worker.loop import worker_loop

    state = WorkerState(lock_token=make_lock_token(settings.worker_id))
    app.state.worker = state
    pool = await create_pool(settings)
    source = DbPullSource(pool, settings, state.lock_token)

    # 启动自愈：失败**不阻止启动**（DevOps 设计 R1 中③——可用性优先），
    # 但须在 /health 暴露，否则残留锁会静默等对方的回收阈值
    try:
        reclaimed = await source.reclaim_own_stale_locks()
        if reclaimed:
            log.info("self_heal_reclaimed",
                     extra={"fields": {"step": "startup", "status": "ok", "count": reclaimed}})
    except Exception as exc:  # noqa: BLE001
        state.self_heal_failed = True
        log.error("self_heal_failed",
                  extra={"fields": {"step": "startup", "status": "failed",
                                    "error_kind": "db_error", "error_message": redact(exc)}})

    stop = asyncio.Event()
    task = asyncio.create_task(
        worker_loop(source, DbL1Mapper(), state, settings, stop,
                    client=build_ai_client(), tools=DefaultNewsTools())
    )
    task.add_done_callback(lambda t: _on_worker_done(state, t))

    yield

    # 优雅停机：停止新 claim → 处理完当前条目 → 释放锁 → 退出（AC-5.7）
    state.request_stop()
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=settings.shutdown_grace_ms / 1000)
    except asyncio.TimeoutError:
        log.error("shutdown_grace_exceeded",
                  extra={"fields": {"step": "shutdown", "status": "failed",
                                    "grace_ms": settings.shutdown_grace_ms}})
        task.cancel()
    finally:
        await pool.close()


app = FastAPI(title="niuma-cheng-ai", version="0.2.0", lifespan=lifespan)

# 进程级模式开关（AC-1.4）。配置门禁在此执行：任一不变式不满足即拒绝启动。
app.state.settings = load_and_validate_worker_settings()
app.state.worker = None


@app.get("/health")
def health() -> JSONResponse:
    """三重探活（AC-9.3）。不做任何 IO——它是 async 彻底性的运行时闸门。"""
    body, code = build_health(app.state.settings, app.state.worker)
    return JSONResponse(content=body, status_code=code)


@app.post("/v1/runs/news-l1", response_model=RunResponse)
async def run_news_l1(
    inp: L1Input,
    client: AIClient = Depends(get_ai_client),
    tools: NewsTools = Depends(get_news_tools),
) -> RunResponse:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    start = time.monotonic()
    try:
        result = await run_task("news-l1", run_id, inp, client=client, tools=tools)
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
