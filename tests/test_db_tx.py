"""事务级超时与 SQL 契约（设计 §8 测试 25，CN-008 变更 4）。

测试 25② 是本组的要点：**专验「语句级超时挡不住事务超时」**——mock 一个
含多条语句、总耗时超 `tx_timeout` 但**每条都不超 `statement_timeout`** 的
事务，断言在 tx_timeout 处被取消并回滚。这条测试如果不写，CN-008 那次订正
的全部意义在回归中就没有守护。

真实库语义（SKIP LOCKED、GRANT、回滚）mock 测不出，归集成测试
（§8 测试 6/7/15/16/20），需连 `news_test`。
"""
from __future__ import annotations

import asyncio

import pytest

from agent_hub.config import WorkerSettings
from agent_hub.sources.db import sql
from agent_hub.sources.db.pool import build_conninfo, run_tx

_S = WorkerSettings(run_mode="db", db_host="h", db_name="d", db_user="u",
                    db_password="secret-pw", tx_timeout_ms=300,
                    statement_timeout_ms=200, lock_timeout_ms=100)


class _Tx:
    """模拟 `conn.transaction()`：异常时标记回滚。"""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._conn.rolled_back = True
        return False


class _FakeConn:
    def __init__(self, per_statement_s: float):
        self._per = per_statement_s
        self.executed: list[str] = []
        self.rolled_back = False

    async def execute(self, q, params=None):
        await asyncio.sleep(self._per)   # 每条语句都低于 statement_timeout
        self.executed.append(q)
        return self

    async def fetchall(self):
        return []

    def transaction(self):
        return _Tx(self)


class _FakePool:
    """模拟 psycopg_pool 的 async 上下文管理器形状。"""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return _CtxConn(self._conn)


class _CtxConn:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


# --- 测试 25②：语句级超时挡不住事务超时 ---
async def test_transaction_level_timeout_fires_when_no_single_statement_exceeds():
    """三条语句各 150ms（均 < statement_timeout 200ms），合计 450ms > tx 300ms。

    只靠 `statement_timeout` 时数据库侧不会中断任何一条——事务会一路跑完。
    事务级上界**只能由应用层的 asyncio.wait_for 给出**（PG 无内建等价物）。
    """
    conn = _FakeConn(per_statement_s=0.15)
    pool = _FakePool(conn)

    async def _three_statements(c):
        await c.execute("stmt 1")
        await c.execute("stmt 2")
        await c.execute("stmt 3")
        return "done"

    with pytest.raises(asyncio.TimeoutError):
        await run_tx(pool, _S, _three_statements)

    assert len(conn.executed) < 3, "事务应在跑完前被取消"
    assert conn.rolled_back, "超时后必须回滚"


async def test_transaction_within_budget_succeeds():
    conn = _FakeConn(per_statement_s=0.01)
    pool = _FakePool(conn)

    async def _fast(c):
        await c.execute("stmt 1")
        return "ok"

    assert await run_tx(pool, _S, _fast) == "ok"
    assert not conn.rolled_back


async def test_cancellation_propagates_not_swallowed():
    """外部取消（优雅停机）须穿透，不能被当成超时吞掉。

    `CancelledError` 是 `BaseException`；一旦有人在 run_tx 外层写
    `except BaseException`，**超时重试与优雅停机会同时失效**（O-8）。
    """
    conn = _FakeConn(per_statement_s=10)
    pool = _FakePool(conn)

    async def _slow(c):
        await c.execute("slow")

    task = asyncio.create_task(run_tx(pool, _S, _slow))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- 凭据不进日志 / 不拼整串 DSN（AC-6.2 / O-7）---
def test_conninfo_built_from_fields_not_dsn():
    info = build_conninfo(_S)
    assert "host=h" in info and "dbname=d" in info
    assert not info.startswith("postgres"), "不拼整串 DSN——极易被日志/ps/驱动异常整体带出"


def test_redact_hides_password_from_error_text():
    from agent_hub.obs.logging import redact

    msg = f"connection failed: {build_conninfo(_S)}"
    assert "secret-pw" not in redact(msg)


# --- SQL 契约：几处「漏了就静默出错」的约束 ---
def test_writeback_never_mentions_score_total_or_id():
    """不是「写 NULL」，是**根本不提及**——否则 DO UPDATE 会把对方已算好的
    score_total 覆盖成 NULL（O-1 / §2.3）。"""
    assert "score_total" not in sql.WRITEBACK_UPSERT
    assert " id," not in sql.WRITEBACK_UPSERT and "(id" not in sql.WRITEBACK_UPSERT


def test_needs_context_in_both_insert_list_and_do_update_set():
    """占位行由对方在 L0 通过时创建，故走 DO UPDATE 分支是**常态**。

    只加进 INSERT 列清单而漏了 SET，该列会永远保持 NULL 且不报错——与
    CN-009 要修的「列存在但信号永远缺失」完全同型（CN-009 确认时提的落点）。
    """
    body = sql.WRITEBACK_UPSERT
    insert_part, update_part = body.split("DO UPDATE SET")
    assert "needs_context" in insert_part
    assert "needs_context = EXCLUDED.needs_context" in update_part


def test_claim_has_all_three_required_conditions():
    q = sql.CLAIM_SELECT
    assert "run_after <= now()" in q          # 缺它退避完全失效（C-4）
    assert "raw_item_id IS NOT NULL" in q     # 该列 nullable，缺它会越界标他人任务
    assert "ORDER BY priority DESC" in q      # R1→R3 曾整条丢失，队列积压时老条目饿死


def test_claim_increments_l1_attempt_in_same_transaction():
    """与 tasks.attempt 同事务推进——留到写回才加，claim 后崩溃会永久漂移。"""
    assert "l1_attempt = l1_attempt + 1" in sql.CLAIM_MARK_PROCESSING


def test_release_does_not_touch_attempt_or_error():
    """主动释放既非成功也非失败：不动 attempt、不写 last_error。"""
    assert "attempt" not in sql.RELEASE_TASK
    assert "last_error" not in sql.RELEASE_TASK


def test_reclaim_only_matches_own_prefix_and_other_run_token():
    q = sql.RECLAIM_OWN_STALE
    assert "locked_by LIKE" in q and "locked_by <> " in q


@pytest.mark.parametrize("attempt, expected", [(1, 60), (2, 300), (3, 900), (4, 900), (9, 900)])
def test_backoff_clamps_to_last_value(attempt, expected):
    """越界取末值，**禁止取 0**——取 0 即静默退化回「立刻重领」，正是 C-4
    刚修好的问题。对方 max_attempts schema 默认 5 而退避表长 3（C-12）。"""
    assert sql.backoff_for(attempt) == expected
