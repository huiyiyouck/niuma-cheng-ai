"""`classify_error` 的 SQLSTATE 判定（CN-010 变更 6/7，实现 R2 Architect Review 高①）。

**本文件存在的理由是我 R2 那次实测的方法错了。** 那次验了五项——`42501` /
`42P01` / `22P02` / 无 sqlstate / `TimeoutError`——**全是「该判不可重试的判没判对」，
一项都没验「该判可重试的有没有被误判成不可重试」**。而白名单的风险从来不在名单
内，在名单外：漏判的码会被当成确定性错误，一次重试都没有就进终态。

后果链（逐段实查）：

    classify_error → (db_error, False)
      → _commit_with_retry 走 gave_up_deterministic：一次重试都没有
      → mark_failed(retryable=False) → l1_status='final_failed' + tasks.status='failed'
      → 且不计入 consecutive_writeback_failures → 不判死、不告警

即**一条完全正常、已花掉 240s 预算和一次 LLM 调用的数据，因为撞上 PG 重启就被
烧成不可恢复，且没有任何信号**——而 CN-010 变更 1 从头到尾的立论正是「PG 例行
重启会走到这条路径」。
"""
from __future__ import annotations

import asyncio

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from agent_hub.config import WorkerSettings
from agent_hub.sources.db.source import DbPullSource

_SRC = DbPullSource(None, WorkerSettings(), "probe#1")


def _pg_error(sqlstate: str) -> psycopg.Error:
    """按 sqlstate 造真实 psycopg 异常类（`psycopg.errors.lookup` 是官方入口）。"""
    return psycopg.errors.lookup(sqlstate)("boom")


# --- 该判「可重试」的：本组是 R2 漏掉的那一半 ---
@pytest.mark.parametrize(
    "sqlstate, name",
    [
        ("57P01", "admin_shutdown —— PG 主动断开，例行重启就是它"),
        ("57P02", "crash_shutdown"),
        ("57P03", "cannot_connect_now —— 数据库正在启动中"),
        ("53300", "too_many_connections"),
        ("53200", "out_of_memory"),
        ("55P03", "lock_not_available —— lock_timeout 触发，等一会儿可能就拿到了"),
        ("40001", "serialization_failure"),
        ("40P01", "deadlock_detected"),
        ("08006", "connection_failure"),
        ("08003", "connection_does_not_exist"),
    ],
)
def test_retryable_sqlstates_are_not_misjudged(sqlstate, name):
    """**漏判这里任何一个，对应场景的数据都会被一次不重试地烧成终态。**"""
    kind, retryable = _SRC.classify_error(_pg_error(sqlstate))
    assert (kind, retryable) == ("db_error", True), f"{sqlstate} {name} 被误判为不可重试"


@pytest.mark.parametrize("code", ["57000", "57014", "57P05", "53000", "53400", "08001", "08004"])
def test_class_coverage_catches_codes_never_enumerated(code):
    """按 Class 给而非按个别码列——**漏的永远是没想到的那个**。

    这些码我一个都没在白名单里写过（写的是 `08`/`53`/`57` 三个 Class），它们
    仍落在正确一侧；改成逐码列举则每一个都是一次新的遗漏机会。
    """
    assert _SRC.classify_error(_pg_error(code))[1] is True


def test_class_coverage_overshoots_on_purpose_and_why():
    """**按 Class 会误收几个重试确实无用的码，这是有意接受的代价。**

    `57P04 database_dropped`（库被删）、`53100 disk_full` 重试短期都不会好，
    按码列本可排除它们。仍按 Class，是因为**两种误判的代价严重不对称**：

    - 误判为可重试 → 多试几次 → 走 `consecutive_writeback_failures` 判死 →
      `/health` 503，**有信号、可恢复**；
    - 误判为不可重试 → 一次重试都没有 → `final_failed` 终态 + 不计判死不告警，
      **无信号、不可恢复**，而数据已花掉 240s 预算和一次 LLM 调用。

    在不对称的代价面前，宁可多重试几次。
    """
    for code in ("57P04", "53100"):
        assert _SRC.classify_error(_pg_error(code))[1] is True


# --- 该判「不可重试」的：R2 已验过，保留防回归 ---
@pytest.mark.parametrize(
    "sqlstate, name",
    [
        ("42501", "insufficient_privilege —— 权限拒绝"),
        ("42P01", "undefined_table"),
        ("22P02", "invalid_text_representation —— 类型不符"),
        ("23505", "unique_violation —— 约束冲突"),
        ("23502", "not_null_violation"),
    ],
)
def test_deterministic_sqlstates_stay_non_retryable(sqlstate, name):
    """重试它们没有意义：同一份数据重试多少次都是同样结果，只是白烧
    `attempt` 与 240s 算力 + 一次 LLM 调用费。"""
    kind, retryable = _SRC.classify_error(_pg_error(sqlstate))
    assert (kind, retryable) == ("db_error", False), f"{sqlstate} {name} 被误判为可重试"


# --- 非 DB 异常与无 sqlstate 的驱动层错误 ---
def test_timeout_and_pool_timeout_are_retryable():
    """`TimeoutError` 是 `run_tx` 把事务超时转换后的形态。"""
    assert _SRC.classify_error(asyncio.TimeoutError()) == ("db_error", True)
    assert _SRC.classify_error(PoolTimeout()) == ("db_error", True)


def test_operational_error_without_sqlstate_is_retryable():
    """连接建立失败等环境类问题——尚未到达服务端，没有 sqlstate。"""
    assert _SRC.classify_error(psycopg.OperationalError("could not connect")) == ("db_error", True)


@pytest.mark.parametrize("exc", [RuntimeError("graph bug"), KeyError("x"), ValueError("v")])
def test_non_db_exception_is_unexpected(exc):
    """处理核心的代码 bug、未注册的 source type——**标成 `db_error` 会让运维
    照日志去查 DB 并查到「一切正常」**，会说谎的日志比没有日志更费时间。"""
    assert _SRC.classify_error(exc) == ("unexpected", False)
