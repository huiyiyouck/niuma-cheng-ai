"""真实闭环验收：真实 LLM + 真实 PostgreSQL，走完整 claim → 处理 → 写回。

与集成测试的区别：集成测试用 FakeClient（**验编排逻辑**），本脚本用真实
LLM（**验产出质量**）——四维评分、标签、摘要是否像样，只能人看。单条约 70~80s。

用法（服务器上）：
    cd /root/Project/ai-itest && PYTHONPATH=src .venv/bin/python scripts/real_e2e.py

LLM 凭据从 `/root/.openclaw/openclaw.json` 读取（**不落盘、不回显**）。
之所以不读部署目录的 `.env`：那里配的 `/api/coding/v3` 订阅已过期，而
openclaw 的 `/api/plan/v3` 可用——同一个模型名，只是端点与 key 不同。
"""
import asyncio
import json
import os
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

# 必须先加载 .env 再 import agent_hub——config.py 在 import 期读环境变量
load_dotenv(os.getenv("ENV_FILE", "/srv/niuma-ai/test/.env"))

# 用 openclaw 中**实测可用**的两个 provider 覆盖 .env 里已过期的配置，
# 顺带让 ADR-0002 的多 provider fallback 链真正生效（原 .env 只有一个）
if os.getenv("USE_OPENCLAW_LLM", "1") == "1":
    _oc = json.load(open("/root/.openclaw/openclaw.json"))["models"]["providers"]

    def _key(p):
        return next(p[k] for k in p if k.lower() in ("apikey", "api_key"))

    os.environ["VOLC_PLAN_KEY"] = _key(_oc["volcengine-plan"])
    os.environ["DEEPSEEK_KEY"] = _key(_oc["deepseek"])
    os.environ["LLM_PROVIDERS_JSON"] = json.dumps([
        {"name": "volcengine-plan", "base_url": _oc["volcengine-plan"]["baseUrl"],
         "api_key_env": "VOLC_PLAN_KEY", "model": "doubao-seed-2.0-pro", "timeout_ms": 120000},
        {"name": "deepseek", "base_url": _oc["deepseek"]["baseUrl"],
         "api_key_env": "DEEPSEEK_KEY", "model": "deepseek-v4-pro", "timeout_ms": 120000},
    ])

# DB 指向独立测试库，不碰 news_test
ITEST_DB = os.getenv("ITEST_DB", "ai_l1_itest")
ADMIN_DSN = (f"host=127.0.0.1 port=5432 dbname={ITEST_DB}"
             " user=itest_seeder password=itest_seed_pw")
os.environ["AI_DB_NAME"] = ITEST_DB

import psycopg  # noqa: E402

from agent_hub.config import WorkerSettings, load_providers  # noqa: E402
from agent_hub.llm.client import build_ai_client  # noqa: E402
from agent_hub.sources.db.mapper import DbL1Mapper  # noqa: E402
from agent_hub.sources.db.pool import create_pool  # noqa: E402
from agent_hub.sources.db.source import DbPullSource  # noqa: E402
from agent_hub.tools.base import DefaultNewsTools  # noqa: E402
from agent_hub.worker.loop import process_one  # noqa: E402
from agent_hub.worker.state import WorkerState, make_lock_token  # noqa: E402

NEWS_TEXT = (
    "OpenAI 今日发布 GPT-5.5，官方称在数学推理基准 AIME 上达到 98.2%，"
    "较上一代提升 6 个百分点，同时推理成本下降约 40%。该模型即日起向 "
    "ChatGPT Pro 用户开放，API 定价为每百万输入 token 5 美元。"
)


def settings() -> WorkerSettings:
    return WorkerSettings(
        run_mode="db", db_host="127.0.0.1", db_port=5432, db_name=ITEST_DB,
        db_user="ai_worker", db_password=os.environ["AI_DB_PASSWORD"],
        claim_batch_size=1, item_budget_ms=240000,
    )


async def seed() -> tuple:
    async with await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True) as conn:
        for t in ("news_positions", "processed_news", "tasks", "raw_items", "sources"):
            await conn.execute(f"DELETE FROM {t}")
        sid, rid, tid = uuid4(), uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO sources (id,type,display_name,identity,config,domain_tags)"
            " VALUES (%s,'x_twitter','验收源','acceptance','{}'::jsonb,'[\"AI\"]'::jsonb)", (sid,))
        await conn.execute(
            "INSERT INTO raw_items (id,source_id,source_item_id,content,published_at,"
            " source_item_url,l0_status,l1_status,l1_attempt,process_type)"
            " VALUES (%s,%s,%s,%s::jsonb,now(),%s,'passed','queued',0,'ai')",
            (rid, sid, f"acc-{rid.hex[:8]}",
             json.dumps({"text": NEWS_TEXT, "author_username": "OpenAI"}),
             "https://x.com/OpenAI/status/1"))
        await conn.execute(
            "INSERT INTO tasks (id,type,status,raw_item_id,source_id,priority,run_after,"
            " attempt,max_attempts) VALUES (%s,'l1_ai_process','queued',%s,%s,100,now(),0,3)",
            (tid, rid, sid))
        return tid, rid


async def main():
    providers = load_providers()
    print(f"provider: {[p.name for p in providers]}")
    if not providers:
        sys.exit("无 LLM provider 配置")

    tid, rid = await seed()
    print(f"已造数 raw_item={rid}\n新闻原文：{NEWS_TEXT[:50]}...\n")

    s = settings()
    pool = await create_pool(s)
    src = DbPullSource(pool, s, make_lock_token("acceptance"))
    state = WorkerState(lock_token="acceptance#1")

    t0 = time.monotonic()
    items = await src.fetch_batch(1)
    print(f"claim 到 {len(items)} 条，耗时 {time.monotonic()-t0:.2f}s")

    t1 = time.monotonic()
    await process_one(src, DbL1Mapper(), items[0], state, s,
                      client=build_ai_client(), tools=DefaultNewsTools())
    print(f"处理 + 写回完成，耗时 {time.monotonic()-t1:.1f}s\n")

    async with await psycopg.AsyncConnection.connect(ADMIN_DSN) as conn:
        cur = await conn.execute(
            "SELECT r.l1_status, t.status, p.title, p.summary, p.analysis,"
            " p.score_dimensions, p.tags_v2, p.language, p.needs_context, p.score_total,"
            " p.translation, p.published_at IS NOT NULL"
            " FROM raw_items r JOIN tasks t ON t.raw_item_id=r.id"
            " LEFT JOIN processed_news p ON p.raw_item_id=r.id WHERE r.id=%s", (rid,))
        row = await cur.fetchone()

    (l1, tstat, title, summary, analysis, dims, tags, lang, needs, total, trans, has_pub) = row
    print("=" * 62)
    print(f"raw_items.l1_status : {l1}")
    print(f"tasks.status        : {tstat}")
    print(f"标题                : {title}")
    print(f"摘要                : {summary}")
    print(f"分析                : {(analysis or '')[:100]}")
    print(f"四维评分            : " + ", ".join(
        f"{k}={v.get('score')}" for k, v in (dims or {}).items()))
    for k, v in (dims or {}).items():
        print(f"    {k:12} {v.get('score')} — {v.get('reason','')[:40]}")
    print(f"标签                : { {k: v for k, v in (tags or {}).items() if k != 'processing'} }")
    print(f"processing 标记     : {(tags or {}).get('processing')}")
    print(f"language            : {lang}   needs_context: {needs}")
    print(f"score_total         : {total}  ← 应为 None（归 xiaobao 加权）")
    print(f"published_at 已写   : {has_pub}")
    print("=" * 62)
    await pool.close()


asyncio.run(main())
