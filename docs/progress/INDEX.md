# 项目进度索引

> 本文件是项目级当前状态的唯一真源。启动时 Agent 读此文件即应能判断"现在卡在哪、下一步做什么"，不需要再去翻迭代记录。

## 当前项目状态

- 当前迭代：v0.2（进行中，2026-07-25 范围重排：主线改为承接 REQ-003 数据库边界异步解耦）
- 当前模式：标准迭代（进行中）
- 当前阶段：**设计阶段 — R1 三方 Review 齐、均未通过，待 Architect 出 R2**（2026-07-28：PM 3 高 2 中 / Developer 1 高 5 中 2 低 / DevOps 2 高 2 中）
- **本项目核心开发原则（Owner 2026-07-26 定，优先于成本考量）**：以基础夯实、可扩展性强的方式开发，而不是图便捷。已写入 `v0.2-prd.md` §0，后续所有技术取舍按此裁定。
- 阻塞项：**无阻塞级**。三方设计 R1 的问题均为覆盖缺口或跨层协调细节，非方向错误。
- **PM 侧本轮产出（2026-07-28）**：① **设计 R1 Review 未通过**（3 高 2 中：AC-7 零落点 / AC-6 仅落 2/6 / `N=1` 的吞吐未经产品确认）；② **CN-004 已出并落地 PRD**（AC-8.2 据实测订正、新增 O-11 吞吐观察项、`error_kind` 增补 `budget_exhausted`）；③ **向 xiaobao 提三件事**（C-14 `l0_label` 语义 / 测试队列不可领 / 日增量量级），已 push coordination。
- **CN-004 的三条**：
  1. **AC-8.2 据实测订正**：`l0_label` 实测两库只有 `direct_display` 一个非空取值、**是流程标记非领域分类** → **`domain_tags` 在 DB 模式实际恒为 `[]`**，**推翻 C-1 的原闭合结论**（§6 C-1 行已改为「重新开放」，已闭合计数 14 → 13）。适配层用**排除集**而非一律置空（对方将来启用真实分类时 ai 无需改代码即生效）。
  2. **新增 O-11 吞吐观察项**：`N=1` + 单实例 + 串行下处理能力上界约 **340~920 条/天**，生产已有 757 条历史、日增量未确认。**灰度期须监测队列长度趋势，单调增长超 24h 即触发 v0.3 并发化排期前移**。不改 v0.2 任何实现与验收。
  3. **`error_kind` 增补 `budget_exhausted`**：与 `timeout` 分开——前者指向各段上限分配（调 `KB_TIMEOUT_MS` 等），后者指向 provider 侧（调 provider / 查 fallback 链）；混记会让灰度期无法定位该调哪一个。
- **待 xiaobao 回应（新提 3 项）**：C-14 `l0_label` 取值域与语义；**`tasks` 中 `l1_ai_process` 记录为 0 → 5 条预置队列 ai 永远领不到**（阻塞 AC-10.2 真实冒烟与 C-6 实证）；`process_type='ai'` 日增量量级。另 C-11~C-13、Q-1 仍待回应，均不阻塞。
- **联调判读须知**：`score_total` 在 database 模式无触发点，ai 写回后该列保持 NULL → 新闻排序沉底、评分徽章显示 0。**不是 ai 的缺陷**。
- 下一步入口：① **Architect 按三方意见出设计 R2**（PM 侧两条必改：补 AC-7 三工具语义落点与测试项、补 AC-6 日志字段结构与 6.6 降级冗余）；② CN-003 / CN-004 待三方确认；③ xiaobao 回应新提 3 项后执行 C-6 实证与真实数据冒烟；④ 设计 R2 三方复审通过后进实现阶段。

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
