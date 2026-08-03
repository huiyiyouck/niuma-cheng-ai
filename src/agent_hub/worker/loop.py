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


def _error_kind_of(source, exc: BaseException) -> tuple[str, bool]:
    """异常 → `(error_kind, 是否计入判死)`（CN-010 变更 7）。

    **这个函数此前不是死代码，是写了没接上的分类器**——实现 R1 Review 按
    「全仓零引用」把它判成死代码建议删除，而零引用只能证明它现在没用，不能
    证明它不该有用。两者的正确处置相反：死代码该删，未接上的该接上。

    `MappingError` 由本层判（它是 worker 层自己的类型）；驱动异常一律交
    `source.classify_error` —— worker 不 `import psycopg`（AC-2.2）。

    **只有 DB 类计入判死**：`run_task` 内部的代码 bug、未注册的 source type
    同样会穿透主循环，把它们计进去意味着**十几条同型毒数据就能杀死 worker，
    而 `dead_reason` 写的是 DB 故障**，排查从第一步就走错方向。
    """
    if isinstance(exc, MappingError):
        return "mapping_error", False
    kind, _ = source.classify_error(exc)
    return kind, kind == "db_error"


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
        outcome = await _commit_with_retry(source, item, payload, settings, slog)
        if outcome == "ok":
            state.consecutive_writeback_failures = 0
            slog.step("writeback", "ok", budget_remaining_ms=budget.remaining_ms())
        elif outcome == "gave_up_retryable":
            # 只有环境性失败才计数：它意味着「谁来都写不进」，下一条同样会失败
            state.consecutive_writeback_failures += 1
        # gave_up_deterministic 不计数——那是这一条数据自己的问题，不该拖垮 worker
    finally:
        state.end_item()


def _provider_of(output: L1Output) -> str | None:
    for tag in output.tags.processing:
        if tag.startswith("llm:"):
            return tag[4:]
    return None


async def _commit_with_retry(source, item, payload, settings: WorkerSettings,
                             slog: StepLogger) -> str:
    """写回失败的有限重试（§4.6，设计 R1 Developer 问题 6；CN-010 变更 1/6）。

    此时结果已经花掉整条预算 + 一次完整 LLM 调用（含费用），而写回事务本身
    是毫秒级的——因为一次可能只持续几毫秒的连接抖动就整个丢弃、并让该条目
    再占用队列到卡死回收，与「高可靠」不符。**重试在 ItemBudget 之外**：
    结果已产出，不再受单条预算约束。

    **两处按 CN-010 改**：

    1. **耗尽后不再向上抛**，改为返回结果——原实现抛异常会杀死整个 worker，
       而 §4.6/§4.7 早写明语义是「放弃这一条、worker 继续跑」；
    2. **区分确定性错误**——§4.6 明确「仅对可重试的 PG 错误类重试；确定性
       错误（约束冲突、权限拒绝）不重试」，而原实现是 `except Exception`
       无差别重试。这处偏离在实现 R1 Review 中被漏报，由 Developer 末票
       中① 引出。

    返回三态而非布尔：`ok` / `gave_up_retryable` / `gave_up_deterministic`。
    **后两者必须可区分**——前者意味着「谁来都写不进」，是环境故障、要计入
    判死；后者只是这一条数据自己有问题，其他条目照常，计进去就是误伤。
    """
    attempts = settings.writeback_retry + 1
    for i in range(attempts):
        try:
            await source.commit_success(item, payload)
            return "ok"
        except Exception as exc:  # noqa: BLE001 — CancelledError 是 BaseException，不会被吞
            kind, retryable = source.classify_error(exc)
            if not retryable:
                # 确定性错误：重试多少次都是同样结果，直接判这一条失败
                slog.step("writeback", "failed", error_kind=kind,
                          error_message=redact(exc), deterministic=True)
                await source.mark_failed(item, error_kind=kind,
                                         message=redact(exc), retryable=False)
                return "gave_up_deterministic"
            if i == attempts - 1:
                slog.step("writeback", "failed", error_kind=kind,
                          error_message=redact(exc))
                # 条目保持 running/processing，走 §4.7 已定的「由自愈或对方回收」
                return "gave_up_retryable"
            slog.step("writeback", "retry", error_kind=kind,
                      error_message=redact(exc), attempt=i + 1)
            await asyncio.sleep(settings.writeback_retry_delay_ms / 1000)
    return "gave_up_retryable"  # 兜底：attempts ≥ 1 时不可达


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

    **每轮包一层异常边界**（CN-010 变更 1）：原实现里 `fetch_batch` 的异常
    直接穿透主循环 → worker 协程死亡 → `/health` 503，而 `dead` 在 v0.2 **没有
    任何自动消费方**（`Restart=on-failure` 只看进程退出码，协程死了进程还活着），
    只能靠人工 curl 发现。claim 每 15s 一次、是全链路最高频的 DB 操作且一次
    重试都没有，PG 例行重启 / 网络闪断 / `PoolTimeout` 都会走到这里。

    这也消除了一处口径不一致：§4.1 早已定过「启动自愈失败**不阻止启动**，
    可用性优先」，理由正是「失败最可能的原因是 DB 短暂抖动」——同一个原因
    在启动期判「不该拦」、运行期却判「直接死」。
    """
    while state.is_running:
        # 判死检查放在 try **之前**：放在 except 里会被自己捕获，放在轮末则
        # 空队列的 continue 会绕过它——写回连败达阈值后若队列恰好空了，就
        # 永远不判死。
        if state.consecutive_writeback_failures >= settings.writeback_failure_limit:
            raise RuntimeError(
                f"writeback failed {state.consecutive_writeback_failures} times in a row"
            )

        try:
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
                                state.consecutive_empty_polls * settings.poll_interval_ms / 60000,
                                1,
                            ),
                        }},
                    )
                state.consecutive_db_failures = 0
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
            state.consecutive_db_failures = 0        # 任一轮走完即清零
        except Exception as exc:  # noqa: BLE001 — CancelledError 是 BaseException，优雅停机靠它穿透
            kind, counts = _error_kind_of(source, exc)
            if counts:
                state.consecutive_db_failures += 1
            log.error(
                "loop_iteration_failed",
                extra={"fields": {
                    "step": "loop", "status": "failed", "error_kind": kind,
                    "error_message": redact(exc),
                    # `consecutive` 是 PM 定的验收要求：状态位只有当下值，
                    # 日志才有历史与时间线，两者不互替
                    "consecutive": state.consecutive_db_failures,
                    "counts_toward_dead": counts,
                }},
            )
            if counts and state.consecutive_db_failures >= settings.loop_failure_limit:
                raise
            await sleep_interruptible(settings.poll_interval_ms, stop)
