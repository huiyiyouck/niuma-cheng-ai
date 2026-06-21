# 项目上下文

> 项目适配层，只写**项目事实**，不写通用工作流规则，也不写当前阶段 / 迭代 / Review 状态。
>
> **启动契约**：Agent 读「本文件 + `docs/progress/INDEX.md`」后应能回答 8 个问题——
> ① 这是什么项目 ② 技术栈与启动方式 ③ 代码大致在哪（模块地图）④ 依赖哪些外部系统 ⑤ 做什么 / 不做什么 ⑥ 哪些路径受保护、有什么特有约束（①-⑥ 看本文件）⑦ 当前卡在哪 ⑧ 下一步（⑦-⑧ 看 INDEX）。
> 填写时保证每个字段能被一个新接手的 Agent 直接看懂，未知写「待定」、无则写「无」。

## 项目一句话
niuma-cheng 生态的 **AI 处理中枢**（Agent Hub）：通过 HTTP 为新闻平台 xiaobao 提供新闻 L1 的 LLM 处理（四维评分 / 标签 / 摘要 / 翻译），供 xiaobao 这一调用方解耦使用。

## 技术栈
Python + FastAPI + LangGraph；AI 推理走外部 OpenAI 兼容 API（本服务为 IO-bound 协调者，不自托管模型）。

## 架构与模块地图
> 关键目录 / 模块 → 职责，让 Agent 不通读代码就知道改动该去哪。
- `src/agent_hub/main.py` — FastAPI 入口（`/health`、`POST /v1/runs/news-l1`）
- `src/agent_hub/config.py` — 环境变量（外部 LLM API / 搜索）
- `src/agent_hub/schemas.py` — `L1Input` / `L1Output` 跨服务契约
- `src/agent_hub/graphs/news_l1.py` — news-l1 LangGraph 固定流水线（`kb_search → link_read → web_search → llm_process`）
- `tests/test_health.py` — 骨架冒烟测试
- ⚠️ 当前为骨架：各节点真实逻辑（LLM 调用 / 外部检索 / 链接读取）未实现，`llm_process` 返回结构化占位输出（`tags.processing` 含 `stub`）。

## 启动方式
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

## 关键配置 / 环境变量
> 见 `.env.example`，只写名称与用途，不写密钥值。
- `HOST` / `PORT` — 服务监听地址（默认 `127.0.0.1:8100`）
- `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `L1_LLM_MODEL` — 外部 OpenAI 兼容 LLM API 配置
- `LLM_TIMEOUT_MS` — LLM 调用超时
- `WEB_SEARCH_MAX_RESULTS` — Web 搜索返回条数上限

## 外部依赖与集成
- 调用方 `xiaobao`（牛马成新闻平台，Node.js）：通过 `POST /v1/runs/news-l1` 调用本服务；其 `tasks` 为业务真源，本服务 run 仅为处理证据。
- 外部 LLM API（OpenAI 兼容）：L1 推理引擎。
- 外部 Web 搜索：按需工具调用。
- `coordination_root`：`/root/Project/niuma-cheng-coordination`（本地 checkout，跨项目契约 / 状态单一真源；跨项目任务据此定位，见 `cross-project-collaboration.md`）。

## 业务边界
- 本项目做：L1 新闻 LLM 处理 —— 四维 `score` + `reason`、标签、摘要、翻译，以及按需工具调用（KB 检索 / 链接读取 / Web 搜索）。
- 本项目不做：评分加权 `score_total`（留在调用方 xiaobao）；信息源管理、抓取调度、L0 分类、新闻展示（均属 xiaobao）。

## 受保护路径
> 删除需走架构师 Review 门禁（见 `conventions.md §受保护路径删除`）。由 Architect 在 ADR 明确后回填。
- 缺省最小集：业务源码（`src/agent_hub/`）/ 部署配置（`.env.example`、`requirements.txt`）/ 工作流框架（`docs/baseline`、`docs/templates`、入口文件 `CLAUDE.md`/`AGENTS.md`）

## 项目特有约束 / 领域术语
- `news-l1` 跨服务契约单一真源在 coordination 仓 `contracts/news-l1.md`，改 API / schema / 字段语义前先改契约再改代码。
- 四维 `score`：本服务产出四个维度评分 + `reason`，**不**做加权汇总。
- `L0` / `L1`：L0 为 xiaobao 侧规则分类，L1 为本服务侧 LLM 处理。
- run 仅为处理证据，非业务真源（业务真源是 xiaobao 的 `tasks`）。

## 状态说明
项目级当前状态见 `docs/progress/INDEX.md`；迭代阶段细节见 `docs/progress/iterations/vX.Y.md`。本文件不写状态。
