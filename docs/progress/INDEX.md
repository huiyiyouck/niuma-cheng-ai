# 项目进度索引

> 本文件是项目级当前状态的唯一真源。启动时 Agent 读此文件即应能判断"现在卡在哪、下一步做什么"，不需要再去翻迭代记录。

## 当前项目状态

- 当前迭代：v0.2（进行中，2026-07-25 范围重排：主线改为承接 REQ-003 数据库边界异步解耦）
- 当前模式：标准迭代（进行中）
- 当前阶段：**设计阶段已定稿（2026-07-28，R2）→ 可进实现阶段**。三方全部通过（Developer 通过 / PM 通过·附条件 / DevOps 通过·附条件）；PM 的三条附条件全在 PRD 侧、已由 **CN-005** 落地（AC-5.7 逐层放大 / AC-3.6 不变式补 DB 上界 / AC-6.1 补 `budget_remaining_ms`，另新增 **AC-4.7 DB 操作超时上限**），Architect 已确认；DevOps 的附条件（DB 超时上限）**已于定稿前落进设计**（§2.6 三项超时配置 + `DB_OP_BOUND` 两条不等式进启动门禁 + §4.10 池初始化与隔离级别断言同处设置 + §4.6 的「≤2s」改为参数推导上界）。三方 R2 另提的 7 条建议项亦于定稿前一并订正，**测试项 24 → 26**。
- **设计定稿要点**：六项开放问题 O-2/O-3/O-6/O-8/O-9/O-10 全部落定 + ADR-0003（协议按职责分层）/ ADR-0004（单条预算 240s 与 N=1）。**DevOps R2 高① 是本轮最实质的一条**——我给处理阶段设了 240s 封顶，却默认了「数据库操作总是快的」：claim 与写回两个事务在所有预算之外，而 §4.6 的「重试 ≤2s」只在每次重试立即失败时成立，其触发条件 `deadlock_detected`/`serialization_failure` 本质是锁等待、无 `lock_timeout` 时 PG 会无限等；写回三表时 xiaobao 的 1800s 回收可能正在 UPDATE 同一行 `tasks`，两侧写竞争是这套契约的固有面。已按 `statement_timeout=8s` / `lock_timeout=5s` 收敛（最坏 `2 × (8+1) = 18s ≤ 20s` 收尾余量，无需改动已定的 260/280）。
- **本项目核心开发原则（Owner 2026-07-26 定，优先于成本考量）**：以基础夯实、可扩展性强的方式开发，而不是图便捷。已写入 `v0.2-prd.md` §0。
- **定稿后据 xiaobao 答复的更新（2026-07-28，[CN-006](iterations/v0.2-cn-006.md)，轻量变更·不回设计阶段）**：xiaobao 三方于设计定稿当日答复完毕、契约升 **v1.5**，八条外部事实全部落进设计。**最实质一条：`domain_tags` 的真源是 `sources.domain_tags` 而非 `l0_label`**——对方主动撤回其 v1.3 的错误结论并追出 HTTP 模式完整取数链路，`GRANT SELECT (domain_tags, attention_level) ON sources` 已双库执行 verify。**后果是好消息：DB 模式取到该列后与 HTTP 模式同字段同数据、完全等价，「`domain_tags` 恒为 `[]`」的已知差异整条消失**（设计 §3.3 整节重写，原排除集方案作废；PRD AC-8.2 对应条与 CN-004 变更 1 应由 PM 撤回）。另：**C-6 行锁实证通过** → claim 定为写法 A（写法 B 降为 v0.3 备用）；**发现 A 闭合**（对方补建 5 条 task + 订正造数脚本）→ 测试 20 前置解除；C-11 `priority` 数值大=优先、C-13 URL 确不保证前缀、C-5 事务已落地为强承诺、C-12 对方已改读列——**ai 侧结论与防御均不变**；**O-11 风险大幅下降**（实测日均 15~30 条，5~10 倍余量，v0.3 并发化无需前移）。
- **Architect 拍板项：KB 检索走同机直连、不用任何 token**（设计 §4.13）。对方 `/v1/kb-search` 鉴权 = `ADMIN_TOKEN` 或 IP 白名单，而唯一可用的是其**全权** token（下发即授予所有 admin 写接口权限）——按最小权限定为方案 A：`KB_SEARCH_URL` 指向 `127.0.0.1`，不配 token，`tools/kb.py:38-40` 零代码改动即兼容。**部署约束**：唯一前提是同机；若将来分机，须请对方加独立只读 KB token，**不得复用全权 `ADMIN_TOKEN`**。
- 阻塞项：**无**。
- **范围变更（Owner 2026-07-28 拍板）**：**服务托管化「部分纳入」v0.2** —— 进程级托管（systemd unit + `Restart=on-failure` 崩溃自动拉起）**移入「本迭代做」并补验收标准**；**健康检查驱动的重启（worker 协程级）仍顺延 v0.3**。
  - **能力边界（防误期待，已写进 PRD §4 与 AC-9.3）**：`Restart=on-failure` 只看**进程退出码**，而 worker **协程**死亡时进程仍存活，systemd **不会做任何事**；消费 `dead` 状态 503 的 healthcheck timer 未纳入。故 `dead` **靠人工发现**。
  - **灰度期约束（替代原「不得无人值守」）**：可在 systemd 托管下运行，但**仍须人工看护 worker 存活**。**部署就绪检查口径：unit 存在 ≠ worker 存活有自动兜底。**
- **CN-005 的其余五条**：① **AC-5.7「三层配一致值」→「逐层放大、不得相等」**（原表述由 PM 在 CN-003 逐字搬用 DevOps 措辞而来，「一致」被读成「数值相等」；照原文配三个相等值会**通过验收却在真实停机时踩竞态**，且该竞态自测几乎必不复现）② **新增 AC-4.7 数据库操作超时上限**（`ItemBudget` 只覆盖处理阶段，claim 与写回两个事务在所有预算之外且无任何超时配置；取 `statement_timeout=8s`/`lock_timeout=5s` 使 AC-5.7 算式自洽、无需改 260/280）③ AC-3.6 不变式输入收敛为 `N × (预算 + DB 上界) < 1800s` ④ AC-9.3 `dead` 行补 v0.2 无自动消费方 ⑤ AC-6.3 日志落盘按 journal 订正、AC-6.1 补 `budget_remaining_ms`。
- **联调判读须知**：`score_total` 在 database 模式无触发点，ai 写回后保持 NULL → 新闻排序沉底、评分徽章 0。**不是 ai 的缺陷**。
- **待 xiaobao 回应（3 项，已分派角色）**：C-14 `l0_label` 取值域（→ 其 Architect）；**`tasks` 中 `l1_ai_process` 记录为 0 致 5 条预置队列领不到**（→ 其 DevOps，**最急**，阻塞 AC-10.2 真实冒烟与 C-6 实证）；日增量量级（→ 其 PM）。另 C-11~C-13、Q-1 待回应，均不阻塞。
- 下一步入口：① ~~Architect 补 DB 超时配置 → 设计定稿~~ **已完成**（2026-07-28，见上）；② **切 Developer 进实现阶段**——第一动作是设计 §6.1 **步 0：在 v0.1 基线录制四类黄金样本**，须遵守 §6.2 边界声明（**四类样本均不得含「工具成功但无结果」场景**，否则会与步 3 并入的 AC-7 三分支修复直接冲突——那是有意的行为变更、不是回归；该场景由测试 17 独立覆盖）；③ **CN-006 待三方确认**（设计侧已落地；**PM 侧连带动作：撤回 PRD AC-8.2 的 `domain_tags` 差异条 + 作废 CN-004 变更 1**），CN-003/004/005 待确认齐后随迭代归档（Architect 侧均已确认）；④ ~~等 xiaobao 回应~~ **已全部回应**——C-6 实证通过、发现 A 闭合，**AC-10.2 真实数据端到端（测试 20）现已可跑**，`news_test` 有 5 条 `queued` `l1_ai_process` task 即刻可领；⑤ 灰度期按 O-11 监测队列长度趋势（风险已降，保留作兜底）；⑥ **v0.3 候选登记**：`l0_label` 作为处理优先级信号用于 `needs_context` 判定（对方建议，呼应 Q-1）——**v0.2 明确不做**。

> 当迭代激活后，`当前阶段` 必须写清楚具体状态，例如：
> `设计阶段 — Review R2，Architect 等待 PM 和 Developer 反馈`
> `实现阶段 — R1 已提交，等待 Tester 和 Architect Review`
> 这能避免 Agent 仅为了解状态就去读完整迭代记录。

## 版本列表

> 首个迭代版本号建议为 `v0.1`，后续版本号由 PM 在 PRD 中决定。不强制 SemVer。

| 版本 | 迭代记录 | PRD | UI | 设计文档 | Summary | 状态 |
|------|----------|-----|----|----------|---------|------|
| v0.2 | [v0.2.md](iterations/v0.2.md) | [v0.2-prd.md](iterations/v0.2-prd.md) | 纯后端（无界面） | — | — | **设计阶段进行中**（PRD R4 已定稿 + CN-003 已落地；契约 v1.4） |
| v0.1 | [v0.1.md](iterations/v0.1.md) | [v0.1-prd.md](iterations/v0.1-prd.md) | 纯后端（无界面） | [v0.1-design.md](iterations/v0.1-design.md) | [v0.1-summary.md](iterations/v0.1-summary.md) | 已关闭（2026-07-04，[自测报告](iterations/v0.1-test-report.md)） |

## 当前 Change Notes

> v0.1 迭代已关闭，CN-001 / CN-002 已随 v0.1 归档。

| Change Note | 关联工作 | 状态 | 下一步 |
|-------------|----------|------|--------|
| [CN-005](iterations/v0.2-cn-005.md) | 托管化范围追认（Owner 拍板部分纳入）+ 设计 R2 两方附条件 + 四条 PRD 追平 | 待三方确认（**PRD 已落地**） | 三方确认后随迭代归档 |
| [CN-004](iterations/v0.2-cn-004.md) | 据实机发现订正 AC-8.2 + 补吞吐观察项 O-11 + 补 `error_kind=budget_exhausted` | 待三方确认（**PRD 已落地**） | 三方确认后随迭代归档 |
| [CN-003](iterations/v0.2-cn-003.md) | v0.2 PRD R4 两条附条件 + 三方中低项收敛（12 条） | 待三方确认（**PRD 已落地**） | 三方确认后随迭代归档 |

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
| P1 | 承接 coordination REQ-003（数据库边界异步解耦）：已于 2026-07-25 承接并转入 v0.2 标准迭代，由迭代记录跟踪 | PM | xiaobao PM 提报 REQ-003（2026-07-05 初版 / 07-12 R2）/ Owner 2026-07-25 拍板 v0.2 重排 | 进行中（PRD R4 已定稿，进设计阶段；C-11~C-13 + Q-1 待 xiaobao 回应，均不阻塞） |
| P0 | **v0.2 设计阶段开工即并行（CN-003 3.10 前移，原排部署阶段）：备服务器环境 + 注入 `ai_worker` 口令 + 跑 C-6 实证** —— 在服务器上从 `/root/.secrets/ai_worker_news_test.pw`（root only）直接读取，写入部署目录 `.env`（`chmod 600`、仓外），按 O-7 拆字段注入 `AI_DB_PASSWORD`。**同机部署，无需 Owner 人肉转交、不经对话传递**；口令不进 git / coordination / 任何 `docs/` / 会话明文。~~服务器环境整块缺失（ai 至今只在开发机跑过）~~ **该前提有误，已订正**：v0.1 服务一直在服务器上运行（pid 3026041，起于 2026-07-01，已连续 26 天），环境非缺失而是「已有一份、需规范化 + 升级」。 | DevOps | Owner 2026-07-27 定交付方式 / DevOps R3 问题 1 / CN-003 变更 3.10 | ✅ **已完成（2026-07-28）**：目标机 `zijie`/115.191.43.79，ai 部署于 `/opt/niuma-cheng-ai`（clone+venv+依赖，40 单测通过）；口令按 O-7 拆字段注入 `.env`（600、gitignore、未回显），`ai_worker` 实连 `news_test` 六项验证全过、权限矩阵与契约 v1.4 一致；LLM 凭据一并合并到位。**C-6 实证被实机发现 A 阻塞**（`tasks` 无 `l1_ai_process` 行），待 xiaobao 回应。证据见 [ad-hoc](ad-hoc/2026-07-28-ops-server-env-and-credential.md) |
| P1 | v0.2 顺延项 ①服务托管化（systemd/launchd）②工具调用并发化：托管对象与并发单元均随 v0.2 worker 形态确定后再定，避免返工 | DevOps（①）+ Architect/Developer（②） | v0.1 发布检查项 1/4 / 2026-07-25 v0.2 范围重排 | 待启动（排 v0.3） |
| P2 | v0.2 顺延项 ③RunRecord 持久化：与 v0.2 的 `processed_news`/`tasks` 写回存在职责重叠，待 DB 模式落地后重估还缺哪些审计信息 | Architect | v0.1 下一步入口 / 2026-07-25 v0.2 范围重排 | 待启动（排 v0.3，需先重估范围） |
| P2 | v0.2 顺延项 ④生产 ≥2 provider 真实 fallback 验证 | DevOps | v0.1 发布检查项 3 / 2026-07-25 v0.2 范围重排 | 待启动（部署阶段或 v0.3） |
| P1 | ai↔xiaobao news-l1 真实数据端到端联调 + KB search 接入：① ai 测试环境部署、提供 `AI_HUB_BASE_URL`（`/health` 200，当前 127.0.0.1:8100 未运行）② 鉴权 token ③ 核对 `/v1/runs/news-l1` 与更新后 `contracts/news-l1.md` 一致 ④ 新接入 xiaobao `POST /v1/kb-search`（`x-admin-token`；v0.1 `tools/kb.py` 占位禁用、属新工作）⑤ 回填真实调用证据 | Developer | xiaobao 2026-07-01 响应（coordination `communications/REQ-001`、`contracts/kb-search.md`） | ✅ 已完成（2026-07-04，4 条用例通过，Owner 抽样验收通过，v0.1 已关闭；KB 空结果语义 D-3 待优化为非阻塞遗留，转入下一迭代） |

## Bootstrap 记录
- 时间：2026-06-21
- 状态：已完成
- Git 状态：仓库工作区干净（initial commit `0ee6c9a`）；本次先同步安装工作流框架（`agent-workflow@90edee2`），再执行 Bootstrap 初始化工作台
- 下一步：询问用户是否需要以某个角色或工作类型继续；如不需要，保持 General（通用助手）
