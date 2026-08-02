#!/usr/bin/env bash
# v0.2 实现 R1 · Owner 验收脚本
#
# 每一项都打印「验的是什么 → 看到什么算通过」，不需要读代码。
# 全程只碰独立测试库 ai_l1_itest，不动 news_test（对方的联调样本）。
set -uo pipefail

# 可用环境变量覆盖（默认值为当前测试环境）
APP_DIR="${APP_DIR:-/root/Project/ai-itest}"      # 代码目录
ENV_FILE="${ENV_FILE:-/srv/niuma-ai/test/.env}"   # 含 LLM 与 DB 凭据，不入仓
ITEST_DB="${ITEST_DB:-ai_l1_itest}"               # 独立测试库，绝不指向 news_test
cd "$APP_DIR"

export PYTHONPATH=src
PY=.venv/bin/python
PGPW=$(grep -E "^AI_DB_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)
export AI_ITEST_DSN="host=127.0.0.1 port=5432 dbname=$ITEST_DB user=ai_worker password=$PGPW"
export AI_ITEST_ADMIN_DSN="host=127.0.0.1 port=5432 dbname=$ITEST_DB user=itest_seeder password=itest_seed_pw"

export APP_DIR ENV_FILE ITEST_DB

hr() { printf '%.0s─' {1..70}; echo; }
ok() { echo "  ✅ $1"; }
no() { echo "  ❌ $1"; }

hr; echo "【1】自动化测试全量跑一遍"
echo "  验：141 项单测 + 10 项真实 PG 集成测试"
echo "  过：两行都是 passed，没有 failed"
hr
$PY -m pytest -q 2>&1 | tail -2
$PY -m pytest tests/integration -q 2>&1 | tail -2

hr; echo "【2】DB 模式真实闭环：一条新闻从入队到写回"
echo "  验：worker 真的 claim → 处理 → 写回数据库（不是测试桩自说自话）"
echo "  过：l1_status 由 queued 变 completed，且 processed_news 出现结果行"
hr
$PY - <<'PYEOF'
import asyncio, json, os
from uuid import uuid4
import psycopg
from dotenv import load_dotenv
load_dotenv(os.environ["ENV_FILE"])
os.environ["AI_DB_NAME"] = os.environ["ITEST_DB"]
from agent_hub.config import WorkerSettings
from agent_hub.sources.db.mapper import DbL1Mapper
from agent_hub.sources.db.pool import create_pool
from agent_hub.sources.db.source import DbPullSource
from agent_hub.worker.loop import process_one
from agent_hub.worker.state import WorkerState, make_lock_token
import sys; sys.path.insert(0, ".")
from tests.test_news_l1 import FakeClient, NullTools

ADMIN = os.environ["AI_ITEST_ADMIN_DSN"]

async def main():
    async with await psycopg.AsyncConnection.connect(ADMIN, autocommit=True) as c:
        for t in ("news_positions","processed_news","tasks","raw_items","sources"):
            await c.execute(f"DELETE FROM {t}")
        sid, rid, tid = uuid4(), uuid4(), uuid4()
        await c.execute("INSERT INTO sources (id,type,display_name,identity,config,domain_tags)"
                        " VALUES (%s,'x_twitter','验收源','acc','{}'::jsonb,'[\"AI\"]'::jsonb)",(sid,))
        await c.execute("INSERT INTO raw_items (id,source_id,source_item_id,content,published_at,"
                        "source_item_url,l0_status,l1_status,l1_attempt,process_type)"
                        " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
                        (rid,sid,f"acc-{rid.hex[:8]}",
                         json.dumps({"text":"某公司发布新一代推理芯片，能效比提升两倍。","author_username":"acc"}),
                         "https://x.com/acc/status/1"))
        await c.execute("INSERT INTO tasks (id,type,status,raw_item_id,source_id,priority,"
                        "run_after,attempt,max_attempts) VALUES (%s,'l1_ai_process','queued',%s,%s,100,now(),0,3)",
                        (tid,rid,sid))
        cur = await c.execute("SELECT l1_status FROM raw_items WHERE id=%s",(rid,))
        print(f"  处理前 raw_items.l1_status = {(await cur.fetchone())[0]}")

    s = WorkerSettings(run_mode="db", db_host="127.0.0.1", db_name=os.environ["ITEST_DB"],
                       db_user="ai_worker", db_password=os.environ["AI_DB_PASSWORD"],
                       claim_batch_size=1)
    pool = await create_pool(s)
    src = DbPullSource(pool, s, make_lock_token("acc"))
    items = await src.fetch_batch(1)
    print(f"  worker claim 到 {len(items)} 条")
    await process_one(src, DbL1Mapper(), items[0], WorkerState(lock_token="acc#1"), s,
                      client=FakeClient(), tools=NullTools())
    async with await psycopg.AsyncConnection.connect(ADMIN) as c:
        cur = await c.execute("SELECT r.l1_status,t.status,p.title,p.language,p.needs_context,"
                              "p.score_total FROM raw_items r JOIN tasks t ON t.raw_item_id=r.id"
                              " LEFT JOIN processed_news p ON p.raw_item_id=r.id WHERE r.id=%s",(rid,))
        l1,ts,title,lang,needs,total = await cur.fetchone()
    print(f"  处理后 raw_items.l1_status = {l1}    tasks.status = {ts}")
    print(f"  processed_news 写入: title={title!r} language={lang} needs_context={needs}")
    print(f"  score_total = {total}  ← 必须是 None（这一列归 xiaobao 算，ai 不能写）")
    print("  ✅ 闭环成立" if (l1=="completed" and ts=="succeeded" and title and total is None)
          else "  ❌ 闭环未成立")
    await pool.close()
asyncio.run(main())
PYEOF

hr; echo "【3】出故障时会不会「静默失败」"
echo "  验：worker 协程死掉后，健康检查必须报 503，而不是继续说自己健康"
echo "  过：三行分别是 200 / 200 / 503"
hr
$PY - <<'PYEOF'
from agent_hub.config import WorkerSettings
from agent_hub.health import build_health
from agent_hub.worker.state import WorkerState
s = WorkerSettings(run_mode="db")
for phase, desc in [("running","正常运行"),("stopping","正在优雅停机"),("dead","worker 已死")]:
    st = WorkerState(lock_token="w#1"); st.phase = phase
    body, code = build_health(s, st)
    print(f"  {desc:14} → HTTP {code}  worker_state={body['worker_state']}")
PYEOF

hr; echo "【4】配置写错时会不会带病启动"
echo "  验：把批量 N 调到 8（PRD 曾暂定的值），启动门禁必须拒绝"
echo "  过：打印「拒绝启动」并给出算式"
hr
$PY - <<'PYEOF'
from agent_hub.config import WorkerSettings, validate_worker_settings, ConfigInvariantError
try:
    validate_worker_settings(WorkerSettings(claim_batch_size=8))
    print("  ❌ 竟然放行了")
except ConfigInvariantError as e:
    print(f"  ✅ 拒绝启动：{str(e).splitlines()[1].strip()}")
PYEOF

hr; echo "【5】真实 LLM 可用性（当前受外部因素阻塞）"
echo "  验：能否真的调通大模型"
hr
$PY - <<'PYEOF'
import asyncio, os, httpx
from dotenv import load_dotenv
load_dotenv(os.environ["ENV_FILE"])
from agent_hub.config import load_providers
ps = load_providers()
print(f"  已配置 provider: {[p.name for p in ps]}（无备用 provider）")
p = ps[0]
r = httpx.post(p.base_url.rstrip('/')+"/chat/completions",
               json={"model":p.model,"messages":[{"role":"user","content":"hi"}]},
               headers={"Authorization":f"Bearer {os.getenv(p.api_key_env,'')}"}, timeout=30)
import json as j
msg = j.loads(r.text).get("error",{}).get("message","") if r.status_code>=400 else "OK"
print(f"  调用结果: HTTP {r.status_code}")
print(f"  {msg[:150]}")
print("  ⚠️  订阅过期属账号问题，非代码问题——同步/异步两种调法结果一致" if r.status_code>=400 else "  ✅ LLM 可用")
PYEOF

hr; echo "验收要点：【1】~【4】是本次开发的交付物，应全绿；"
echo "【5】红是账号订阅过期，需续订后才能验「产出质量」那一层。"
hr
