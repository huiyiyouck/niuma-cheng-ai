"""连接池与**事务级**超时（O-6 / O-9 落定，设计 §4.10，CN-008）。

**PG 没有内建的事务执行超时**：`statement_timeout` 逐语句生效，
`idle_in_transaction_session_timeout` 管的是空闲而非执行。因此光靠数据库侧
配置给不出事务级上界——`DB_OP_BOUND` 的保证**只来自应用层的 asyncio.wait_for**，
不能靠 `ALTER ROLE` 绕开（CN-008 变更 3 第 2 条）。

一次写回是 3 条语句、一次 claim 是 4 条；把 `statement_timeout` 当成一次
事务的上界会低估到 1/3。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from psycopg_pool import AsyncConnectionPool

from agent_hub.config import WorkerSettings
from agent_hub.obs.logging import redact

log = logging.getLogger("agent_hub.db")


def build_conninfo(s: WorkerSettings) -> str:
    """按字段拼接，**不从整串 DSN 读**（O-7）。

    整串 DSN 极易被日志、`ps` 输出、驱动异常信息整体带出；按字段拆分后
    拼装点唯一、可集中脱敏。
    """
    return (
        f"host={s.db_host} port={s.db_port} dbname={s.db_name} "
        f"user={s.db_user} password={s.db_password} "
        f"connect_timeout={max(1, s.connect_timeout_ms // 1000)}"
    )


async def _configure(conn, s: WorkerSettings) -> None:
    """每条连接建立后设置超时与隔离级别。

    三层超时逐层收紧（lock < statement < tx），便于在日志中区分「等锁」
    「查询慢」「事务超时」——三者的处置方向完全不同。
    """
    await conn.execute(f"SET statement_timeout = {s.statement_timeout_ms}")
    await conn.execute(f"SET lock_timeout = {s.lock_timeout_ms}")
    await conn.execute("SET default_transaction_isolation = 'read committed'")


async def assert_read_committed(pool: AsyncConnectionPool) -> None:
    """启动期显式校验隔离级别，不符即拒绝启动（§4.10）。

    写法 B（fallback claim）的正确性依赖 `READ COMMITTED` 的 EvalPlanQual
    重新求值；在 RR / SERIALIZABLE 下会抛 `could not serialize access` 而非
    安全跳过。**这条依赖是隐式的、一旦被破坏表现为偶发报错**，必须在启动期
    暴露——写法 A 虽不依赖它，但写法 B 是将来权限收紧时的退路，启用那天
    没人会回头补这条断言。
    """
    async with pool.connection() as conn:
        cur = await conn.execute("SHOW transaction_isolation")
        row = await cur.fetchone()
    level = (row[0] if row else "").lower()
    if level != "read committed":
        raise RuntimeError(f"事务隔离级别须为 read committed，实际 {level!r}")


async def create_pool(s: WorkerSettings) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=build_conninfo(s),
        min_size=s.pool_min,
        max_size=s.pool_max,
        configure=lambda conn: _configure(conn, s),
        open=False,
    )
    await pool.open(wait=True, timeout=s.connect_timeout_ms / 1000 * 3)
    await assert_read_committed(pool)
    return pool


async def run_tx(pool: AsyncConnectionPool, s: WorkerSettings,
                 fn: Callable[[Any], Awaitable[Any]]) -> Any:
    """claim / 写回 / 自愈**三类事务统一走这里**（CN-008 变更 2）。

    - 连接随事务获取与释放，**不跨 `await` 长持**（O-6）：240s 的长持会同时
      踩服务端 `idle_in_transaction_session_timeout` 与连接池饥饿，三段式
      设计等于作废；
    - `asyncio.wait_for` 包整个事务，超时抛 `TimeoutError` → 回滚 → 计入
      写回重试；
    - **不得逐事务另设超时**：三类统一用同一个值，否则 `DB_OP_BOUND` 要按
      最大值重算，多一个易漂移的量。

    `CancelledError` 是 `BaseException`，不会被调用方的 `except Exception`
    吞掉——外部取消（优雅停机）因此能正常穿透，而超时被转成 `TimeoutError`
    计入重试。两者若被同一个 `except BaseException` 拦下，**超时重试与优雅
    停机会同时失效**。
    """

    async def _inner():
        async with pool.connection() as conn:
            async with conn.transaction():
                return await fn(conn)

    try:
        return await asyncio.wait_for(_inner(), timeout=s.tx_timeout_ms / 1000)
    except asyncio.TimeoutError:
        log.error(
            "tx_timeout",
            extra={"fields": {"step": "db", "status": "failed", "error_kind": "db_error",
                              "tx_timeout_ms": s.tx_timeout_ms}},
        )
        raise
    except Exception as exc:  # noqa: BLE001 — 统一脱敏后再上抛
        log.error(
            "tx_failed",
            extra={"fields": {"step": "db", "status": "failed", "error_kind": "db_error",
                              "error_message": redact(exc)}},
        )
        raise
