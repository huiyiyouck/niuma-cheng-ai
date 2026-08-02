"""claim / 写回 / 自愈 的 SQL（设计 §3.4、§4.6-4.8）。

**这是唯一出现表名与列名的地方**——AC-2.2 的静态判据靠这个边界成立。

契约 `news-l1-db` v1.9。ai 只读授权列、只写授权字段，不建表改表；
数据库层已强制（对方 2026-07-25 越权实测：SELECT alerts / INSERT raw_items /
UPDATE process_type 均 permission denied）。
"""
from __future__ import annotations

# ── claim（写法 A：C-6 实证通过，两侧各验一半后采用）─────────────────
# 权限侧由 xiaobao DevOps 验（ai_worker 身份下 FOR UPDATE SKIP LOCKED 可行，
# 列级 GRANT 足以支撑行锁）；并发侧由 ai DevOps 补（两会话拿到不同行、
# 全程 ROLLBACK 未消耗队列）。写法 B 保留为 v0.3 权限收紧时的退路。
CLAIM_SELECT = """
SELECT id, raw_item_id, attempt, max_attempts
FROM tasks
WHERE type = 'l1_ai_process'
  AND status = 'queued'
  AND run_after <= now()
  AND raw_item_id IS NOT NULL
ORDER BY priority DESC, run_after ASC
LIMIT %(n)s
FOR UPDATE SKIP LOCKED
"""
"""三个 WHERE 条件都不可省：

- `run_after <= now()`——缺它退避完全失效，失败条目会以轮询间隔的节奏被
  连续重领，几十秒内耗尽重试预算（C-4 的根因是对方 GRANT 少给了该列，
  其退避机制本就存在，**ai 禁止自算退避**否则形成两套真源）；
- `raw_item_id IS NOT NULL`——该列 nullable（tasks 是通用任务表）。若为空，
  适配层会在 claim 事务**已提交之后**才失败，此时条目已置 running、锁已持有；
  加此条件让异常 task 留在队列由对方发现，**ai 不把不属于自己的任务标 failed**；
- `ORDER BY priority DESC, run_after ASC`——R1→R3 演进中这条曾整条丢失，
  无 ORDER BY 时 PG 返回顺序由执行计划决定，队列积压时新条目插队、老条目
  饿死完全可能，而 REQ-003 的动机之一正是解决积压。priority 方向已由 C-11
  确认为「数值大 = 优先」。
"""

CLAIM_MARK_RUNNING = """
UPDATE tasks
SET status = 'running',
    attempt = attempt + 1,
    locked_by = %(lock_token)s,
    locked_at = now(),
    updated_at = now()
WHERE id = ANY(%(ids)s)
"""

CLAIM_LOAD_RECORDS = """
SELECT ri.id, ri.content, ri.published_at, ri.source_item_url, ri.l0_label,
       s.type AS source_type, s.identity AS source_identity,
       s.config AS source_config, s.domain_tags AS source_domain_tags
FROM raw_items ri
JOIN sources s ON s.id = ri.source_id
WHERE ri.id = ANY(%(raw_item_ids)s)
"""
"""一次性取全，使**处理阶段完全不持有数据库连接**（§4.10）。

`s.domain_tags` 是 `domain_tags` 的真源（C-14 定案，契约 v1.9）——不是
`raw_items.l0_label`，后者是流程标记而非领域分类。
"""

CLAIM_MARK_PROCESSING = """
UPDATE raw_items
SET l1_status = 'processing',
    l1_attempt = l1_attempt + 1
WHERE id = ANY(%(raw_item_ids)s)
"""
"""`l1_attempt` **在 claim 事务递增**，与 `tasks.attempt` 同事务推进。

若留到写回才加，worker 在「claim 之后、写回之前」崩溃时（240s 预算窗口内
这是最可能的崩溃点）两个计数器会永久差 1，对方侧看到的尝试次数比实际少
（AC-5.1 定 tasks.attempt 为判定真源、l1_attempt 为镜像值）。
"""

# ── 写回（§4.6）─────────────────────────────────────────────────────
# score_total 与 id **不出现在任何位置**——不是「写 NULL」，是根本不提及，
# 否则 ON CONFLICT DO UPDATE 会把对方已算好的 score_total 覆盖成 NULL。
# needs_context 必须同时进 INSERT 列清单与 DO UPDATE SET：占位行由对方在
# L0 通过时创建，故走 DO UPDATE 分支是**常态**；只加前者会让该列永远保持
# NULL 且不报错（CN-009 确认时提的实现落点）。
WRITEBACK_UPSERT = """
INSERT INTO processed_news (
    raw_item_id, title, summary, translation, context,
    analysis, score_dimensions, tags_v2, language, published_at, needs_context
) VALUES (
    %(raw_item_id)s, %(title)s, %(summary)s, %(translation)s, %(context)s,
    %(analysis)s, %(score_dimensions)s, %(tags_v2)s, %(language)s,
    %(published_at)s, %(needs_context)s
)
ON CONFLICT (raw_item_id) DO UPDATE SET
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    translation = EXCLUDED.translation,
    context = EXCLUDED.context,
    analysis = EXCLUDED.analysis,
    score_dimensions = EXCLUDED.score_dimensions,
    tags_v2 = EXCLUDED.tags_v2,
    language = EXCLUDED.language,
    published_at = EXCLUDED.published_at,
    needs_context = EXCLUDED.needs_context
"""

WRITEBACK_MARK_COMPLETED = """
UPDATE raw_items
SET l1_status = 'completed',
    l1_processed_at = now()
WHERE id = %(raw_item_id)s
"""

WRITEBACK_TASK_SUCCEEDED = """
UPDATE tasks
SET status = 'succeeded',
    locked_by = NULL,
    locked_at = NULL,
    updated_at = now()
WHERE id = %(task_id)s
"""

# ── 失败与退避（§4.7）───────────────────────────────────────────────
# 退避真源是 tasks.run_after，**禁止 ai 自算公式之外的推导**——自算会与
# 对方的 requeueTask 形成两套真源，卡死回收介入后必然漂移（C-4）。
FAIL_RETRYABLE_TASK = """
UPDATE tasks
SET status = 'queued',
    run_after = now() + make_interval(secs => %(backoff_s)s),
    last_error = %(message)s,
    last_error_kind = %(error_kind)s,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = now()
WHERE id = %(task_id)s
"""

FAIL_RETRYABLE_RAW_ITEM = """
UPDATE raw_items
SET l1_status = 'retryable_failed',
    l1_error = %(message)s
WHERE id = %(raw_item_id)s
"""

FAIL_FINAL_TASK = """
UPDATE tasks
SET status = 'failed',
    last_error = %(message)s,
    last_error_kind = %(error_kind)s,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = now()
WHERE id = %(task_id)s
"""

FAIL_FINAL_RAW_ITEM = """
UPDATE raw_items
SET l1_status = 'final_failed',
    l1_error = %(message)s,
    l1_processed_at = now()
WHERE id = %(raw_item_id)s
"""

# ── 主动释放（停机路径，非失败）─────────────────────────────────────
# 退回 queued + 清锁，且**不动 attempt、不写 last_error**。
RELEASE_TASK = """
UPDATE tasks
SET status = 'queued',
    locked_by = NULL,
    locked_at = NULL,
    updated_at = now()
WHERE id = %(task_id)s
"""

RELEASE_RAW_ITEM = """
UPDATE raw_items
SET l1_status = 'queued'
WHERE id = %(raw_item_id)s
"""

# ── 启动自愈（§4.8，AC-5.6）─────────────────────────────────────────
# **只回收 worker_id 前缀相同、run_token 不同的锁**——他人的锁一律不碰，
# 交对方的卡死回收（600s）处理。
RECLAIM_OWN_STALE = """
UPDATE tasks
SET status = 'queued',
    run_after = now(),
    locked_by = NULL,
    locked_at = NULL,
    updated_at = now()
WHERE type = 'l1_ai_process'
  AND status = 'running'
  AND locked_by LIKE %(worker_prefix)s
  AND locked_by <> %(current_lock_token)s
RETURNING id, raw_item_id
"""

RECLAIM_RAW_ITEMS = """
UPDATE raw_items
SET l1_status = 'retryable_failed'
WHERE id = ANY(%(raw_item_ids)s)
"""

# 退避间隔（契约 §task type）。attempt 超出数组长度时**取末值**，
# 禁止取 0（取 0 即静默退化回「立刻重领」，正是 C-4 刚修好的问题）——
# 因对方 tasks.max_attempts schema 默认为 5 而本数组长度为 3（C-12）。
BACKOFF_SECONDS = [60, 300, 900]


def backoff_for(attempt: int) -> int:
    """`attempt` 从 1 起。越界取末值。"""
    idx = min(max(attempt, 1), len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[idx]
