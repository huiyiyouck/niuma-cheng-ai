"""worker 主循环：claim → 处理 → 写回 → 释放（设计 §4.2、§4.4-4.8）。

**只有本模块知道「轮询」这件事**——处理核心对它零依赖（§1.3 依赖方向）。

三段式事务边界（O-6）：claim 短事务 → 处理**无事务、无连接** → 写回短事务。
LLM 调用（240s 量级）绝不持有数据库事务或连接。
"""
from __future__ import annotations

import asyncio
import logging

from agent_hub.budget import ItemBudget
from agent_hub.config import WorkerSettings
from agent_hub.obs.logging import StepLogger, redact
from agent_hub.schemas import L1Output
from agent_hub.sources.base import ClaimedItem, MappingError, PullSource
from agent_hub.tasks import run_task
from agent_hub.worker.state import WorkerState

log = logging.getLogger("agent_hub.worker")


async def sleep_interruptible(ms: int, stop: asyncio.Event) -> None:
    """空队列时等待，但**可被停机信号立即打断**。

    直接 `asyncio.sleep(15s)` 会让 SIGTERM 最多白等一个轮询间隔——宽限期是
    按处理耗时算的，不该被空转等待吃掉。
    """
    try:
        await asyncio.wait_for(stop.wait(), timeout=ms / 1000)
    except asyncio.TimeoutError:
        pass  # 正常：等满间隔，没有收到停机信号


def _error_kind_of(exc: BaseException) -> str:
    if isinstance(exc, MappingError):
        return "mapping_error"
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    return "server_error"


async def process_one(
    source: PullSource,
    mapper,
    item: ClaimedItem,
    state: WorkerState,
    settings: WorkerSettings,
    *,
    client,
    tools=None,
) -> None:
    """处理单条：入向映射 → 处理 → 出向映射 → 写回（§4.4-4.7）。"""
    slog = StepLogger(
        run_id=f"run_{item.task_id.hex[:12]}",
        raw_item_id=str(item.record.raw_item_id),
        task_id=str(item.task_id),
    )
    state.begin_item()
    budget = ItemBudget(total_ms=settings.item_budget_ms, min_segment_ms=settings.min_segment_ms)

    try:
        # 1) 入向映射——失败不可重试：同一份脏数据重试不会变干净（AC-2.5）
        try:
            l1_input = mapper.to_l1_input(item.record)
        except MappingError as exc:
            slog.step("map_in", "failed", error_kind="mapping_error",
                      error_message=redact(exc.message))
            await source.mark_failed(item, error_kind="mapping_error",
                                     message=redact(exc.message), retryable=False)
            return
        slog.step("map_in", "ok", budget_remaining_ms=budget.remaining_ms())

        # 2) 处理——无事务、无连接
        result = await run_task("news-l1", slog._base["run_id"], l1_input,
                                client=client, tools=tools, budget=budget)

        if result.output is None:
            # 预算耗尽 / LLM 全 provider 失败 / 工具层不可用——均可重试
            kind = "budget_exhausted" if budget.exhausted() else "server_error"
            slog.step("llm_process", "failed", error_kind=kind,
                      error_message=redact(result.error or ""),
                      budget_remaining_ms=budget.remaining_ms())
            await source.mark_failed(item, error_kind=kind,
                                     message=redact(result.error or ""), retryable=True)
            return

        output: L1Output = result.output
        slog.degradations(_provider_of(output), list(result.degradations))

        # 3) 出向映射——失败可重试（AC-2.5）
        try:
            payload = mapper.from_l1_output(output, item)
        except MappingError as exc:
            slog.step("map_out", "failed", error_kind="mapping_error",
                      error_message=redact(exc.message))
            await source.mark_failed(item, error_kind="mapping_error",
                                     message=redact(exc.message), retryable=True)
            return

        # 4) 写回——短事务 + 瞬时故障有限重试（§4.6）
        await _commit_with_retry(source, item, payload, settings, slog)
        slog.step("writeback", "ok", budget_remaining_ms=budget.remaining_ms())
    finally:
        state.end_item()


def _provider_of(output: L1Output) -> str | None:
    for tag in output.tags.processing:
        if tag.startswith("llm:"):
            return tag[4:]
    return None


async def _commit_with_retry(source, item, payload, settings: WorkerSettings,
                             slog: StepLogger) -> None:
    """写回失败的有限重试（§4.6，设计 R1 Developer 问题 6）。

    此时结果已经花掉整条预算 + 一次完整 LLM 调用（含费用），而写回事务本身
    是毫秒级的——因为一次可能只持续几毫秒的连接抖动就整个丢弃、并让该条目
    再占用队列到卡死回收，与「高可靠」不符。**重试在 ItemBudget 之外**：
    结果已产出，不再受单条预算约束。
    """
    attempts = settings.writeback_retry + 1
    for i in range(attempts):
        try:
            await source.commit_success(item, payload)
            return
        except Exception as exc:  # noqa: BLE001 — CancelledError 是 BaseException，不会被吞
            if i == attempts - 1:
                slog.step("writeback", "failed", error_kind="db_error",
                          error_message=redact(exc))
                raise
            slog.step("writeback", "retry", error_kind="db_error",
                      error_message=redact(exc), attempt=i + 1)
            await asyncio.sleep(settings.writeback_retry_delay_ms / 1000)


async def worker_loop(
    source: PullSource,
    mapper,
    state: WorkerState,
    settings: WorkerSettings,
    stop: asyncio.Event,
    *,
    client,
    tools=None,
) -> None:
    """主循环。**取到条目后不 sleep，立即进入下一轮 claim**。

    队列有积压时不浪费轮询间隔，只有空队列才等待——这是 N=1 不损失吞吐的
    前提（ADR-0004）。
    """
    while state.is_running:
        items = await source.fetch_batch(settings.claim_batch_size)
        state.touch_poll(claimed=len(items))

        if not items:
            # 只在跨过阈值时打一次，不刷屏（§2.5 空转可观测性）
            if state.consecutive_empty_polls == settings.empty_poll_warn:
                log.warning(
                    "queue_idle",
                    extra={"fields": {
                        "step": "claim", "status": "idle",
                        "consecutive_empty_polls": state.consecutive_empty_polls,
                        "minutes": round(
                            state.consecutive_empty_polls * settings.poll_interval_ms / 60000, 1
                        ),
                    }},
                )
            await sleep_interruptible(settings.poll_interval_ms, stop)
            continue

        for item in items:
            if not state.is_running:
                # 停机时不再开始新条目：**主动释放**而非标记失败——它既非成功
                # 也非失败，走 mark_failed 会污染 attempt 与 last_error_kind，
                # 让一次正常停机在对方侧看起来像一次处理失败（§4.7）
                await source.release(item)
                continue
            await process_one(source, mapper, item, state, settings,
                              client=client, tools=tools)
