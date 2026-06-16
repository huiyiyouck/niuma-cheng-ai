# niuma-cheng-ai

niuma-cheng 生态的 **AI 处理中枢**（Agent Hub）。新闻平台 [niuma-cheng-xiaobao](../niuma-cheng-xiaobao)（Node.js）通过 HTTP 调用本服务完成新闻 L1 处理；后续承载平台多种 AI 能力（影响力扩展、时间线复盘等）。

> 方案来源：niuma-cheng-xiaobao `docs/progress/ad-hoc/2026-06-16-spike-langgraph-agent-hub-proposal.md`（§12 为 Owner 二轮收敛的真源）。

## 定位（已拍板 D1–D5）

- AI 处理与新闻平台**解耦**为独立服务，平台退化为调用方。
- 技术栈：**Python + FastAPI + LangGraph**（新闻平台保持 Node.js）。
- AI 推理走**外部 API**，本服务为 IO-bound 协调者（4 核 8G 可承载）。
- 新闻平台 `tasks` 为业务真源，本服务 run 仅为处理证据。
- 第一版只做 `news-l1`，**不为无关项目做抽象**（避免过早泛化）。

## ⚠️ 当前状态：骨架 / 占位

已就位：跨服务契约（`L1Input` / `L1Output`）、API 入口（`POST /v1/runs/news-l1`）、固定流水线结构（`kb_search → link_read → web_search → llm_process`）、冒烟测试。

**未实现（占位）**：各节点真实逻辑——LLM 调用、外部检索、链接读取。`llm_process` 当前返回结构化占位输出，`tags.processing` 标记 `["engine:agent_hub", "stub"]`。

## 结构

```
src/agent_hub/
  main.py            FastAPI 入口（/health, POST /v1/runs/news-l1）
  config.py          环境变量（外部 LLM API / 搜索）
  schemas.py         L1Input / L1Output 跨服务契约
  graphs/news_l1.py  news-l1 LangGraph 固定流水线
tests/test_health.py 骨架冒烟测试
```

## 运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 启动
PYTHONPATH=src uvicorn agent_hub.main:app --reload --port 8100

# 测试
PYTHONPATH=src pytest -q

# 冒烟
curl localhost:8100/health
```

## 待 Architect 架构定稿（提案 §12.5 / §12.7）

- 同步 vs 异步对接（回调 / 轮询）；新闻平台 worker 提交 run 后如何回填。
- run 状态持久化 / LangGraph checkpoint（独立库 or 复用 PostgreSQL）。
- 超时回收、幂等去重、背压。
- 评分加权 `score_total` 留新闻平台，本服务只产四维 `score` + `reason`（§12.6）。
- news-l1 各节点真实逻辑实现 + 错误类型细分。
