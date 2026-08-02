"""`DbPullSource`：`PullSource` 的 DB 实现（设计 §3.2、§4.3、§4.6-4.8）。

三段式事务边界（O-6）：claim 一个短事务、处理无事务、写回一个短事务。
全部经 `run_tx` 统一入口，事务级超时由应用层 `asyncio.wait_for` 保证。
"""
from __future__ import annotations

import json
import logging
import time
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_hub.config import WorkerSettings
from agent_hub.sources.base import ClaimedItem, SourceRecord, WriteBackPayload
from agent_hub.sources.db import sql
from agent_hub.sources.db.pool import run_tx
from agent_hub.worker.state import worker_id_of

log = logging.getLogger("agent_hub.db")


class DbPullSource:
    """实现 `PullSource`；映射由 `DbL1Mapper` 负责（协议按职责分层，O-2）。"""

    def __init__(self, pool, settings: WorkerSettings, lock_token: str):
        self._pool = pool
        self._s = settings
        self._lock_token = lock_token

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
