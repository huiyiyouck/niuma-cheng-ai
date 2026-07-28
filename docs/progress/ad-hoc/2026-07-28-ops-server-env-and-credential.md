# 临时工作记录

## 基本信息
- 日期：2026-07-28
- 模式：Ops Task（服务器部署环境准备 + `ai_worker` 口令注入）
- 执行角色：DevOps（运维/部署工程师）
- 是否进入迭代：是（v0.2 的「实现阶段开工前置」两项，PRD R4 §5 待办，INDEX 跨任务待办 P0）
- 关联迭代：v0.2（PRD R4 已定稿，进设计阶段）
- 当前状态：**两项均已完成**；附带发现 2 项阻塞/高风险问题，其中 1 项**阻塞 C-6 行锁实证**

## 背景

PRD R4 §5 把两项前置从「部署阶段」前移为「实现阶段开工前置」（DevOps R3 问题 1 + Developer R3 问题 3 合并处置）：

1. **服务器部署环境** —— ai 至今只在开发机（macOS）跑过，而共享库 `news_test` 与 xiaobao 同在一台 Linux 服务器上，PRD 说的 `host=127.0.0.1` 是相对该服务器而言。
2. **`ai_worker` 口令注入** —— 同机直读 `/root/.secrets/ai_worker_news_test.pw` 写入部署目录 `.env`，不经对话传递。

两项共同阻塞 C-6 行锁实证与任何联调冒烟。

## 一、目标服务器定位

| 项 | 结论 | 依据 |
|---|------|------|
| 目标机 | **`zijie` / 115.191.43.79**（SSH config 别名） | `dig news.huiyiyou.cloud` → `115.191.43.79`；`workboard.huiyiyou.cloud` 同 IP |
| OS | Ubuntu 24.04 LTS（`x86_64`，kernel 6.8） | `uname -a` / `/etc/os-release` |
| PostgreSQL | `127.0.0.1:5432` 监听中（进程 `postgres`） | `ss -lntp` |
| Python | 3.12.3，`venv` 可用 | `python3 -V` |
| xiaobao 部署位置 | `/opt/news-aggregator`（remote = `niuma-cheng-xiaobao`） | `git remote -v` |
| 登录身份 | **root**（SSH config `User root`） | `id -un` |

> **安全观察（登记，不阻塞）**：ai DevOps 在该机为 root 登录，因此 PRD §5「授权形式二选一（按需 sudo / Owner 代拷）」在当前配置下**不适用**——已经是最高权限，最小权限原则未被满足。这是既有运维方式，非本次引入；若将来收紧，建议为 ai 建独立系统用户并只授予 `/root/.secrets/ai_worker_news_test.pw` 的读取权。

## 二、部署环境准备（已完成）

部署路径 **`/opt/niuma-cheng-ai`**（与 `/opt/news-aggregator`、`/opt/workboard-prod` 同级，沿用既有惯例）。

| 步骤 | 结果 |
|---|------|
| `git clone git@github.com:huiyiyouck/niuma-cheng-ai.git` | ✅ HEAD = `cc45cd3` |
| `python3 -m venv .venv` | ✅ |
| `pip install -r requirements.txt` | ✅ fastapi 0.140.0 / uvicorn 0.44.0 / langgraph 1.1.10 / pydantic 2.13.4 / httpx 0.28.1 / pytest 9.1.1 / python-dotenv 1.2.2 |
| `PYTHONPATH=src pytest -q` | ✅ **40 passed**（与 v0.1 基线一致，环境可用） |

**未完成项**：`.env` 中 LLM 相关变量（`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `L1_LLM_MODEL`）与 `TAVILY_API_KEY` / `KB_ADMIN_TOKEN` **留空待 Owner 提供**。v0.1 时这些取自 openclaw（火山 `doubao-seed-2.0-pro`），本次不擅自跨项目取用他人凭据。不影响 C-6 实证（纯 SQL，不经 LLM），但阻塞任何真实处理冒烟。

## 三、口令注入（已完成）

**执行方式**：源文件内容经 shell 命令替换直接写入 `.env`，**全程未回显、未落任何日志、未进入会话**。

```
printf 'AI_DB_PASSWORD=%s\n' "$(tr -d '\r\n' < /root/.secrets/ai_worker_news_test.pw)"
```

**落点与纪律核验**：

| 项 | 结果 |
|---|------|
| 路径 | `/opt/niuma-cheng-ai/.env` |
| 权限 | `-rw------- root root`（`umask 077` + 显式 `chmod 600`） |
| 口令长度校验 | 28 字符，与源文件 28 字节一致（无 `\r\n` 残留） |
| git 忽略 | `git check-ignore` 命中 `.gitignore:5`；`git status` 中 `.env` 出现 **0** 次 |
| 变量形态 | 按 O-7 **拆字段**：`AI_DB_HOST` / `AI_DB_PORT` / `AI_DB_NAME` / `AI_DB_USER` / `AI_DB_PASSWORD`，**未使用整串 DSN** |

> **与 PRD §5 措辞的一处偏差（须订正 PRD 或确认）**：PRD 写 `.env` 应在「**仓外**」，但 `config.py:16` 是无参 `load_dotenv()`，只会从 cwd 及父目录查找 `.env`；放仓外需要改代码或额外传绝对路径，属实现阶段决定。本次按 v0.1 现行做法放**仓内**（`/opt/niuma-cheng-ai/.env`），风险由 `.gitignore:5` + `chmod 600` 覆盖，已验证 `git status` 不显示。建议 PRD §5 把「仓外」改为「仓内且经 `.gitignore` 覆盖」，或在实现阶段引入 `ENV_FILE` 路径变量。

**连库与权限边界验证**（以 `ai_worker` 身份实连 `news_test`）：

| # | 验证 | 结果 |
|---|------|------|
| 1 | 连接与身份 | ✅ `ai_worker` / `news_test` |
| 2 | 读 `raw_items` 授权列 | ✅ 5 条 `process_type='ai' AND l1_status='queued'`（与 PRD §5 预置一致） |
| 3 | 读 v1.3 新 GRANT 的 `source_item_url` / `l0_label` | ✅ 154 条两列均非空 |
| 4 | 读 `tasks` | ✅ 可读（但见下方发现 A） |
| 5 | 越权对照：`SELECT ... FROM alerts` | ✅ `permission denied for table alerts` |
| 6 | 越权对照：`UPDATE raw_items SET process_type` | ✅ `permission denied for table raw_items` |

**结论：口令可用，权限矩阵与契约 v1.4 一致，越权拦截有效。**

## 四、附带发现（两项，均需 PM 转达 xiaobao）

### 发现 A（阻塞级）｜`tasks` 表中 `l1_ai_process` 类型记录数为 **0**，5 条预置队列按 AC-3.1 的 claim 逻辑永远领不到

实测 `news_test` 的 `tasks` 表 type 分布（全表 211 行）：

| type | status | 条数 |
|---|---|---|
| `fetch` | succeeded / failed | 52 / 4 |
| `l0_classify` | failed | 8 |
| `l1_process` | succeeded | 1 |
| `process` | succeeded | 146 |
| **`l1_ai_process`** | — | **0** |

而 `raw_items` 确有 5 条 `process_type='ai' AND l1_status='queued'`。两者对不上。

**后果有两层**：

1. **直接阻塞 C-6 行锁实证**。AC-3.7 的实证 SQL 是 `SELECT ... FROM tasks WHERE type='l1_ai_process' AND status='queued' ... FOR UPDATE SKIP LOCKED`——当前必然返回 **0 行**。0 行的情况下 `FOR UPDATE` 的权限检查**不会被触发**，因此**测不出**「列级 GRANT 是否支撑行锁」这个 C-6 的核心问题，实证会得到一个假的「通过」。
2. **worker 上线后会静默空转**。AC-3.1 明确「claim 以 `tasks` 表为准，不扫 `raw_items`」，且据 xiaobao Architect 的答复「`raw_items` 入库时尚无 task 的条目本就不该被领，ai 侧**不需要**孤儿探测」。按此实现，这 5 条预置数据对 worker 完全不可见——冒烟会表现为「worker 活着、队列为空」，而实际队列非空。

**注意这不是 C-5 的毫秒级窗口**（那是 xiaobao 已承诺包进事务的并发缺陷），而是**造数脚本 `seed_ai_queue_test.sql` 本身只造了 `raw_items`、没造配套的 `l1_ai_process` task**。

**需要 xiaobao 确认**：① 造数脚本是否遗漏建 task；② 若其正式链路是「L0 通过后由应用层建 `l1_ai_process` task」，则预置数据须补建对应 task 行才能用于冒烟；③ 顺带确认 type 字面量到底是 `l1_ai_process` 还是复用既有的 `l1_process`（表中已存在后者 1 条 succeeded，契约与 PRD 用的是前者）。

### 发现 B（高）｜`l0_label` 在真实数据中只有 `direct_display` 一个取值，`domain_tags` 会恒为噪声——比 R3 判断的「恒空」更糟

| 库 | `l0_label` 取值分布 |
|---|---|
| `news_test` | `direct_display` × 154（**唯一取值**，无其它） |
| 生产 `news` | `direct_display` × 637、`NULL` × 120（**同样只有这一个非空值**） |

PRD 的 C-1 闭合结论是「已 GRANT `l0_label` → `domain_tags` **不再恒空**」，AC-8.2 记为「单值 varchar，语义**近似**但非等价」。**实测数据推翻了这个判断**：`l0_label` 不是领域分类结果，而是一个**流程标记**（L0 判定为"直接展示"），全库无第二个取值。

后果：适配层按 AC-8.2 映射 `domain_tags = [l0_label]` 后，每条新闻的 `domain_tags` 恒为 `['direct_display']`。而 `domain_tags` 会流进 **prompt** 与 **KB 检索查询**（`news_l1.py:311` `_build_query` / `:320` `_build_kb_query`），即：

- 相比 R1 判断的「恒空」，**这更糟**——恒空时 `inp.domain_tags or None`（`news_l1.py:206`）会把它归零并被正确忽略；而 `['direct_display']` 是**真值**，会穿过该判断，把一个无信息量的流程标记当作领域标签塞进推理与检索输入。
- 这与 Developer R3 问题 5 指出的 `['']` 穿透是同一类问题，但 `['']` 至少还能靠空串检查拦掉，`'direct_display'` 拦不掉。

**建议**：在 xiaobao 确认 `l0_label` 语义前，适配层应**将 `direct_display` 视同无分类、映射为 `[]`**（与 NULL / 空串同等处理），而不是照搬进 `domain_tags`。该处置须写进 AC-8.2 或设计阶段的入向映射规则。**需 PM 向 xiaobao 确认**：`l0_label` 是否还有其它取值（是否存在未启用的分类枚举）、是否另有列承载真正的 L0 领域分类结果。

### 附带印证：C-12 已被实测确认

`tasks` 表实测 `max_attempts=5`、`priority=100`（`l1_process` 样本），印证 Architect R3 的 C-12——契约写「最大尝试 3」而 schema 默认 5 不一致。PRD AC-5.1 已定「读 `tasks.max_attempts` 列、禁止硬编码 3」，方向正确，实测支持该决定。

## 五、结论与下一步

**本次两项任务已完成**：服务器部署环境就绪（40 单测通过）、口令注入完成并经连库与越权双向验证。

**下一步不可直接执行 C-6 实证**——发现 A 使实证 SQL 必然返回 0 行、测不出行锁权限。三条路径任选其一：

1. **（推荐）** PM 转达发现 A，请 xiaobao 为 5 条预置 `raw_items` 补建 `l1_ai_process` task 行（或修正造数脚本后重跑），之后再执行 AC-3.7 的 6 步实证。
2. 若短期内拿不到，可退而求其次：以 `ai_worker` 对 `tasks` 表**任意一行既有记录**（如 `type='process'`）做 `FOR UPDATE` 权限探测——能验出「列级 GRANT 是否支撑行锁」这个核心问题，但验不出 claim 条件与 `SKIP LOCKED` 的并发语义。**须在回帖中写明该实证是降级版本**，不得当作完整 C-6 结论。
3. 等实现阶段 ai 侧具备写 task 的能力后再测——不可行，ai 对 `tasks` **无 INSERT 权限**（契约权限矩阵）。

**另需 Owner 提供**：LLM 相关凭据（`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `L1_LLM_MODEL`）与 `TAVILY_API_KEY` / `KB_ADMIN_TOKEN`，否则无法做任何真实处理冒烟。

**登记给 PM 的跨项目转达项**：发现 A、发现 B（两者均属 `news-l1-db` 契约/造数范畴，写 coordination `communications/` 归 PM，不在 DevOps 权限内）。
