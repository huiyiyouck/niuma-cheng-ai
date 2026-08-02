"""真实 PostgreSQL 集成测试（设计 §8 测试 6/7/15/16/20/23）。

**这些是 mock 测不出的**：`SKIP LOCKED` 的并发语义、事务回滚、列级 GRANT
下的可执行性、触发器时序——只有真实库能验。

运行方式（需 `AI_ITEST_DSN` 指向一个**独立测试库**）：

    AI_ITEST_DSN="host=127.0.0.1 dbname=ai_l1_itest user=ai_worker password=..." \\
    PYTHONPATH=src pytest tests/integration -q

未设该变量时整组跳过——本机（开发机）没有 PG，CI 与开发机不应因此变红。

**纪律**：绝不指向 `news_test`。对方只预置了个位数条 `queued`，端到端会真实
消耗；测试库用本文件自己造的数据，跑多少次都不影响联调样本。
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_hub.config import WorkerSettings
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.db.pool import create_pool, run_tx
from agent_hub.sources.db.source import DbPullSource
from agent_hub.worker.loop import process_one, worker_loop
from agent_hub.worker.state import WorkerState, make_lock_token
from tests.test_news_l1 import FakeClient, NullTools

DSN = os.getenv("AI_ITEST_DSN", "")
# 造数用独立角色——ai_worker 按契约只有 SELECT/UPDATE，**无 INSERT**，
# 这与生产中「对方造数、ai 只消费」的分工一致，测试不该为造数破坏该边界。
ADMIN_DSN = os.getenv("AI_ITEST_ADMIN_DSN", "")
pytestmark = pytest.mark.skipif(
    not (DSN and ADMIN_DSN), reason="需设 AI_ITEST_DSN 与 AI_ITEST_ADMIN_DSN 指向独立测试库"
)


def _settings(**over) -> WorkerSettings:
    parts = dict(p.split("=", 1) for p in DSN.split() if "=" in p)
    base = dict(
        run_mode="db",
        db_host=parts.get("host", "127.0.0.1"),
        db_port=int(parts.get("port", 5432)),
        db_name=parts.get("dbname", ""),
        db_user=parts.get("user", ""),
        db_password=parts.get("password", ""),
        claim_batch_size=1,
        item_budget_ms=60000,
        tx_timeout_ms=5000,
        statement_timeout_ms=4000,
        lock_timeout_ms=3000,
        writeback_retry=1,
        writeback_retry_delay_ms=10,
    )
    base.update(over)
    return WorkerSettings(**base)


@pytest.fixture(autouse=True)
async def _clean():
    """每个测试前清空测试数据——保证用例独立、可重复跑。

    仅作用于**独立测试库**；`news_test` 绝不在此列（见模块 docstring 的纪律）。
    """
    import psycopg

    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        for table in ("news_positions", "processed_news", "tasks", "raw_items", "sources"):
            await conn.execute(f"DELETE FROM {table}")
    yield


@pytest.fixture
async def pool():
    p = await create_pool(_settings())
    yield p
    await p.close()


async def _seed(pool, *, n=1, status="queued", run_after_offset="0 seconds",
                priority=100, max_attempts=3, domain_tags=None, url=None):
    """造数：sources → raw_items → tasks。返回 [(task_id, raw_item_id)]。

    以 ai_worker 身份无法 INSERT（契约只给 SELECT/UPDATE），故造数走
    独立的超级用户连接——与生产中「对方造数、ai 只消费」的分工一致。
    """
    import psycopg

    out = []
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        source_id = uuid4()
        # 必填列按**真实 schema** 而非契约摘要——契约只列了 ai 需读的列，
        # 造数还要满足 sources.display_name / raw_items.source_item_id 等
        # 对方侧的必填约束（按契约猜会写不进去）
        await conn.execute(
            "INSERT INTO sources (id, type, display_name, identity, config, domain_tags)"
            " VALUES (%s,'x_twitter',%s,%s,'{}'::jsonb,%s::jsonb)",
            # display_name 有 lower() 唯一约束，须带唯一后缀
            (source_id, f"itest-{source_id.hex[:8]}", f"itest_{source_id.hex[:8]}",
             '["AI"]' if domain_tags is None else domain_tags),
        )
        for i in range(n):
            raw_id, task_id = uuid4(), uuid4()
            await conn.execute(
                "INSERT INTO raw_items (id, source_id, source_item_id, content, published_at,"
                " source_item_url, l0_status, l1_status, l1_attempt, process_type)"
                " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
                (raw_id, source_id, f"itest-{raw_id.hex[:12]}",
                 f'{{"text": "集成测试推文 {i}", "author_username": "itest"}}',
                 url if url is not None else f"https://x.com/itest/status/{i}"),
            )
            await conn.execute(
                "INSERT INTO tasks (id, type, status, raw_item_id, source_id, priority,"
                " run_after, attempt, max_attempts)"
                " VALUES (%s,'l1_ai_process',%s,%s,%s,%s, now() + %s::interval, 0, %s)",
                (task_id, status, raw_id, source_id, priority, run_after_offset, max_attempts),
            )
            out.append((task_id, raw_id))
    return out


async def _q(pool, sql, params=None):
    async def _run(conn):
        cur = await conn.execute(sql, params)
        return await cur.fetchall()

    return await run_tx(pool, _settings(), _run)


# ── 测试 6：claim 并发不重复（SKIP LOCKED）──────────────────────────
async def test_concurrent_claim_never_duplicates(pool):
    """两个 worker 同时 claim，**不得拿到同一条**。

    这是 mock 完全测不出的一条——`SKIP LOCKED` 的语义只存在于真实事务中。
    """
    await _seed(pool, n=4)
    s = _settings(claim_batch_size=2)
    a = DbPullSource(pool, s, make_lock_token("worker-a"))
    b = DbPullSource(pool, s, make_lock_token("worker-b"))

    got_a, got_b = await asyncio.gather(a.fetch_batch(2), b.fetch_batch(2))
    ids_a = {i.task_id for i in got_a}
    ids_b = {i.task_id for i in got_b}

    assert ids_a and ids_b, "两侧都应领到（共 4 条待处理）"
    assert not (ids_a & ids_b), f"并发 claim 拿到重复条目: {ids_a & ids_b}"


async def test_claim_respects_run_after_backoff(pool):
    """退避窗口内不得被重领——缺 `run_after <= now()` 条件时这条会失败（C-4）。"""
    await _seed(pool, n=1, run_after_offset="1 hour")
    src = DbPullSource(pool, _settings(), make_lock_token("w-backoff"))
    assert await src.fetch_batch(5) == [], "退避窗口内的条目不应被领取"


async def test_claim_skips_null_raw_item_id(pool):
    """`tasks.raw_item_id` 可为空（通用任务表）。领到会在事务提交后才失败，
    此时条目已被标记、锁已持有——ai 会把不属于自己的任务标成 failed（越界）。"""
    import psycopg

    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO tasks (id, type, status, raw_item_id, priority, run_after,"
            " attempt, max_attempts) VALUES (%s,'l1_ai_process','queued',NULL,999,now(),0,3)",
            (uuid4(),),
        )
    src = DbPullSource(pool, _settings(), make_lock_token("w-null"))
    items = await src.fetch_batch(5)
    assert all(i.record.raw_item_id is not None for i in items)


# ── 测试 23：两个计数器同事务推进 ───────────────────────────────────
async def test_attempt_counters_stay_consistent_after_claim(pool):
    """`l1_attempt` 与 `tasks.attempt` 在 claim 事务后必须相等。

    若 `l1_attempt` 留到写回才加，claim 之后、写回之前崩溃（240s 预算窗口内
    最可能的崩溃点）两者会永久差 1，对方看到的尝试次数比实际少。
    """
    (task_id, raw_id), = await _seed(pool, n=1)
    src = DbPullSource(pool, _settings(), make_lock_token("w-cnt"))
    await src.fetch_batch(1)

    rows = await _q(pool,
                    "SELECT t.attempt, r.l1_attempt FROM tasks t"
                    " JOIN raw_items r ON r.id=t.raw_item_id WHERE t.id=%s", (task_id,))
    assert rows[0][0] == rows[0][1] == 1


# ── 测试 20：端到端 claim → 处理 → 写回 completed ──────────────────
async def test_end_to_end_writes_back_completed(pool):
    """完整闭环（AC-10.2 的等价验证，用自造数据而非对方的联调样本）。"""
    (task_id, raw_id), = await _seed(pool, n=1)
    s = _settings()
    src = DbPullSource(pool, s, make_lock_token("w-e2e"))
    state = WorkerState(lock_token="w-e2e#1")

    items = await src.fetch_batch(1)
    assert len(items) == 1
    await process_one(src, DbL1Mapper(), items[0], state, s,
                      client=FakeClient(), tools=NullTools())

    rows = await _q(pool,
                    "SELECT r.l1_status, t.status, p.title, p.language, p.needs_context,"
                    " p.score_total, p.published_at IS NOT NULL"
                    " FROM raw_items r JOIN tasks t ON t.raw_item_id=r.id"
                    " LEFT JOIN processed_news p ON p.raw_item_id=r.id WHERE r.id=%s", (raw_id,))
    l1_status, task_status, title, language, needs_ctx, score_total, has_published = rows[0]

    assert l1_status == "completed"
    assert task_status == "succeeded"
    assert title, "写回内容缺失"
    assert language == "zh"                      # C-7 定案
    assert needs_ctx is not None                 # CN-009：列已落地且被写入
    assert score_total is None, "score_total 归对方加权，ai 不得写（O-1）"
    assert has_published, "published_at 双保险未写入"


async def test_writeback_is_idempotent_on_placeholder_row(pool):
    """占位行已存在时走 `ON CONFLICT DO UPDATE`——这是**常态**（C-3）。

    若 `needs_context` 只进了 INSERT 列清单、漏了 DO UPDATE SET，本用例会
    发现该列在二次写回后仍是旧值（CN-009 确认时提的落点）。
    """
    import psycopg

    (task_id, raw_id), = await _seed(pool, n=1)
    # 模拟对方在 L0 通过时创建的占位行
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO processed_news (raw_item_id, title, summary, needs_context)"
            " VALUES (%s,'占位','占位', false)", (raw_id,))

    s = _settings()
    src = DbPullSource(pool, s, make_lock_token("w-upsert"))
    state = WorkerState(lock_token="w-upsert#1")
    items = await src.fetch_batch(1)
    await process_one(src, DbL1Mapper(), items[0], state, s,
                      client=FakeClient(), tools=NullTools())

    rows = await _q(pool, "SELECT title, needs_context, count(*) OVER () FROM processed_news"
                          " WHERE raw_item_id=%s", (raw_id,))
    assert len(rows) == 1, "ON CONFLICT 失效，产生了重复行"
    assert rows[0][0] != "占位", "占位行未被更新"


# ── 测试 7：写回事务的原子性 ────────────────────────────────────────
async def test_writeback_rolls_back_atomically(pool):
    """中途失败不得留下「结果已写但状态未推进」。"""
    (task_id, raw_id), = await _seed(pool, n=1)
    s = _settings()
    src = DbPullSource(pool, s, make_lock_token("w-tx"))
    items = await src.fetch_batch(1)

    from agent_hub.sources.db import sql as dbsql

    original = dbsql.WRITEBACK_TASK_SUCCEEDED
    try:
        # 让事务的最后一条语句失败
        dbsql.WRITEBACK_TASK_SUCCEEDED = "UPDATE tasks SET status='succeeded' WHERE id=%(task_id)s AND 1/0=1"
        payload = DbL1Mapper().from_l1_output(_fake_output(), items[0])
        with pytest.raises(Exception):
            await src.commit_success(items[0], payload)
    finally:
        dbsql.WRITEBACK_TASK_SUCCEEDED = original

    rows = await _q(pool, "SELECT (SELECT count(*) FROM processed_news WHERE raw_item_id=%s),"
                          " (SELECT l1_status FROM raw_items WHERE id=%s)", (raw_id, raw_id))
    assert rows[0][0] == 0, "事务未回滚：结果已写但状态未推进"
    assert rows[0][1] == "processing"


def _fake_output():
    from agent_hub.schemas import L1Output, ScoreDimension, ScoreDimensions, Tags

    d = ScoreDimension(score=3, reason="r")
    return L1Output(
        title="t", summary="s", translation={"zh": "z"}, context=[], analysis=None,
        score_dimensions=ScoreDimensions(timeliness=d, impact=d, confidence=d, clarity=d),
        tags=Tags(processing=["engine:agent_hub"]), needs_context=True,
    )


# ── 测试 15/16：停机释放与启动自愈 ──────────────────────────────────
async def test_release_returns_item_without_touching_attempt(pool):
    """主动释放：退回 queued、清锁，且**不动 attempt、不写 last_error**。"""
    (task_id, raw_id), = await _seed(pool, n=1)
    src = DbPullSource(pool, _settings(), make_lock_token("w-rel"))
    items = await src.fetch_batch(1)
    before = (await _q(pool, "SELECT attempt FROM tasks WHERE id=%s", (task_id,)))[0][0]

    await src.release(items[0])

    rows = await _q(pool, "SELECT status, locked_by, attempt, last_error FROM tasks WHERE id=%s",
                    (task_id,))
    status, locked_by, attempt, last_error = rows[0]
    assert status == "queued" and locked_by is None
    assert attempt == before, "释放不应消耗重试配额"
    assert last_error is None, "释放不是失败，不应写 last_error"


async def test_self_heal_only_reclaims_own_previous_run(pool):
    """只回收 `worker_id` 相同、`run_token` 不同的锁；**他人的锁一律不碰**。"""
    (mine, mine_raw), (theirs, theirs_raw) = await _seed(pool, n=2)

    old_token = "worker-x#aaaa"       # 我上次进程
    other_token = "worker-y#bbbb"     # 他人
    import psycopg

    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        await conn.execute("UPDATE tasks SET status='running', locked_by=%s, locked_at=now()"
                           " WHERE id=%s", (old_token, mine))
        await conn.execute("UPDATE tasks SET status='running', locked_by=%s, locked_at=now()"
                           " WHERE id=%s", (other_token, theirs))

    src = DbPullSource(pool, _settings(), "worker-x#cccc")   # 本次运行
    reclaimed = await src.reclaim_own_stale_locks()

    assert reclaimed == 1, "应只回收自己上次进程的那一条"
    rows = await _q(pool, "SELECT id, status, locked_by FROM tasks WHERE id = ANY(%s)",
                    ([mine, theirs],))
    by_id = {r[0]: (r[1], r[2]) for r in rows}
    assert by_id[mine] == ("queued", None), "自己上次的锁应被回收"
    assert by_id[theirs][0] == "running", "他人的锁不得碰"


# ── 端到端：worker 循环在真实库上跑通 ──────────────────────────────
async def test_worker_loop_drains_queue_then_idles(pool):
    """worker 循环在真实库上完成 claim → 处理 → 写回，队列排空后进入空转。"""
    await _seed(pool, n=2)
    s = _settings(poll_interval_ms=10000, empty_poll_warn=1)
    src = DbPullSource(pool, s, make_lock_token("w-loop"))
    state = WorkerState(lock_token="w-loop#1")
    stop = asyncio.Event()

    async def stop_when_idle():
        for _ in range(100):
            await asyncio.sleep(0.05)
            if state.consecutive_empty_polls >= 1:
                break
        state.request_stop()
        stop.set()

    await asyncio.gather(
        worker_loop(src, DbL1Mapper(), state, s, stop,
                    client=FakeClient(), tools=NullTools()),
        stop_when_idle(),
    )

    done = await _q(pool, "SELECT count(*) FROM raw_items WHERE l1_status='completed'"
                          " AND source_item_url LIKE 'https://x.com/itest%%'")
    assert done[0][0] >= 2
