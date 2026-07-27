# 项目进度索引

> 本文件是项目级当前状态的唯一真源。启动时 Agent 读此文件即应能判断"现在卡在哪、下一步做什么"，不需要再去翻迭代记录。

## 当前项目状态

- 当前迭代：v0.2（进行中，2026-07-25 范围重排：主线改为承接 REQ-003 数据库边界异步解耦）
- 当前模式：标准迭代（进行中）
- 当前阶段：v0.2 **PRD 阶段 — R4 已出，待三方复审**（R1/R3 三方均未通过，R2 未经 Review 即被外部事实推进；R4 于 2026-07-27 按三方 R3 意见收敛，10 高 + 6 中低全部处置）
- **本项目核心开发原则（Owner 2026-07-26 定，优先于成本考量）**：以基础夯实、可扩展性强的方式开发，而不是图便捷；宁可现在多干活，也要让系统更健全、后期接入更友好。已写入 `v0.2-prd.md` §0，后续所有技术取舍按此裁定。三方 R3 均明确认可该准则的三处裁定。
- 阻塞项：**无阻塞定稿项**。契约侧 4 条阻塞已于 2026-07-27 全闭、契约升至 **v1.4**；R3 三方 10 条高严重度全为增补型、已在 R4 处置完毕。
- **前置待办（DevOps，已前移为「实现阶段开工前置」，不再排部署阶段）**：
  1. **服务器部署环境** —— 实查本机为 macOS、无 `/root`、`5432` 无监听、无 `scripts/`·`deploy/`；PRD 说的「与 xiaobao 同机」指一台 **Linux 服务器**，而 ai 至今只在开发机跑过。须明确目标机 / 代码上机方式 / Python 环境 / `.env` 与日志落点 / 启动命令。（原 PRD 称「唯一剩余外部依赖=口令」是事实性错误，已订正）
  2. **`ai_worker` 口令注入** —— 同机直读 `/root/.secrets/ai_worker_news_test.pw` 写入部署目录 `.env`；授权形式二选一（按需 sudo / Owner 代拷），**不给全量 sudo**；`.env` 是快照，对方轮换口令后须重注入 + 重启。
  两项**不阻塞设计阶段开工**，但共同阻塞 C-6 实证与任何联调冒烟。
- **联调判读须知**：`score_total` 在 database 模式**没有触发点**（xiaobao 的 `calcScoreTotal` 只挂 HTTP 路径），ai 写回后该列保持 NULL → 新闻按分排序沉底、前端评分徽章显示 0。**这不是 ai 的缺陷**，xiaobao 已上报其 PM 补触发点。
- **本迭代最大技术风险**：**async 改造的回归**（O-8，P0）。三方判断一致「风险在回归不在重写」。客观兜底已从开放问题提升为验收标准——**AC-9.4 黄金样本外部化**（改造前在 v0.1 基线录 `L1Output` JSON 快照，改造后同输入同 mock 重跑逐字段比对），因为约 21/36 例单测的 fake 必须随 async 改写，只靠单测自证属循环论证。
- 待转达 xiaobao 3 条（均不阻塞，ai 已按明确假设实现）：**C-11** `tasks.priority` 方向语义、**C-12** 退避表长 3 < `max_attempts` 默认 5 且契约「最大 3」与 schema 默认 5 不一致、**C-13** `source_item_url` 是否保证带协议前缀 + 登记「`raw_item_id` 唯一约束是 ai 写回幂等前提」。另 C-6 待 ai 实证（**已有 fallback，不阻塞实现**）、Q-1 待对方 PM 表态。
- 下一步入口：① **切 Architect / Developer / DevOps 做 PRD R4 复审**（各自复核其 R3 意见的落实）；② PM 转达 C-11~C-13；③ DevOps 备服务器环境 + 注入口令 → 执行 C-6 实证（6 步方案见 PRD §5，全程事务内 `ROLLBACK` 不消耗 5 条预置队列；结论回帖归 PM）；④ R4 定稿后进设计阶段：O-2 协议按职责分层、O-6 事务与连接（连接不得跨 `await` 长持）、**O-8 async 切分与回归（P0）**、O-9 驱动选型（倾向 psycopg3 async）、O-10 `locked_by` 标识规则；⑤ 实现阶段按 §8 五块切片推进。

> 当迭代激活后，`当前阶段` 必须写清楚具体状态，例如：
> `设计阶段 — Review R2，Architect 等待 PM 和 Developer 反馈`
> `实现阶段 — R1 已提交，等待 Tester 和 Architect Review`
> 这能避免 Agent 仅为了解状态就去读完整迭代记录。

## 版本列表

> 首个迭代版本号建议为 `v0.1`，后续版本号由 PM 在 PRD 中决定。不强制 SemVer。

| 版本 | 迭代记录 | PRD | UI | 设计文档 | Summary | 状态 |
|------|----------|-----|----|----------|---------|------|
| v0.2 | [v0.2.md](iterations/v0.2.md) | [v0.2-prd.md](iterations/v0.2-prd.md) | 纯后端（无界面） | — | — | 进行中（PRD R4 已出，待三方复审；无阻塞定稿项，契约 v1.4） |
| v0.1 | [v0.1.md](iterations/v0.1.md) | [v0.1-prd.md](iterations/v0.1-prd.md) | 纯后端（无界面） | [v0.1-design.md](iterations/v0.1-design.md) | [v0.1-summary.md](iterations/v0.1-summary.md) | 已关闭（2026-07-04，[自测报告](iterations/v0.1-test-report.md)） |

## 当前 Change Notes

> v0.1 迭代已关闭，CN-001 / CN-002 已随 v0.1 归档。

| Change Note | 关联工作 | 状态 | 下一步 |
|-------------|----------|------|--------|

## 当前非迭代工作

| 日期 | 模式 | 记录 | 状态 | 下一步 |
|------|------|------|------|------|
| 2026-06-29 | Tech Spike·REQ-002 数据架构调研 | Architect 调研 Horizon/aggregator，答 4 岔路口 + 生态骨架接缝，见 `ad-hoc/2026-06-29-spike-req002-data-architecture.md` | 已完成 | 回 PM 创建 v0.1 PRD；设计阶段落岔路口①③ 的 ADR |
| 2026-06-29 | 跨项目协作·产品定位升级 + REQ-002 承接 | 定位 Brief `ad-hoc/2026-06-29-product-brief-positioning.md`；coordination `decisions/0002` + `REQUESTS` + `STATUS` 台账（push `7fa7820`） | 已完成 | 切 Architect 做数据架构定位（REQ-002）；元信息同步第 2/3 棒转协调/根会话 |
| 2026-06-22 | 框架维护·BCR-002 回流 | baseline 同步至 `agent-workflow@1b01fba`（BCR-002 communications 按需求一份），见 PM 日志 | 已完成 | coordination BCR-002 已置「已回流下游」 |
| 2026-06-22 | 框架维护·工作流真源同步 | baseline 同步至 `agent-workflow@c8c66ce`（P8 BCR 机制），见 PM 日志 | 已完成 | 框架变更今后走 `BCR-###` |
| 2026-06-22 | 跨项目协作·需求承接 | coordination `REQUESTS.md`/`communications/xiaobao__ai.md`/`STATUS.md` | 已完成 | 待启动 v0.1 标准迭代 |

## 最近收尾摘要

| 日期 | 角色 | 工作 | 结论 | 下一步入口 |
|------|------|------|------|------------|
| 2026-07-04 | PM | 迭代关闭检查 + 收尾归档：修 test-report 小问题（Architect 状态表 / 36→40 passed）、v0.1 部署就绪 + 关闭归档区、CN-001/CN-002 归档、生成 v0.1-summary.md、更新 INDEX、更新 PM 日志、coordination REQ-001 置已关闭 | v0.1 已关闭 | v0.2 立项（PM，待 Owner 确定范围）；部署阶段 DevOps 托管化 + 多 provider |
| 2026-07-04 | Developer | 收尾铺写：同步 test-report 元信息（40 passed / 文档定稿 / D-1 闭环 / D-3 登记）、v0.1.md 部署就绪检查与迭代关闭归档、INDEX.md 状态、Developer 日志；核实 coordination 联调文档完整（2026-07-04 端到端 4 条用例通过，Owner 抽样验收通过）；区分 Developer 代码侧（logging/耗时）vs DevOps 运维侧（托管化/多 provider）发布检查项归属 | 已收尾（Developer 侧铺写完成） | Owner 同步验收状态并触发迭代关闭检查；R2/下一迭代处理发布检查项 + Architect 观察项 + D-2/D-3 |
| 2026-07-04 | DevOps | 实现 R1 Review（部署 / 环境变量 / 密钥注入 / 健康检查 / 发布风险 / 回滚条件）：两方通过，实现 R1 定稿；4 条发布检查项跟踪到部署阶段 | 已收尾（实现 R1 定稿） | Owner 验收；部署就绪检查处理 4 条发布检查项 |
| 2026-07-02 | DevOps | 同步最新 + 收尾复核：`git pull --rebase` 已是最新；`127.0.0.1:8100` `/health` 200；`127.0.0.1:8001` 当前监听 | 暂停待续（迭代未关闭） | xiaobao 确认配置后做 KB/端到端联调；Architect/DevOps 复核实现 R1 |
| 2026-07-01 | Developer+DevOps | v0.1 实现 R1（S1~S5，含 CN-002 KB 接入，40 passed）+ ai 服务部署测试环境 `127.0.0.1:8100`（火山 LLM，news-l1 真实冒烟 succeeded）+ 回填 coordination | 暂停待续（迭代未关闭） | xiaobao 配 `AI_HUB_BASE_URL`+起 8001 端到端联调；Architect/DevOps 复核实现 R1 |
| 2026-06-29 | Architect | REQ-002 数据架构调研：4 岔路口已答 + 生态骨架接缝（见 `ad-hoc/2026-06-29-spike-req002-data-architecture.md`） | 已完成（待 Owner/PM Review） | PM 创建 `v0.1-prd.md`；coordination REQ-002 回执待跟进 |
| 2026-06-29 | PM | ai 产品定位升级生态内部通用 AI 中枢 + REQ-002 承接 + 元信息台账（coordination push `7fa7820`） | 已完成 | 切 Architect 做数据架构定位（REQ-002）→ PM 创建 v0.1 PRD |
| 2026-06-22 | PM | BCR-002 真源回流到 ai baseline → `agent-workflow@1b01fba` | 已完成 | BCR-002 已闭环；REQ-001 下一步不变 |
| 2026-06-22 | PM | 工作流真源同步 baseline → `agent-workflow@c8c66ce`（P8 BCR 机制） | 已完成，已 commit/push | 框架变更今后走 `BCR-###` |
| 2026-06-22 | PM | REQ-001 正规提报 + ai PM 承接留痕（跨项目协作） | 已完成，两仓已 commit/push | 待启动 v0.1 标准迭代 / 更新项目定位 |

## 跨任务待办

> 列入此表通常说明事项跨多个任务、归属角色明确但尚未启动；
> 若已有可独立的 ad-hoc 或基线修正提案，优先走对应流程。完成后从本表移除。
>
> **字段与写权限**：
> - **优先级**（P0/P1/P2）：登记时由提出方设定，归属角色可调整。
> - **待办**：一句话描述。
> - **归属角色**：登记时由提出方判定；写入后只能由归属角色本人变更（如转交）。
> - **来源**：任何角色的日志、ad-hoc、Incident、Review 结论、Owner 口述等；登记后不再改。
> - **状态**：**只能由归属角色更新**；其他角色发现状态过期可在会话里提醒，不可代改。
> - Owner 始终可以更新任何字段，作为兜底。
> - 收尾归档、迭代关闭检查等机制执行者可以登记新待办和更新项目级当前状态；不得代改归属其他角色的“归属角色 / 状态”字段，只能写入提醒或待确认。

| 优先级 | 待办 | 归属角色 | 来源 | 状态 |
|--------|------|----------|------|------|
| P1 | REQ-001 真实 L1 处理（stub→真实）已转入 v0.1 标准迭代，由迭代记录跟踪 | PM | xiaobao 提报 REQ-001 / Owner 立项 | ✅ 已完成（v0.1 已关闭，2026-07-04） |
| P1 | REQ-002 数据架构调研：读 Horizon/aggregator、答 4 岔路口、出数据架构方案 | Architect | Owner 指派 REQ-002 / 2026-06-29 ai PM 承接 | 已完成（2026-06-29，见 ad-hoc spike） |
| P1 | 承接 coordination REQ-003（数据库边界异步解耦）：已于 2026-07-25 承接并转入 v0.2 标准迭代，由迭代记录跟踪；**阻塞项 O-1（`score_total` 归属冲突）待 xiaobao 侧回应** | PM | xiaobao PM 提报 REQ-003（2026-07-05 初版 / 07-12 R2）/ Owner 2026-07-25 拍板 v0.2 重排 | 进行中（v0.2 PRD R1 待三方 Review） |
| P0 | **v0.2 部署阶段：注入 `ai_worker` 数据库口令** —— 在服务器上从 `/root/.secrets/ai_worker_news_test.pw`（root only）直接读取，写入部署目录 `.env`（`chmod 600`、仓外），按 O-7 拆字段注入 `AI_DB_PASSWORD`。**同机部署，无需 Owner 人肉转交、不经对话传递**；口令不进 git / coordination / 任何 `docs/` / 会话明文。到位后方可做联调冒烟与 C-6 行锁实证 | DevOps | Owner 2026-07-27 定交付方式 / xiaobao DevOps 2026-07-25 生成口令 | 待执行（部署阶段） |
| P1 | v0.2 顺延项 ①服务托管化（systemd/launchd）②工具调用并发化：托管对象与并发单元均随 v0.2 worker 形态确定后再定，避免返工 | DevOps（①）+ Architect/Developer（②） | v0.1 发布检查项 1/4 / 2026-07-25 v0.2 范围重排 | 待启动（排 v0.3） |
| P2 | v0.2 顺延项 ③RunRecord 持久化：与 v0.2 的 `processed_news`/`tasks` 写回存在职责重叠，待 DB 模式落地后重估还缺哪些审计信息 | Architect | v0.1 下一步入口 / 2026-07-25 v0.2 范围重排 | 待启动（排 v0.3，需先重估范围） |
| P2 | v0.2 顺延项 ④生产 ≥2 provider 真实 fallback 验证 | DevOps | v0.1 发布检查项 3 / 2026-07-25 v0.2 范围重排 | 待启动（部署阶段或 v0.3） |
| P1 | ai↔xiaobao news-l1 真实数据端到端联调 + KB search 接入：① ai 测试环境部署、提供 `AI_HUB_BASE_URL`（`/health` 200，当前 127.0.0.1:8100 未运行）② 鉴权 token ③ 核对 `/v1/runs/news-l1` 与更新后 `contracts/news-l1.md` 一致 ④ 新接入 xiaobao `POST /v1/kb-search`（`x-admin-token`；v0.1 `tools/kb.py` 占位禁用、属新工作）⑤ 回填真实调用证据 | Developer | xiaobao 2026-07-01 响应（coordination `communications/REQ-001`、`contracts/kb-search.md`） | ✅ 已完成（2026-07-04，4 条用例通过，Owner 抽样验收通过，v0.1 已关闭；KB 空结果语义 D-3 待优化为非阻塞遗留，转入下一迭代） |

## Bootstrap 记录
- 时间：2026-06-21
- 状态：已完成
- Git 状态：仓库工作区干净（initial commit `0ee6c9a`）；本次先同步安装工作流框架（`agent-workflow@90edee2`），再执行 Bootstrap 初始化工作台
- 下一步：询问用户是否需要以某个角色或工作类型继续；如不需要，保持 General（通用助手）
