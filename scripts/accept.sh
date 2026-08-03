#!/usr/bin/env bash
# v0.2 Owner 验收脚本
#
# 这个迭代没有界面，所以每项都打印「验什么 → 看到什么算通过」，
# 你只看输出即可，不需要读代码、不需要看测试数字。
#
# 只有【1】需要你动脑判断（AI 干得好不好），【2】~【5】看到「过」即可。
#
# 全程只碰独立测试库 ai_l1_itest，**绝不动 news_test**——那是小报的联调样本，
# 跑一次就少一条。真实新闻文本从 news_test **只读复制**，不消耗队列。
#
# 用法（在服务器上）：  cd /opt/niuma-cheng-ai && bash scripts/accept.sh
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/niuma-cheng-ai}"
ENV_FILE="${ENV_FILE:-/srv/niuma-ai/test/.env}"
ITEST_DB="${ITEST_DB:-ai_l1_itest}"
cd "$APP_DIR"

PY="$APP_DIR/.venv/bin/python"
PGPW=$(grep -E "^AI_DB_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)
export PYTHONPATH="$APP_DIR/src" APP_DIR ENV_FILE ITEST_DB PGPW
export ADMIN_DSN="host=127.0.0.1 dbname=$ITEST_DB user=itest_seeder password=itest_seed_pw"
export NEWS_RO_DSN="host=127.0.0.1 dbname=news_test user=ai_worker password=$PGPW"
export WORKER_DSN="host=127.0.0.1 dbname=$ITEST_DB user=ai_worker password=$PGPW"

hr() { printf '%.0s─' {1..72}; echo; }
sec() { echo; hr; echo "$1"; echo "$2"; hr; }

sec "【1】它能不能把一条真新闻处理好　← 只有这项需要你判断" \
"  验：取一条**真实推文**（从小报库只读复制），交给真实 AI 出标题/摘要/评分/标签
  过：下面的结果读起来是对的——标题贴切、每个评分都有像样的理由、标签不离谱
  说明：其余四项验的是「不出事」，只有这项验「干得好不好」"
"$PY" - <<'PY'
import asyncio, json, os, sys, time
from uuid import uuid4
import psycopg
sys.path.insert(0, os.environ["APP_DIR"])
from dotenv import load_dotenv
load_dotenv(os.environ["ENV_FILE"])

# LLM 凭据取自 openclaw（部署 .env 里那个 CodingPlan 订阅已过期，归 DevOps 更新）
oc = json.load(open("/root/.openclaw/openclaw.json"))["models"]["providers"]
key = lambda p: next(p[k] for k in p if k.lower() in ("apikey", "api_key"))
os.environ["VOLC_PLAN_KEY"] = key(oc["volcengine-plan"])
os.environ["DEEPSEEK_KEY"] = key(oc["deepseek"])
os.environ["LLM_PROVIDERS_JSON"] = json.dumps([
    {"name": "volcengine-plan", "base_url": oc["volcengine-plan"]["baseUrl"],
     "api_key_env": "VOLC_PLAN_KEY", "model": "doubao-seed-2.0-pro", "timeout_ms": 120000},
    {"name": "deepseek", "base_url": oc["deepseek"]["baseUrl"],
     "api_key_env": "DEEPSEEK_KEY", "model": "deepseek-v4-pro", "timeout_ms": 120000}])

from agent_hub.config import WorkerSettings
from agent_hub.llm.client import build_ai_client
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.db.pool import create_pool
from agent_hub.sources.db.source import DbPullSource
from agent_hub.tools.base import DefaultNewsTools
from agent_hub.worker.loop import process_one
from agent_hub.worker.state import WorkerState, make_lock_token

ADMIN, PW, DB = os.environ["ADMIN_DSN"], os.environ["PGPW"], os.environ["ITEST_DB"]

async def main():
    # 只读取一条真实推文（SELECT，不动 news_test 的任何状态）
    async with await psycopg.AsyncConnection.connect(os.environ["NEWS_RO_DSN"]) as c:
        cur = await c.execute(
            "SELECT content->>'text', source_item_url FROM raw_items"
            " WHERE process_type='ai' AND length(content->>'text') > 120"
            " ORDER BY created_at DESC LIMIT 1")
        row = await cur.fetchone()
    if not row:
        print("  ⚠ 小报库里没找到合适的真实样本，跳过"); return
    text, url = row
    print(f"  原文（真实推文，{len(text)} 字）：\n    {text[:150]}...\n")

    sid, rid, tid = uuid4(), uuid4(), uuid4()
    async with await psycopg.AsyncConnection.connect(ADMIN, autocommit=True) as c:
        for t in ("news_positions", "processed_news", "tasks", "raw_items", "sources"):
            await c.execute(f"DELETE FROM {t}")
        await c.execute("INSERT INTO sources (id,type,display_name,identity,config,domain_tags)"
                        " VALUES (%s,'x_twitter','验收源','acc','{}'::jsonb,'[\"AI\"]'::jsonb)", (sid,))
        await c.execute("INSERT INTO raw_items (id,source_id,source_item_id,content,published_at,"
                        "source_item_url,l0_status,l1_status,l1_attempt,process_type)"
                        " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
                        (rid, sid, f"acc-{rid.hex[:8]}", json.dumps({"text": text}), url))
        await c.execute("INSERT INTO tasks (id,type,status,raw_item_id,source_id,priority,run_after,"
                        "attempt,max_attempts) VALUES (%s,'l1_ai_process','queued',%s,%s,100,now(),0,3)",
                        (tid, rid, sid))

    s = WorkerSettings(run_mode="db", db_host="127.0.0.1", db_name=DB,
                       db_user="ai_worker", db_password=PW, claim_batch_size=1, item_budget_ms=240000)
    pool = await create_pool(s)
    src = DbPullSource(pool, s, make_lock_token("acc"))
    items = await src.fetch_batch(1)
    t0 = time.monotonic()
    await process_one(src, DbL1Mapper(), items[0], WorkerState(lock_token="acc#1"), s,
                      client=build_ai_client(), tools=DefaultNewsTools())
    elapsed = time.monotonic() - t0
    await pool.close()

    async with await psycopg.AsyncConnection.connect(ADMIN) as c:
        cur = await c.execute(
            "SELECT r.l1_status,t.status,p.title,p.summary,p.score_dimensions,p.tags_v2,"
            "p.needs_context,p.score_total FROM raw_items r JOIN tasks t ON t.raw_item_id=r.id"
            " LEFT JOIN processed_news p ON p.raw_item_id=r.id WHERE r.id=%s", (rid,))
        l1, ts, title, summary, dims, tags, needs, total = await cur.fetchone()

    print(f"  ── AI 的处理结果（耗时 {elapsed:.0f} 秒）" + "─" * 30)
    print(f"  标题：{title}")
    print(f"  摘要：{summary}")
    print("  评分：")
    for k, v in (dims or {}).items():
        print(f"    {k:12} {v.get('score')} 分 —— {v.get('reason')}")
    print(f"  领域标签：{(tags or {}).get('domain')}")
    print(f"  处理标记：{(tags or {}).get('processing')}")
    print(f"  证据是否不足：{needs}")
    print(f"  {'─'*68}")
    print(f"  数据库状态：l1_status={l1} / tasks={ts}"
          f" / score_total={total}（必须是 None，这列归小报算）")
    print("  过 ✅" if l1 == "completed" and ts == "succeeded" and title and total is None
          else "  未过 ❌")
PY

sec "【2】AI 处理失败了会不会丢数据" \
"  验：让 AI 调用必然失败，看那条新闻是被丢掉还是排队重来
  过：状态回到 queued 等重试、attempt +1、锁已释放"
"$PY" - <<'PY'
import asyncio, json, os, sys
from uuid import uuid4
import psycopg
sys.path.insert(0, os.environ["APP_DIR"])
from agent_hub.config import WorkerSettings
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.db.pool import create_pool
from agent_hub.sources.db.source import DbPullSource
from agent_hub.worker.loop import process_one
from agent_hub.worker.state import WorkerState, make_lock_token
from tests.test_news_l1 import FakeClient, NullTools

ADMIN, PW, DB = os.environ["ADMIN_DSN"], os.environ["PGPW"], os.environ["ITEST_DB"]

async def main():
    sid, rid, tid = uuid4(), uuid4(), uuid4()
    async with await psycopg.AsyncConnection.connect(ADMIN, autocommit=True) as c:
        for t in ("news_positions", "processed_news", "tasks", "raw_items", "sources"):
            await c.execute(f"DELETE FROM {t}")
        await c.execute("INSERT INTO sources (id,type,display_name,identity,config,domain_tags)"
                        " VALUES (%s,'x_twitter','验收源','acc2','{}'::jsonb,'[]'::jsonb)", (sid,))
        await c.execute("INSERT INTO raw_items (id,source_id,source_item_id,content,published_at,"
                        "source_item_url,l0_status,l1_status,l1_attempt,process_type)"
                        " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
                        (rid, sid, f"f-{rid.hex[:8]}", json.dumps({"text": "测试推文。"}), "https://x.com/a/1"))
        await c.execute("INSERT INTO tasks (id,type,status,raw_item_id,source_id,priority,run_after,"
                        "attempt,max_attempts) VALUES (%s,'l1_ai_process','queued',%s,%s,100,now(),0,3)",
                        (tid, rid, sid))

    s = WorkerSettings(run_mode="db", db_host="127.0.0.1", db_name=DB,
                       db_user="ai_worker", db_password=PW, claim_batch_size=1)
    pool = await create_pool(s)
    src = DbPullSource(pool, s, make_lock_token("acc2"))
    items = await src.fetch_batch(1)
    # 真实的失败：全部 provider 都抛异常
    await process_one(src, DbL1Mapper(), items[0], WorkerState(lock_token="acc2#1"), s,
                      client=FakeClient(exc=RuntimeError("all providers failed")), tools=NullTools())
    await pool.close()

    async with await psycopg.AsyncConnection.connect(ADMIN) as c:
        cur = await c.execute(
            "SELECT t.status,t.attempt,t.max_attempts,t.locked_by,r.l1_status,"
            "round(extract(epoch from (t.run_after-now())))::int"
            " FROM tasks t JOIN raw_items r ON r.id=t.raw_item_id WHERE t.id=%s", (tid,))
        st, att, mx, lock, l1, backoff = await cur.fetchone()
    print(f"  任务状态：{st}（回到队列等重试）    尝试次数：{att}/{mx}")
    print(f"  锁：{lock or 'NULL —— 已释放，别的 worker 可以接手'}")
    print(f"  下次重试：{backoff} 秒后（退避，不会立刻死循环）")
    print(f"  新闻状态：{l1}")
    print("  过 ✅" if st == "queued" and att == 1 and lock is None and backoff > 0 else "  未过 ❌")
PY

sec "【3】数据库重启会不会丢数据　← 本迭代最后一轮才修好的" \
"  验：真的让 PG 主动断开连接（terminate，不是模拟），看这类错误怎么归类
  过：判为「可重试」——等数据库回来接着做，而不是当成坏数据永久放弃
  改之前：会把撞上重启的**正常新闻**一次不重试地烧成永久失败，且不告警。
          每条白烧 4 分钟算力 + 一次 AI 调用费，而那条数据本身没有任何问题"
"$PY" - <<'PY'
import asyncio, os, sys
import psycopg
sys.path.insert(0, os.environ["APP_DIR"])
from agent_hub.config import WorkerSettings
from agent_hub.sources.db.source import DbPullSource

src = DbPullSource(None, WorkerSettings(), "acc#1")
DSN = os.environ["WORKER_DSN"]

async def main():
    victim = await psycopg.AsyncConnection.connect(DSN, connect_timeout=3)
    cur = await victim.execute("SELECT pg_backend_pid()")
    pid = (await cur.fetchone())[0]
    await victim.commit()
    killer = await psycopg.AsyncConnection.connect(DSN, connect_timeout=3)
    await killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
    await killer.commit(); await killer.close()
    print(f"  已真实终止数据库连接（后端进程 {pid}）")
    try:
        await victim.execute("SELECT 1")
        print("  ⚠ 未抛异常，用例无效"); return
    except Exception as exc:
        kind, retryable = src.classify_error(exc)
        print(f"  数据库报的错：{type(exc).__name__}（PG 错误码 {getattr(exc,'sqlstate','-')}）")
        print(f"  我方归类：{'可重试 —— 等数据库回来接着做' if retryable else '不可重试 —— 当坏数据放弃'}")
        print("  过 ✅" if retryable else "  未过 ❌")
    # 顺带确认反方向没做过头：权限/数据类错误仍应判为不可重试
    for code, desc in (("42501", "权限不足"), ("23505", "数据重复"), ("22P02", "格式不对")):
        _, r = src.classify_error(psycopg.errors.lookup(code)("x"))
        print(f"  对照：{desc}（{code}）→ {'可重试' if r else '不可重试'}"
              f" {'❌ 不该重试' if r else '✅'}")
asyncio.run(main())
PY

sec "【4】服务卡住了能不能看出来" \
"  验：让数据库「连得上但写不进」，看健康检查有没有把「正在反复失败」暴露出来
  过：写回失败计数在涨、服务仍报 200（还在挣扎，不是已死）
  为什么两个计数要分开：这个场景下领取任务一直成功，合成一个计数它会**恒为 0**，
  队列被逐条烧光而所有探针显示一切正常"
"$PY" - <<'PY'
import asyncio, os, sys
sys.path.insert(0, os.environ["APP_DIR"])
from agent_hub.config import WorkerSettings
from agent_hub.health import build_health
from agent_hub.worker.state import WorkerState

s = WorkerSettings(run_mode="db")
st = WorkerState(lock_token="w#1")
print("  刚启动：", end="")
b, c = build_health(s, st)
print(f"HTTP {c}  领取失败={b['consecutive_db_failures']}  写回失败={b['consecutive_writeback_failures']}")
st.consecutive_writeback_failures = 2      # 模拟：领取都成功，写回连续失败
print("  写回连续失败 2 次后：", end="")
b, c = build_health(s, st)
print(f"HTTP {c}  领取失败={b['consecutive_db_failures']}  写回失败={b['consecutive_writeback_failures']}")
ok1 = c == 200 and b["consecutive_writeback_failures"] == 2 and b["consecutive_db_failures"] == 0
st.mark_dead("db unreachable")
b, c = build_health(s, st)
print(f"  持续失败到判死后：HTTP {c}  状态={b['worker_state']}  原因={b['dead_reason']}")
print("  过 ✅" if ok1 and c == 503 else "  未过 ❌")
PY

sec "【5】重启服务会不会留下脏数据" \
"  验：处理到一半收到停机信号，看有没有留下「锁着但没人处理」的条目
  过：残留锁 0 条；未开始的条目原样退回队列——不算失败、不烧重试次数"
"$PY" - <<'PY'
import asyncio, json, os, sys
from uuid import uuid4
import psycopg
sys.path.insert(0, os.environ["APP_DIR"])
from agent_hub.config import WorkerSettings
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.db.pool import create_pool
from agent_hub.sources.db.source import DbPullSource
from agent_hub.worker.loop import worker_loop
from agent_hub.worker.state import WorkerState, make_lock_token
from tests.test_news_l1 import FakeClient, NullTools

ADMIN, PW, DB = os.environ["ADMIN_DSN"], os.environ["PGPW"], os.environ["ITEST_DB"]

async def main():
    sid = uuid4()
    async with await psycopg.AsyncConnection.connect(ADMIN, autocommit=True) as c:
        for t in ("news_positions", "processed_news", "tasks", "raw_items", "sources"):
            await c.execute(f"DELETE FROM {t}")
        await c.execute("INSERT INTO sources (id,type,display_name,identity,config,domain_tags)"
                        " VALUES (%s,'x_twitter','验收源','acc5','{}'::jsonb,'[]'::jsonb)", (sid,))
        for i in range(3):
            rid, tid = uuid4(), uuid4()
            await c.execute("INSERT INTO raw_items (id,source_id,source_item_id,content,published_at,"
                            "source_item_url,l0_status,l1_status,l1_attempt,process_type)"
                            " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
                            (rid, sid, f"s-{rid.hex[:8]}", json.dumps({"text": f"第 {i+1} 条。"}),
                             "https://x.com/a/1"))
            await c.execute("INSERT INTO tasks (id,type,status,raw_item_id,source_id,priority,run_after,"
                            "attempt,max_attempts) VALUES (%s,'l1_ai_process','queued',%s,%s,100,now(),0,3)",
                            (tid, rid, sid))

    s = WorkerSettings(run_mode="db", db_host="127.0.0.1", db_name=DB, db_user="ai_worker",
                       db_password=PW, claim_batch_size=3)
    pool = await create_pool(s)
    src = DbPullSource(pool, s, make_lock_token("acc5"))
    state = WorkerState(lock_token=make_lock_token("acc5"))
    stop = asyncio.Event()

    class StopAfterFirst(DbL1Mapper):
        def to_l1_input(self, record):          # 处理第一条时收到停机信号
            state.request_stop(); stop.set()
            return super().to_l1_input(record)

    await worker_loop(src, StopAfterFirst(), state, s, stop,
                      client=FakeClient(), tools=NullTools())
    await pool.close()

    async with await psycopg.AsyncConnection.connect(ADMIN) as c:
        cur = await c.execute(
            "SELECT count(*) FILTER (WHERE locked_by IS NOT NULL),"
            " count(*) FILTER (WHERE status='queued' AND attempt=0),"
            " count(*) FILTER (WHERE status='succeeded'),"
            " count(*) FILTER (WHERE last_error_kind IS NOT NULL) FROM tasks")
        locked, back, done, errs = await cur.fetchone()
    print(f"  残留锁：{locked} 条    已完成：{done} 条")
    print(f"  退回队列且**未烧重试次数**：{back} 条    被误标成失败：{errs} 条")
    print("  过 ✅" if locked == 0 and errs == 0 and back + done == 3 else "  未过 ❌")
PY

sec "【附】自动化测试（不需要看懂，只看有没有 failed）" "  过：两行都是 passed"
"$PY" -m pytest -q --ignore=tests/integration 2>&1 | tail -1
AI_ITEST_DSN="$WORKER_DSN" AI_ITEST_ADMIN_DSN="$ADMIN_DSN" "$PY" -m pytest tests/integration -q -p no:cacheprovider 2>&1 | tail -1

echo; hr
echo "验收要点：【1】看 AI 干得好不好（只有你能判断）；【2】~【5】看到「过 ✅」即可。"
echo "任何一项不满意，直接说哪一项、哪里不对。"
hr
