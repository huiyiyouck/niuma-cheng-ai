# 临时工作记录

## 基本信息
- 日期：2026-06-29
- 模式：Product Brief / 产品方案
- 执行角色：PM（产品经理，ck）
- 是否进入迭代：否（理清定位，为后续 v0.1 标准迭代与 REQ-002 架构调研做输入）
- 关联迭代：v0.1（待启动）
- 当前状态：已定稿（Owner 2026-06-29 拍板，经两轮 review 逐项采纳反馈），待按待办执行跨仓留痕

## 背景

Owner 在本会话要求理清 niuma-cheng-ai 的**产品定位**与**数据架构定位**（后者属 Architect 职责，本 Brief 只定产品定位）。

调研 coordination 真源（`contracts/news-l1.md`、`decisions/0001-ai-hub-split.md`、`REQUESTS.md`、`communications/REQ-001-news-l1.md`、`STATUS.md`）后确认两件关键事实：

1. **已有拍板决策 D5**（`decisions/0001`，2026-06-16，Owner 二轮讨论）：「中枢定位承载 **xiaobao 平台**的多种 AI 能力，**不做泛化的多项目通用平台**」。
2. **REQ-002**（xiaobao Architect 提报、Owner 指派给 ai、尚未承接）：AI 处理架构调研，要求 ai 调研参考项目 `Horizon` / `ai-news-aggregator`、回答 4 个架构岔路口、形成自己的架构方案，是 REQ-001「L1 真实化」的前置。

## 操作/产出

### 定位决策（Owner 2026-06-29 拍板）

Owner 明确**取代 D5**，把 ai 定位升级为：

> **niuma-cheng 生态内部的通用 AI 处理中枢（Agent Hub）** —— 生态内多个项目未来都可以调用同一个 AI 处理服务；当前首个、且唯一真实的落地需求是为 **xiaobao** 做新闻处理（评分 + 处理 = REQ-001）。

定位边界澄清：

- 「生态**内部**通用」指生态内多项目可复用同一服务，**不是**对外开放的泛化平台、多租户平台或开放 SaaS。它表达的是「未来多个内部项目可调用同一 AI 处理服务」，不是现在就建设泛化平台。
- 「Agent Hub」是产品 / 服务代号，**不预设实现形态**；是否采用真 Agent 自主工具循环、还是确定性 staged 编排，由 REQ-002 架构调研决定（REQ-002 第一个岔路口正是「确定性 staged 编排 vs 真 agent 自主工具调用」）。

与 D5 的关系：本次仅 **supersede（取代）D5**「不做泛化多项目通用平台」一条；`decisions/0001` 的 **D1–D4 继续有效**（独立服务、xiaobao 用 Node / ai 用 Python、异步调用、`tasks` 为 xiaobao 业务真源）。这是跨 xiaobao/ai 的决策变更，须在 coordination `decisions/` 留痕（详见后续待办）。

### 落地策略（Owner 原话）

「先搭骨架，然后做真实的需求 —— 小报的评分和处理。」拆解为两层：

- **骨架层**：按「多调用方 + 多任务类型」预留**抽象边界**——在接口分发、任务注册、调用方标识、运行记录模型上留扩展点。当前对外契约和实现**仍只暴露 `POST /v1/runs/news-l1`**（固定 endpoint，见 `contracts/news-l1.md`、`src/agent_hub/main.py`）；是否演进为 `POST /v1/runs/{task_type}` 这类通用路由，由 REQ-002 / v0.1 设计决定 —— **不把未实现的通用路由写成既成事实**。具体架构（确定性编排 vs 真 agent、落盘可重入、与 tasks 调度合流、LLM 客户端自研 vs 移植等）由 **Architect 在 REQ-002 调研中定**，本 Brief 不替架构拍板。
- **真实需求层**：v0.1 把 REQ-001 的 news-l1 从 stub 做成真实全量 —— 四维原始评分（`score`+`reason`）、五类标签、摘要、翻译、按需工具调用（KB 检索 / 链接读取 / Web 搜索）。`score_total` 加权仍留 xiaobao（news-l1 契约职责边界不变）。

### 范围边界

**本阶段（定位 + v0.1）做：**
- 确立「生态内部通用 AI 处理中枢」定位并留决策痕迹。
- 骨架按通用预留扩展点（接口分发 / 任务注册 / 调用方标识 / 运行记录模型），但**只实现 news-l1 一个 task-type**。
- REQ-001 news-l1 真实化（评分 + 处理）。

**本阶段不做（YAGNI）：**
- 不为 xiaobao 之外**尚不存在**的第二个调用方/项目写具体 task、不写空泛能力（仅预留扩展点，不写实现）——Owner 已确认当前生态内无第二个 AI 需求在排队。
- 不做 `score_total` 加权（留 xiaobao）。
- 不替架构拍板（数据架构定位归 Architect / REQ-002）。

### 前置依赖

- REQ-002 架构调研结论（数据架构定位）—— 决定骨架与 news-l1 的实现形态，是 v0.1 PRD 的前置输入。
- coordination 决策变更留痕（取代 D5）。

## 验证证据
- 已验证：定位结论与 Owner 2026-06-29 当面拍板 + review 反馈一致；调研覆盖 coordination 全部相关真源（契约/决策/需求池/沟通/状态）；「当前仅固定 endpoint」一条经核对 `contracts/news-l1.md` 与 `src/agent_hub/main.py` 属实。
- 未验证原因：架构可行性（落盘可重入、4 核 8G 承载等）属 REQ-002 调研范围，本 Brief 不验证。

## 结论

产品定位定为「niuma-cheng 生态内部的通用 AI 处理中枢」，落地按「通用骨架预留扩展点 + 先做 xiaobao news-l1 真实需求」。该定位**取代（supersede）已拍板 D5**（仅 D5，不动 D1–D4），需走决策变更留痕。数据架构定位另由 Architect 承接 REQ-002 产出。

## 后续建议
- 是否建议升级为标准迭代：是 —— REQ-001 news-l1 真实化转 v0.1 标准迭代；但**前置 REQ-002 架构调研**，待数据架构定位出来再创建 v0.1 PRD。
- 建议起始角色：Architect（承接 REQ-002 做数据架构调研）→ 回 PM 创建 v0.1 PRD。

### 待办清单（跨仓 / 跨角色，按下列顺序执行）

执行顺序：**①决策留痕 → ②承接 REQ-002 → ③元信息台账 → ④Architect 架构调研 → ⑤PM 更新 project-context / 创建 v0.1 PRD**。其中 ⑤ 的 v0.1 PRD 须等 ④ 至少给出架构结论后再写。

| # | 动作 | 写入位置 | 归属 | 备注 |
|---|------|----------|------|------|
| 1 | 决策变更留痕：新建 `decisions/0002`（标题示意「ai 定位升级为生态内部通用 AI 处理中枢」，supersede 0001-D5），并在 0001 标注 D5 被 0002 取代 | coordination `decisions/` + `decisions/README.md` | PM（记录 Owner 决策） | 跨 xiaobao/ai；文档措辞用「supersede / 取代 D5」；标注对 xiaobao：调用关系 / `score_total` / D1–D4 不变；需确认是否知会 xiaobao 会话 |
| 2 | 正式承接 REQ-002：REQUESTS.md 回填承接方/状态 + 建 `communications/REQ-002-*.md` | coordination | PM 做承接登记 | 实质产出（架构方案）归 Architect；调研范围因升级生态内部通用而扩大 |
| 3 | 元信息变更台账：定位 old（xiaobao AI 中枢）→ new（生态内部通用 AI 处理中枢），登记 STATUS.md → 触发 PROJECTS.md → 根索引同步 | coordination `STATUS.md` | PM 登记 | 三方接力，见 `cross-project-collaboration.md §项目元信息同步` |
| 4 | 数据架构调研（REQ-002）：读 Horizon/aggregator、答 4 岔路口 + 生态内部通用维度，出数据架构方案 | ai 本地 ad-hoc | **Architect** | 切角色 |
| 5 | 更新 `project-context.md` 定位/业务边界；架构结论出后创建 v0.1 PRD | ai 本地 | PM | v0.1 PRD 前置 #4 架构结论 |

## 收尾归档
- 收尾日期：2026-06-29
- 最终状态：已完成 —— 产品定位定稿（两轮 Owner review）+ ①决策留痕 ②REQ-002 承接 ③元信息台账已落 coordination 并 push；数据架构定位（④）、v0.1 PRD（⑤）转后续角色，见待办表。
- 操作/产出摘要：见正文。coordination 改 7 文件（decisions/0002 + 0001 标注 + README + REQUESTS + communications/REQ-002 + communications/README + STATUS）。
- 已更新当前角色日志：是（`roles/pm.md` 2026-06-29 条）
- 其他角色待补充/确认：Architect 承接 REQ-002 出数据架构方案；元信息第 2 棒（协调会话改 PROJECTS.md）、第 3 棒（根会话订正根索引）
- 已更新 `docs/progress/INDEX.md`：是
- 已更新知识库：否 —— 定位决策已在 coordination `decisions/0002` + 本 Brief 留痕，无需重复沉淀
- 关联 commit：coordination `7fa7820`（决策/承接/台账，已 push）；ai 本地：本次 PM 收尾提交
- 下一次启动建议：切 Architect 承接 REQ-002 做数据架构定位（读 Horizon/aggregator、答 4 岔路口、出方案）→ 回 PM 创建 v0.1 PRD
