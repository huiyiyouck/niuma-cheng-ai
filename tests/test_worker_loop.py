"""worker 主循环（设计 §4.2、§4.7、§8 测试 21）。

用 fake `PullSource` 覆盖循环编排与失败分类；claim/写回的**真实事务语义**
（`SKIP LOCKED`、回滚）mock 测不出，归真实库集成测试（测试 6/7/15/16）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_hub.config import WorkerSettings
from agent_hub.sources.base import ClaimedItem, MappingError, SourceRecord
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.worker.loop import process_one, worker_loop
from agent_hub.worker.state import WorkerState
from tests.test_news_l1 import FakeClient, NullTools

_SETTINGS = WorkerSettings(run_mode="db", poll_interval_ms=10000, empty_poll_warn=2)


def _record(**over) -> SourceRecord:
    base = dict(
        raw_item_id=uuid4(), source_type="x_twitter", source_identity="acct",
        content={"text": "一条推文。"}, source_item_url="https://x.com/a/status/1",
        source_domain_tags=["AI"], published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    base.update(over)
    return SourceRecord(**base)


def _item(record=None) -> ClaimedItem:
    return ClaimedItem(task_id=uuid4(), record=record or _record(), attempt=1,
                       max_attempts=3, lock_token="w#1", claimed_at=0.0)


class FakeSource:
    """记录各操作调用的 fake PullSource。"""

    def __init__(self, batches=None, commit_fails=0, *,
                 error_kind="db_error", retryable=True, claim_exc=None):
        self._batches = list(batches or [])
        self.committed, self.failed, self.released = [], [], []
        self._commit_fails = commit_fails
        self.commit_attempts = 0
        self._error_kind = error_kind
        self._retryable = retryable
        self._claim_exc = list(claim_exc or [])
        self.claim_attempts = 0

    def classify_error(self, exc):
        """驱动异常分类由数据源层给出——worker 不 import psycopg（CN-010 变更 6/7）。"""
        return self._error_kind, self._retryable

    async def fetch_batch(self, n):
        self.claim_attempts += 1
        if self._claim_exc:
            exc = self._claim_exc.pop(0)
            if exc is not None:
                raise exc
        return self._batches.pop(0) if self._batches else []

    async def commit_success(self, item, payload):
        self.commit_attempts += 1
        if self.commit_attempts <= self._commit_fails:
            raise RuntimeError("connection reset")
        self.committed.append((item, payload))

    async def mark_failed(self, item, *, error_kind, message, retryable):
        self.failed.append({"item": item, "error_kind": error_kind, "retryable": retryable})

    async def release(self, item):
        self.released.append(item)

    async def reclaim_own_stale_locks(self):
        return 0


async def _process(source, item, mapper=None, settings=_SETTINGS):
    state = WorkerState(lock_token="w#1")
    await process_one(source, mapper or DbL1Mapper(), item, state, settings,
                      client=FakeClient(), tools=NullTools())
    return state


# --- 正常路径 ---
async def test_success_commits_once():
    source = FakeSource()
    state = await _process(source, _item())
    assert len(source.committed) == 1
    assert source.failed == []
    assert state.in_flight == 0          # in_flight 必须归零，否则探活永远显示在途


# --- 失败分类（§4.7）---
async def test_inbound_mapping_failure_is_not_retryable():
    """入向映射失败不可重试——同一份脏数据重试不会变干净（AC-2.5）。"""
    source = FakeSource()
    await _process(source, _item(_record(source_type="telegram")))  # 未注册的 source type
    assert len(source.failed) == 1
    assert source.failed[0]["retryable"] is False
    assert source.failed[0]["error_kind"] == "mapping_error"
    assert source.committed == []


async def test_outbound_mapping_failure_is_retryable():
    class BadOutMapper(DbL1Mapper):
        def from_l1_output(self, output, ctx):
            raise MappingError("server_error", "boom")

    source = FakeSource()
    await _process(source, _item(), mapper=BadOutMapper())
    assert source.failed[0]["retryable"] is True
    assert source.failed[0]["error_kind"] == "mapping_error"


async def test_llm_failure_is_retryable():
    source = FakeSource()
    state = WorkerState(lock_token="w#1")
    await process_one(source, DbL1Mapper(), _item(), state, _SETTINGS,
                      client=FakeClient(exc=RuntimeError("all providers failed")),
                      tools=NullTools())
    assert source.failed[0]["retryable"] is True
    assert source.committed == []


# --- 写回有限重试（§4.6）---
async def test_writeback_retries_transient_failure():
    """瞬时故障重试成功：结果已花掉整条预算 + 一次 LLM 调用，不该因几毫秒的
    连接抖动整个丢弃。"""
    source = FakeSource(commit_fails=2)          # 前两次失败，第三次成功
    settings = WorkerSettings(run_mode="db", writeback_retry=2, writeback_retry_delay_ms=1)
    state = WorkerState(lock_token="w#1")
    await process_one(source, DbL1Mapper(), _item(), state, settings,
                      client=FakeClient(), tools=NullTools())
    assert source.commit_attempts == 3
    assert len(source.committed) == 1


async def test_writeback_gives_up_after_retries():
    """耗尽后**不抛出**——放弃这一条、worker 继续跑（CN-010 变更 1）。

    这条断言此前是 `pytest.raises(RuntimeError)`，把「一次写回失败杀死整个
    worker」固化成了验收标准，而 §4.6/§4.7 早写明语义是「条目保持 running，
    由自愈或对方回收」。**设计、实现、测试三层各漏一半，测试这层还把错的那
    半锁死了。**
    """
    source = FakeSource(commit_fails=99)
    settings = WorkerSettings(run_mode="db", writeback_retry=1, writeback_retry_delay_ms=1)
    state = WorkerState(lock_token="w#1")
    await process_one(source, DbL1Mapper(), _item(), state, settings,
                      client=FakeClient(), tools=NullTools())
    assert source.commit_attempts == 2
    assert source.committed == []
    assert source.failed == []           # 可重试类耗尽：条目保持 running，不标失败
    assert state.in_flight == 0          # finally 必须执行
    assert state.consecutive_writeback_failures == 1


async def test_deterministic_writeback_error_does_not_retry_or_count():
    """确定性错误（约束冲突 / 权限拒绝）不重试、不计判死（CN-010 变更 6③）。

    §4.6 早写明「仅对可重试的 PG 错误类重试」，而原实现是 `except Exception`
    无差别重试——**这处偏离在实现 R1 Review 中被漏报**。重试它没有意义：
    同一份数据重试多少次都是同样结果，只是白烧 attempt 和算力。
    """
    source = FakeSource(commit_fails=99, retryable=False, error_kind="db_error")
    settings = WorkerSettings(run_mode="db", writeback_retry=2, writeback_retry_delay_ms=1)
    state = WorkerState(lock_token="w#1")
    await process_one(source, DbL1Mapper(), _item(), state, settings,
                      client=FakeClient(), tools=NullTools())
    assert source.commit_attempts == 1                      # 一次就放弃，不重试
    assert len(source.failed) == 1                          # 该条走 mark_failed
    assert source.failed[0]["retryable"] is False
    assert state.consecutive_writeback_failures == 0        # 数据问题不该拖垮 worker


# --- 主循环编排 ---
async def test_loop_stops_and_releases_unstarted_items():
    """停机时**主动释放**而非标记失败（测试 21 / 设计 R1 我提的问题 1）。

    走 mark_failed 会污染 attempt 与 last_error_kind——一次正常停机在对方侧
    看起来像一次处理失败，并白白消耗一次重试配额。
    """
    items = [_item(), _item()]
    source = FakeSource(batches=[items])
    state = WorkerState(lock_token="w#1")
    state.request_stop()                 # 进入循环前就已收到停机信号
    stop = asyncio.Event()
    stop.set()

    settings = WorkerSettings(run_mode="db", claim_batch_size=2)
    await worker_loop(source, DbL1Mapper(), state, settings, stop,
                      client=FakeClient(), tools=NullTools())

    assert source.released == []         # 已 stopping：循环体不再执行
    assert source.committed == []
    assert source.failed == []


async def test_loop_releases_when_stop_arrives_mid_batch():
    """批中途收到停机：剩余条目走 release，不走失败路径。"""
    items = [_item(), _item()]
    source = FakeSource(batches=[items])
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()

    class StopAfterFirst(DbL1Mapper):
        def to_l1_input(self, record):
            state.request_stop()          # 处理第一条时收到停机信号
            return super().to_l1_input(record)

    settings = WorkerSettings(run_mode="db", claim_batch_size=2)
    await worker_loop(source, StopAfterFirst(), state, settings, stop,
                      client=FakeClient(), tools=NullTools())

    assert len(source.committed) == 1     # 第一条正常完成
    assert len(source.released) == 1      # 第二条被释放
    assert source.failed == []            # 释放不是失败


async def test_empty_queue_counts_and_sleeps_interruptibly():
    """空队列时等待可被停机打断——否则 SIGTERM 最多白等一个轮询间隔。"""
    source = FakeSource(batches=[[], [], []])
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.05)
        state.request_stop()
        stop.set()

    settings = WorkerSettings(run_mode="db", poll_interval_ms=10000, empty_poll_warn=2)
    started = asyncio.get_event_loop().time()
    await asyncio.gather(
        worker_loop(source, DbL1Mapper(), state, settings, stop,
                    client=FakeClient(), tools=NullTools()),
        stop_soon(),
    )
    elapsed = asyncio.get_event_loop().time() - started

    assert elapsed < 1.0, f"停机未打断 sleep，耗时 {elapsed:.2f}s（轮询间隔 10s）"
    assert state.consecutive_empty_polls >= 1


# --- 测试 29：主循环异常边界（CN-010 变更 1）---
async def test_loop_survives_transient_claim_failures():
    """一次 DB 抖动不该杀死 worker。

    改前：`fetch_batch` 的异常直接穿透 → 协程死亡 → `/health` 503，而 `dead`
    在 v0.2 **没有任何自动消费方**（`Restart=on-failure` 只看进程退出码，协程
    死了进程还活着），只能靠人工 curl 发现。而 claim 每 15s 一次、是全链路最
    高频的 DB 操作，**且一次重试都没有**。
    """
    item = _item()
    source = FakeSource(
        batches=[[item]],
        claim_exc=[RuntimeError("db down"), RuntimeError("db down"), None],
    )
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()

    class StopAfterFirst(DbL1Mapper):
        def to_l1_input(self, record):
            state.request_stop()
            stop.set()
            return super().to_l1_input(record)

    settings = WorkerSettings(run_mode="db", poll_interval_ms=1, loop_failure_limit=5)
    await worker_loop(source, StopAfterFirst(), state, settings, stop,
                      client=FakeClient(), tools=NullTools())

    assert len(source.committed) == 1        # 前两次失败后仍能正常处理
    assert state.consecutive_db_failures == 0  # 成功一轮即清零
    assert state.phase == "stopping"          # 没被判死


async def test_loop_dies_after_consecutive_db_failures():
    """持续故障仍要判死——DB 真的没了（口令失效 / 库被删）时空转没有意义。

    连着验完整链路到 `phase == "dead"`：worker 协程的异常**不会终止进程**，
    必须由 `_on_worker_done` 取出 `task.exception()` 才会转成 `dead` → 503。
    """
    from agent_hub.main import _on_worker_done

    source = FakeSource(claim_exc=[RuntimeError("db down")] * 10)
    state = WorkerState(lock_token="w#1")
    settings = WorkerSettings(run_mode="db", poll_interval_ms=1, loop_failure_limit=3)

    task = asyncio.create_task(
        worker_loop(source, DbL1Mapper(), state, settings, asyncio.Event(),
                    client=FakeClient(), tools=NullTools())
    )
    task.add_done_callback(lambda t: _on_worker_done(state, t))
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)                   # 让 done_callback 跑完

    assert state.consecutive_db_failures == 3
    assert state.phase == "dead"


# --- 测试 34：写回连续失败可见且判死（CN-010 变更 6）---
async def test_writeback_failures_are_counted_separately_and_fatal():
    """DB「可达但写不进」：claim 一直成功，写回一直失败。

    **这正是合并计数会漏掉的场景**——claim 成功就把 `consecutive_db_failures`
    清零，于是那个计数**恒为 0**，而队列正在被逐条烧成 `final_failed`：worker
    永远 running、`/health` 200、专为暴露「活着但在挣扎」而加的字段显示一切
    正常。断言 `consecutive_db_failures == 0` 就是在钉死这一点。
    """
    source = FakeSource(batches=[[_item()] for _ in range(6)], commit_fails=99)
    state = WorkerState(lock_token="w#1")
    settings = WorkerSettings(
        run_mode="db", poll_interval_ms=1, writeback_retry=0,
        writeback_retry_delay_ms=1, writeback_failure_limit=3,
    )
    with pytest.raises(RuntimeError, match="writeback"):
        await worker_loop(source, DbL1Mapper(), state, settings, asyncio.Event(),
                          client=FakeClient(), tools=NullTools())

    assert state.consecutive_writeback_failures == 3
    assert state.consecutive_db_failures == 0      # ← 合并计数就会漏报的那个 0
    assert source.committed == []


# --- 测试 35：主循环 error_kind 按类型分流（CN-010 变更 7）---
async def test_non_db_exception_neither_mislabeled_nor_counted():
    """非 DB 异常（处理核心 bug / 未注册 source type）同样穿透主循环。

    把它们标成 `db_error` 并计入判死的代价：运维照日志查 DB 会查到「一切
    正常」，而十几条同型毒数据就能杀死 worker、`dead_reason` 却写着 DB 故障
    ——排查从第一步就走错方向。此处 `loop_failure_limit=2` 而失败 5 次，
    若计数了必然判死。
    """
    source = FakeSource(
        claim_exc=[RuntimeError("graph bug")] * 5,
        error_kind="unexpected", retryable=False,
    )
    state = WorkerState(lock_token="w#1")
    stop = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.05)
        state.request_stop()
        stop.set()

    settings = WorkerSettings(run_mode="db", poll_interval_ms=1, loop_failure_limit=2)
    await asyncio.gather(
        worker_loop(source, DbL1Mapper(), state, settings, stop,
                    client=FakeClient(), tools=NullTools()),
        stop_soon(),
    )

    assert source.claim_attempts >= 3              # 确实反复失败过
    assert state.consecutive_db_failures == 0      # 一次都没计入判死
    assert state.phase == "stopping"               # 没被误判死
