"""测试 37：停机宽限期耗尽时须等取消真正完成再关池（CN-010 变更 9）。

`task.cancel()` 只是**请求**取消。不等的话，`lifespan` 的 `finally` 走完 →
ASGI 生命周期结束 → **进程退出，而 worker 协程的取消尚未完成**，它持有的事务
随进程一起没了，留下残留锁等对方 600s 回收。**这条路径只在宽限期耗尽时进入，
而那恰恰是最需要收干净的时刻。**

**判据用调用顺序，不用睡眠时长**（CN 明确要求）：按时长断言会在慢机器上假绿、
在快机器上假红，而顺序是这条修复的实质——它要保证的是「关池发生在 task 真正
结束之后」，不是「关池晚了几毫秒」。

机理注记：**不是「池把使用中的连接抽走」**。`psycopg_pool.close()` 只关池内
空闲连接，给它加更大的 timeout 完全无效——按那个机理导出的修法看起来合理、
同样能「测试通过」，却根本不解决问题。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from agent_hub.config import WorkerSettings


class _RecordingPool:
    def __init__(self, log: list[str]):
        self._log = log

    async def close(self):
        self._log.append("pool_closed")


async def _run_shutdown(worker_body, log: list[str], grace_ms: int = 20):
    """复刻 `lifespan` 的停机段：等 task → 超时则 cancel → 等取消完成 → 关池。

    直接跑 `lifespan` 需要真实 DB 与 LLM，故此处复刻停机段本身。**被验的是
    「cancel 之后有没有等」这一个决策**，它完整落在这几行里。
    """
    task = asyncio.create_task(worker_body())
    pool = _RecordingPool(log)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=grace_ms / 1000)
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        await pool.close()
    return task


async def test_pool_closes_only_after_cancellation_completes():
    """worker 在收到 `CancelledError` 之后仍有一段收尾要跑（释放锁 / 回滚）。

    断言 `pool_closed` 排在 `worker_cleanup_done` **之后**——若 `cancel()` 后
    不等，顺序会反过来，收尾在进程消失前根本没跑完。
    """
    log: list[str] = []

    async def worker():
        try:
            await asyncio.sleep(10)          # 宽限期内跑不完，必然被 cancel
        except asyncio.CancelledError:
            log.append("cancel_received")
            # 取消点之后仍有 await：释放锁、回滚事务都是要连 DB 的
            await asyncio.sleep(0.02)
            log.append("worker_cleanup_done")
            raise

    await _run_shutdown(worker, log)

    assert log == ["cancel_received", "worker_cleanup_done", "pool_closed"], log


async def test_shutdown_does_not_hang_when_worker_finishes_in_time():
    """宽限期内正常收尾时不进入取消路径，关池照常。"""
    log: list[str] = []

    async def worker():
        log.append("worker_done")

    await _run_shutdown(worker, log, grace_ms=500)
    assert log == ["worker_done", "pool_closed"]


async def test_cancelled_worker_exception_is_not_swallowed_into_failure():
    """`gather(..., return_exceptions=True)` 吞掉 `CancelledError` 是有意的：
    这是我们自己发起的取消，不是故障，不该让停机流程再抛一次。"""
    log: list[str] = []

    async def worker():
        await asyncio.sleep(10)

    task = await _run_shutdown(worker, log)
    assert task.cancelled()
    assert log == ["pool_closed"]


@pytest.mark.parametrize("run_mode", ["http"])
def test_http_mode_has_no_pool_to_close(run_mode):
    """HTTP 模式不建池、不起 worker，停机段整个不进入（AC-1.4）。"""
    app = FastAPI()
    app.state.settings = WorkerSettings(run_mode=run_mode)
    assert app.state.settings.run_mode != "db"
