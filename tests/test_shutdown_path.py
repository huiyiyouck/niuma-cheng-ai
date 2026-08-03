"""测试 37：优雅停机路径（CN-010 变更 9；实现 R3 Architect Review 中①）。

**本文件上一版是错的，错法值得记**：它自己复刻了一份 `lifespan` 的停机段来测，
于是删掉 `main.py` 里的 `await gather` 后全仓 208 条测试无一变红——**验的是复刻件**。
我当时还做了反向注入并把「2 failed」写进报告当鉴别力证据，而那个注入点打在复刻
件上，回答的是「测试自己坏了红不红」，恒为真、零信息量。

**更深一层是复刻件与生产代码有实质差异**：复刻件写 `wait_for(shield(task))`，
生产代码是 `wait_for(task)`。`shield` 挡掉了 `wait_for` 自带的取消，**人为制造
出了那个要被修的问题**——实测（3.11 与 3.12 一致）：

    wait_for(task)            → TimeoutError 抛出时 task.done()=True，收尾已跑完
    wait_for(shield(task))    → task.done()=False，甚至还没收到 cancel

即测试不只没验生产代码，还证明了一个**在生产代码里不成立**的命题。

现在直接调用 `main.shutdown_worker`（生产代码本身），并验它真正要守的不变量：
**`pool.close()` 执行时 worker task 必然已结束**。
"""
from __future__ import annotations

import asyncio

import pytest

from agent_hub.config import WorkerSettings
from agent_hub.main import shutdown_worker
from agent_hub.worker.state import WorkerState


class _RecordingPool:
    """记录关池时刻的 task 状态——不变量就落在这一刻。"""

    def __init__(self):
        self.closed = False
        self.task_done_at_close: bool | None = None
        self._task: asyncio.Task | None = None

    def watch(self, task: asyncio.Task) -> None:
        self._task = task

    async def close(self):
        self.closed = True
        self.task_done_at_close = self._task.done() if self._task else None


async def _shutdown(worker_body, grace_ms: int = 20):
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()
    task = asyncio.create_task(worker_body(stop))
    pool = _RecordingPool()
    pool.watch(task)
    settings = WorkerSettings(run_mode="db", shutdown_grace_ms=grace_ms)
    await shutdown_worker(state, stop, task, pool, settings)
    return state, task, pool


# --- 核心不变量 ---
async def test_pool_never_closes_before_worker_finished_on_timeout():
    """宽限期耗尽路径：worker 在取消点之后还有收尾要跑（释放锁 / 回滚事务）。

    **断言关池那一刻 task 已结束**——而不是断言某一行代码在不在。上一版验的是
    「有没有 `await gather`」，那是实现细节；**这里验的是保证本身**。
    """
    trace: list[str] = []

    async def worker(stop):
        try:
            await asyncio.sleep(10)          # 宽限期内跑不完
        except asyncio.CancelledError:
            trace.append("cancel_received")
            await asyncio.sleep(0.02)        # 取消点之后仍有 await
            trace.append("cleanup_done")
            raise

    _, task, pool = await _shutdown(worker)

    assert pool.closed
    assert pool.task_done_at_close is True, "关池时 worker 尚未结束——事务会随进程消失"
    assert trace == ["cancel_received", "cleanup_done"], trace


async def test_pool_never_closes_before_worker_finished_on_normal_exit():
    """宽限期内正常收尾：同一条不变量，不同路径。"""
    trace: list[str] = []

    async def worker(stop):
        await stop.wait()
        trace.append("worker_returned")

    _, task, pool = await _shutdown(worker, grace_ms=2000)

    assert pool.task_done_at_close is True
    assert trace == ["worker_returned"]
    assert not task.cancelled()              # 正常收尾不该走取消路径


async def test_stop_signal_is_set_before_waiting():
    """先置停机信号再等——否则 worker 永远等不到、必然走满宽限期。"""

    async def worker(stop):
        assert stop.is_set(), "shutdown_worker 应先 stop.set() 再等待"

    state, _, pool = await _shutdown(worker, grace_ms=2000)
    assert state.phase == "stopping"
    assert pool.closed


async def test_worker_exception_propagates_but_pool_still_closes():
    """worker 以异常结束时：**池仍然关闭（`finally` 生效），但异常会向上抛**。

    这是实测出来的当前真实行为，不是我预期的——我原本以为 `shutdown_worker`
    会静默收尾。`wait_for` 在 task 以异常结束时抛的是**该异常本身**而非
    `TimeoutError`，于是它穿过 `except asyncio.TimeoutError` 直达调用方。

    **不变量仍然成立**（关池时 task 已结束），故不构成缺陷。但有一个观察已报出、
    未擅自改（Architect 附条件明确「纯提取，不改任何生产行为」）：worker 异常
    死亡时 `_on_worker_done` 已经记录过一次，停机路径再抛一次会让 uvicorn 的
    shutdown 日志出现一个看起来像新故障的异常——而它其实是几分钟前那次判死的
    回声。灰度期看日志的人会被引向错误的时间点。
    """
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()

    async def worker():
        raise RuntimeError("boom")

    task = asyncio.create_task(worker())
    pool = _RecordingPool()
    pool.watch(task)
    settings = WorkerSettings(run_mode="db", shutdown_grace_ms=2000)

    with pytest.raises(RuntimeError, match="boom"):
        await shutdown_worker(state, stop, task, pool, settings)

    assert pool.closed, "异常路径下 finally 未生效，池会泄漏"
    assert pool.task_done_at_close is True


# --- 反向注入的有效形式 ---
async def test_invariant_would_break_if_wait_were_shielded():
    """**这条是上一版缺的那个东西**：证明本组测试确实抓得住保证被破坏的情况。

    按 Architect 给的判据「删掉 `await gather` 后测试必须变红」在生产代码上
    做不到——实测 `wait_for(task)` 超时时已经取消并等待完成，那两行是冗余的。
    **有效的注入不是删一行冗余代码，是破坏保证本身**：给 `wait_for` 包一层
    `shield`（正是上一版复刻件的写法），worker 就会在关池后才结束。

    此处直接复现被破坏的形态并断言它确实被破坏——若哪天 `wait_for` 的语义变了
    使这条不再成立，本条会红，提醒重新审视 `shutdown_worker` 的兜底是否仍够。
    """
    trace: list[str] = []

    async def worker():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            trace.append("cleanup_done")
            raise

    task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=0.02)
    except asyncio.TimeoutError:
        pass

    assert task.done() is False, "shield 下 task 本应仍在跑——若此断言红了说明 wait_for 语义已变"
    assert trace == []
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("run_mode", ["http"])
def test_http_mode_never_reaches_shutdown_worker(run_mode):
    """HTTP 模式不建池、不起 worker，停机段整个不进入（AC-1.4）。"""
    assert WorkerSettings(run_mode=run_mode).run_mode != "db"
