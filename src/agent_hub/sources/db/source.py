"""`DbPullSource`：`PullSource` 的 DB 实现（设计 §3.2、§4.3、§4.6-4.8）。

三段式事务边界（O-6）：claim 一个短事务、处理无事务、写回一个短事务。
全部经 `run_tx` 统一入口，事务级超时由应用层 `asyncio.wait_for` 保证。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from agent_hub.config import WorkerSettings
from agent_hub.sources.base import ClaimedItem, SourceRecord, WriteBackPayload
from agent_hub.sources.db import sql
from agent_hub.sources.db.pool import run_tx
from agent_hub.worker.state import worker_id_of

log = logging.getLogger("agent_hub.db")

# 可重试的 SQLSTATE——**按 Class 给，不按个别码列**（实现 R2 Architect Review 高①）。
#
# 按个别码列时，漏的永远是没想到的那个：R2 的白名单是 `40001 / 40P01 / 08*`，
# 照设计 §4.6 的三类清单写成，**却漏掉了 `57P01`(admin_shutdown)、`57P03`
# (cannot_connect_now) 这两个正是「PG 例行重启」的码**——而 CN-010 变更 1 从头到
# 尾的立论就是「PG 例行重启会走到这条路径」。漏判的后果是最坏的那条：判成确定性
# 错误 → 一次重试都没有 → `final_failed` 终态 → 且不计判死、不告警，**一条完全
# 正常、已花掉 240s 预算和一次 LLM 调用的数据，因为撞上重启就被烧成不可恢复**。
# **按 Class 会误收几个重试确实无用的码（57P04 database_dropped、53100 disk_full），
# 这是有意接受的代价**：两种误判的代价严重不对称——误判为可重试只是多试几次、
# 随后走连续失败判死（有信号、可恢复）；误判为不可重试则一次不试就进终态且不
# 告警（无信号、不可恢复）。在这种不对称面前，宁可多重试几次。
_RETRYABLE_SQLSTATE_CLASSES = frozenset({
    "08",   # connection_exception —— 连接断开 / 建立失败
    "53",   # insufficient_resources —— 含 53300 too_many_connections
    "57",   # operator_intervention —— 含 57P01 admin_shutdown / 57P03 cannot_connect_now
})
_RETRYABLE_SQLSTATES = frozenset({
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available —— lock_timeout 触发，等一会儿可能就拿到了
})


class DbPullSource:
    """实现 `PullSource`；映射由 `DbL1Mapper` 负责（协议按职责分层，O-2）。"""

    def __init__(self, pool, settings: WorkerSettings, lock_token: str):
        self._pool = pool
        self._s = settings
        self._lock_token = lock_token

    def classify_error(self, exc: BaseException) -> tuple[str, bool]:
        """驱动异常 → `(error_kind, 是否值得重试)`（设计 §4.6 / CN-010 变更 6、7）。

        **可重试用白名单制**：只有明确可重试的才为 True，其余一律当确定性
        错误。反过来写（黑名单）会让每一类新出现的错误默认进入重试，而重试
        一次的代价是 240s 算力 + 一次 LLM 调用费 + 一条 `attempt`。

        `TimeoutError` 是 `run_tx` 把事务超时转换后的形态；`CancelledError`
        不在此列——它是 `BaseException`，优雅停机要靠它穿透。
        """
        if isinstance(exc, (asyncio.TimeoutError, PoolTimeout)):
            return "db_error", True
        if isinstance(exc, psycopg.Error):
            state = getattr(exc, "sqlstate", None) or ""
            retryable = (
                state[:2] in _RETRYABLE_SQLSTATE_CLASSES
                or state in _RETRYABLE_SQLSTATES
                # 无 sqlstate 的 OperationalError：连接建立失败等环境类问题
                or (isinstance(exc, psycopg.OperationalError) and not state)
            )
            return "db_error", retryable
        return "unexpected", False

    # ── claim（§4.3）────────────────────────────────────────────────
    async def fetch_batch(self, n: int) -> list[ClaimedItem]:
        async def _claim(conn):
            cur = await conn.execute(sql.CLAIM_SELECT, {"n": n})
            rows = await cur.fetchall()
            if not rows:
                return []                       # 无可领条目返回 []，不是异常（AC-3.4）

            task_ids = [r[0] for r in rows]
            raw_item_ids = [r[1] for r in rows]
            await conn.execute(
                sql.CLAIM_MARK_RUNNING,
                {"lock_token": self._lock_token, "ids": task_ids},
            )
            cur = await conn.execute(
                sql.CLAIM_LOAD_RECORDS, {"raw_item_ids": raw_item_ids}
            )
            records = {r[0]: r for r in await cur.fetchall()}
            # 业务态：对方卡死回收的判定依据，必须写；l1_attempt 同事务递增
            await conn.execute(
                sql.CLAIM_MARK_PROCESSING, {"raw_item_ids": raw_item_ids}
            )

            claimed_at = time.monotonic()
            items = []
            for task_id, raw_item_id, attempt, max_attempts in rows:
                row = records.get(raw_item_id)
                if row is None:
                    # task 指向的 raw_item 不存在——留给对方发现，不猜
                    log.warning(
                        "claim_missing_raw_item",
                        extra={"fields": {"step": "claim", "status": "failed",
                                          "task_id": str(task_id)}},
                    )
                    continue
                items.append(
                    ClaimedItem(
                        task_id=task_id,
                        record=_to_record(row),
                        attempt=attempt,
                        max_attempts=max_attempts,
                        lock_token=self._lock_token,
                        claimed_at=claimed_at,
                    )
                )
            return items

        return await run_tx(self._pool, self._s, _claim)

    # ── 写回（§4.6）─────────────────────────────────────────────────
    async def commit_success(self, item: ClaimedItem, payload: WriteBackPayload) -> None:
        async def _commit(conn):
            await conn.execute(sql.WRITEBACK_UPSERT, _upsert_params(payload))
            await conn.execute(
                sql.WRITEBACK_MARK_COMPLETED, {"raw_item_id": payload.raw_item_id}
            )
            await conn.execute(sql.WRITEBACK_TASK_SUCCEEDED, {"task_id": item.task_id})

        await run_tx(self._pool, self._s, _commit)

    # ── 失败与退避（§4.7）───────────────────────────────────────────
    async def mark_failed(self, item: ClaimedItem, *, error_kind: str,
                          message: str, retryable: bool) -> None:
        # 重试上限读 tasks.max_attempts 列，**禁止硬编码 3**（C-8）——该列按
        # 对方的 AI_MAX_RETRIES 写入，硬编码会与其 env 配置形成双真源
        final = (not retryable) or item.attempt >= item.max_attempts

        async def _fail(conn):
            params = {
                "task_id": item.task_id,
                "raw_item_id": item.record.raw_item_id,
                "message": message[:2000],
                "error_kind": error_kind,
            }
            if final:
                await conn.execute(sql.FAIL_FINAL_TASK, params)
                await conn.execute(sql.FAIL_FINAL_RAW_ITEM, params)
            else:
                await conn.execute(
                    sql.FAIL_RETRYABLE_TASK,
                    {**params, "backoff_s": sql.backoff_for(item.attempt)},
                )
                await conn.execute(sql.FAIL_RETRYABLE_RAW_ITEM, params)

        await run_tx(self._pool, self._s, _fail)

    # ── 主动释放（停机路径，非失败）─────────────────────────────────
    async def release(self, item: ClaimedItem) -> None:
        async def _release(conn):
            await conn.execute(sql.RELEASE_TASK, {"task_id": item.task_id})
            await conn.execute(
                sql.RELEASE_RAW_ITEM, {"raw_item_id": item.record.raw_item_id}
            )

        await run_tx(self._pool, self._s, _release)

    # ── 启动自愈（§4.8）─────────────────────────────────────────────
    async def reclaim_own_stale_locks(self) -> int:
        async def _reclaim(conn):
            cur = await conn.execute(
                sql.RECLAIM_OWN_STALE,
                {
                    "worker_prefix": f"{worker_id_of(self._lock_token)}#%",
                    "current_lock_token": self._lock_token,
                },
            )
            rows = await cur.fetchall()
            if rows:
                await conn.execute(
                    sql.RECLAIM_RAW_ITEMS, {"raw_item_ids": [r[1] for r in rows]}
                )
            return len(rows)

        return await run_tx(self._pool, self._s, _reclaim)


def _to_record(row) -> SourceRecord:
    (raw_item_id, content, published_at, source_item_url, l0_label,
     source_type, source_identity, source_config, source_domain_tags) = row
    return SourceRecord(
        raw_item_id=raw_item_id,
        source_type=source_type or "",
        source_identity=source_identity or "",
        content=content or {},
        source_config=source_config or {},
        source_item_url=source_item_url,
        # 原值透传——**类型不保证**（实机既有 array 也有 object），
        # 由 map_domain_tags 做类型判定
        source_domain_tags=source_domain_tags,
        l0_label=l0_label,
        published_at=published_at,
    )


def _upsert_params(p: WriteBackPayload) -> dict:
    """jsonb 列须用 `Jsonb` 包装，否则 psycopg 会当成字符串写入。"""
    return {
        "raw_item_id": p.raw_item_id,
        "title": p.title,
        "summary": p.summary,
        "translation": Jsonb(p.translation),
        "context": Jsonb(p.context),
        "analysis": p.analysis,          # None → SQL NULL（Q-3）
        "score_dimensions": Jsonb(p.score_dimensions),
        "tags_v2": Jsonb(p.tags_v2),
        "language": p.language,
        "published_at": p.published_at,
        "needs_context": p.needs_context,
    }


def _as_uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
