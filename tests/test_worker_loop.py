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

    def __init__(self, batches=None, commit_fails=0):
        self._batches = list(batches or [])
        self.committed, self.failed, self.released = [], [], []
        self._commit_fails = commit_fails
        self.commit_attempts = 0

    async def fetch_batch(self, n):
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
    source = FakeSource(commit_fails=99)
    settings = WorkerSettings(run_mode="db", writeback_retry=1, writeback_retry_delay_ms=1)
    state = WorkerState(lock_token="w#1")
    with pytest.raises(RuntimeError):
        await process_one(source, DbL1Mapper(), _item(), state, settings,
                          client=FakeClient(), tools=NullTools())
    assert source.commit_attempts == 2
    assert state.in_flight == 0          # finally 必须执行


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
