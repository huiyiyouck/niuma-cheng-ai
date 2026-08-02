# 项目进度索引

> 本文件是项目级当前状态的唯一真源。启动时 Agent 读此文件即应能判断"现在卡在哪、下一步做什么"，不需要再去翻迭代记录。

## 当前项目状态

- 当前迭代：v0.2（进行中，2026-07-25 范围重排：主线改为承接 REQ-003 数据库边界异步解耦）
- 当前模式：标准迭代（进行中）
- 当前阶段：**设计阶段 — R2 三方齐·全部通过；CN-003~CN-008 六个 Change Note 全部三方确认完毕**（2026-08-01 DevOps 投出 CN-008 末票）→ **待 CN-008 末票附条件处置后设计定稿、进实现阶段**
- **本项目核心开发原则（Owner 2026-07-26 定，优先于成本考量）**：以基础夯实、可扩展性强的方式开发，而不是图便捷。已写入 `v0.2-prd.md` §0。
- 阻塞项：**无**。
- **2026-07-28 xiaobao 三方全部答复，四件大事全解（均为好消息）**：
  1. **`domain_tags` 真源找到，差异消除** —— xiaobao Architect **主动撤回其上轮对 C-1 的错误答复并认账**：真源是 **`sources.domain_tags`**（信息源级静态领域标签），**不是** `raw_items.l0_label`。GRANT 已执行、契约升 **v1.5** → **DB 模式与 HTTP 模式在该字段上完全等价**，不再是已知限制。**CN-004 变更 1 整条作废**（其前提已被撤回），由 **CN-007** 撤回、**CN-006**（Architect）同步重写设计 §3.3。
  2. **C-6 行锁实证完整闭合（2026-07-28）** —— xiaobao DevOps 验**权限侧**（`ai_worker` 身份下 `FOR UPDATE SKIP LOCKED` + claim 写入在列级 GRANT 下可行 → claim 采用**写法 A**）；**ai DevOps 已补齐并发侧**（两会话同时 claim 拿到不同行 `ee471923…` / `5b0e6f71…`，SKIP LOCKED 生效、并发不重复领取；越权 `UPDATE tasks SET type` 仍 permission denied；全程 ROLLBACK、队列未消耗）。**结论：列级 GRANT 足以支撑行锁，xiaobao 预留的「改授表级」不必执行。** → 「v0.3 多实例前必须先解决 C-6」这条前置**可以解除**（正确性已验；多实例的吞吐与锁竞争观察仍留 v0.3）。已回帖 coordination（`611b2d9`）。
  3. **测试队列已修复** —— xiaobao DevOps 认领系其造数脚本缺陷（「正是 C-5 讨论过的形态，这次是我造出来的」），已补建 5 条 task + 订正脚本为幂等 → **AC-10.2 真实数据冒烟的数据阻塞解除**。
  4. **日增量已答** —— 活跃期日均 **15~30 条**（生产 757 条系 50+ 天累积），可预见增长无「上千条/天」场景 → 对照 ai 能力上界（340~920 条/天）**有 5~10 倍余量**，**v0.3 并发化无需排期前移**（O-11 由 P1 降 P2）。对方承诺量级跃迁时**提前经 coordination 知会**。
- **⚠️ ai DevOps 实机反证（2026-07-28，已回帖 coordination `611b2d9`）——第 1 条「完全等价」在当前测试数据上不成立**：
  - 实测 `sources` 全部 4 行中 **2 行 `array`（`["AI"]`）、2 行 `object`（`{}`）**，`domain_tags` 列**类型不统一**；
  - 而 **5 条待冒烟条目 JOIN 其 source 全部返回 `{}`** → 对这批数据 `domain_tags` **依然恒空**，「不再是已知限制」的结论对冒烟数据不适用；
  - 更关键：`{}` 是 object 非 array，`L1Input.domain_tags` 为 `list[str]`，按数组处理会触发校验失败 → 归 `MappingError(client_error)` → 按设计 §4.4 **不可重试直接 final_failed，5 条冒烟会全报废**；
  - **ai 侧已自行兜底**：入向映射仅在 `jsonb_typeof='array'` 时取用，`object`/`null`/缺失一律映射 `[]`（已登记 coordination 6i）。
  - > **后续订正（2026-08-01）**：本段「5 条冒烟条目全为 `{}`」是 07-28 当时的实测事实，但 **07-29 起对方已补建第 6 条**（挂 `domain_tags=["AI"]` 的 source）——**队列现为 6 条且同时覆盖两条路径**，「有值路径直到生产才首次执行」的风险已不成立。详见本文件上方 6i② 闭合条目。**类型兜底逻辑仍须保留**（`{}` 形态真实存在）。
  - 另登记 6j（提示）：**`tasks.status` 无 CHECK 约束**，写任何值 DB 都不拦；xiaobao C-6 实证 SQL 用的是 `processing` 而 C-2 枚举是 `running`，需确认其后端读哪个——无约束兜底时两侧各写各的不报错，但状态机认不出。
- **C-1~C-14 全部闭合**（已闭合计数 13 → **18**）；C-11/C-12/C-13 的答复**均与 ai 的假设一致**，无需改实现（C-13 确认 URL 前缀不保证 → ai 的规范化**必须保留**）。
- **⚠️ 卡死回收阈值 1800s → 600s（2026-08-01 PRD 已同步，xiaobao 主动查出并认账）** —— 此前 ai 三条不变式全建立在对方契约**臆定、无实现依据**的 1800s 上；真实值 `AI_STALE_TIMEOUT_MS = 600s`（其 test/prod 均已核实，契约 v1.7 回填）。**重算：停机安全不受影响；批量上限余量由约 4 倍降到 1.37 倍；`N = 1` 由「最优选择」变为唯一合法值（N=2 即违反）。** 产品侧连带约束：**单条预算 240s 只剩约 97s 上调空间**（原以为 1057s），灰度期若嫌 240s 不够，**调整前必须重核不变式**。该常数已升格为**跨项目契约参数**（v1.8），任一侧变更须先改契约并通知——**本迭代第五次「校验通过但保证不成立」，也是最深的一次**：前四次错的是 ai 自己没约束住的量，这次错的是**对方文档里一个 ai 从未质疑过的常数**。
- **🔄 Q-1 结论翻转为「补列」（2026-08-01 稍后，xiaobao PM 拍板，CN-009）** —— ai 当日稍早记的「按丢弃实现 + 写入已知限制」**已作废**。对方采纳 ai 的论证（「证据充分的高分」与「证据不足的高分」不可区分是真实信息损失，且该信号 ai 本就在产出），`processed_news` 新增 `needs_context boolean`（契约 v1.9），**ai v0.2 按 v1.9 写入**。**影响实现**：写回多一个字段 + 自测多一条断言，**须在 Developer 开工前落地**。**沿革教训**：对方原话是「你方按丢弃实现**即可**」（允许），PM 读成了「本迭代确定丢弃」（定论）——把一件仍在对方决策流程中的事标为闭合。
- **✅ `score_total` 补算定案（CN-009，契约 v1.9）**：xiaobao 采**轮询补算**（挂其现有 worker tick，随 ai v0.2 联调启动落地）。该差异由「无触发点、永久 NULL」降为「有确定方案与落地时点的临时状态」；**落地前联调判读须知照旧**（NULL 属预期、不得归因于 ai）。
- **✅ 6i 全项闭合（2026-08-01，xiaobao DevOps）**：其已在 `["AI"]` source 补 2 条待处理条目 + 重跑幂等 seed → 现 **8 条 `queued`、其中 3 条 `domain_tags` 非空**；6i① 列默认值 `'[]'` + CHECK 约束 test/prod 均已生效。**冒烟可同时覆盖「有值」+「空值」两条路径。**
  - **⚠️ PM 侧连带订正**：PRD §5 的队列条目数**当日已两次过期**（5→6→8）。已由 CN-009 把该条**从「写死数字」改为「冒烟前实查两项」**——数字是对方造数脚本决定的运行时事实，写进 PRD 的后果不是不准，而是**过期时没有任何信号**。
- **✅ 6i② 已闭合（2026-08-01，xiaobao DevOps 实测答复）——「5 条全 `{}`」的前提在提出时即已过时**：`news_test` 实有 **6 条** `queued` 的 `l1_ai_process`（非 5 条），其中 `raw_items.id=303fc961-…` 挂在 source `6e7a248a`（`domain_tags=["AI"]`）、task 建于 **2026-07-29**，claim 即命中**「有值」路径**；其余 5 条 `{}` 覆盖**空值/object 路径**。**故冒烟同时覆盖两条路径，无需新造数**，原「有值路径直到生产才首次执行」的风险不成立。另 6i① 修列默认值属其数据卫生（已收口，唯余其部署时 `SET DEFAULT`），不阻塞 ai。
  - **✅ 已由 PM 确认并落地（2026-08-01）**：PRD §5 第 2 条已改为 6 条，并采纳其建议补写「唯一有值样本」风险与处置（自测须避开该条或用 ROLLBACK 保护，被消耗则须请 xiaobao 补造后再冒烟）。原登记：：`v0.2-prd.md` §5 第 2 条「造数队列会耗尽（**预置 5 条**）」的数字同样过期，应为 **6 条**。该条讲的「自测阶段即开始消耗、耗尽前需 xiaobao 补跑脚本」这一风险**仍然成立**，只是基数要改；另可顺带注明**其中 1 条是唯一的「有值」路径样本**——它一旦被自测消耗掉，冒烟就退回「5 条全 `{}`」的老状态，**这条比总数更值得写进风险**。
- **`ALTER ROLE` 已主动知会 coordination（2026-08-01，CN-008 末票低③ 由 PM 落地）** —— ai 将对 `ai_worker` 自身设角色级默认超时；虽不需对方配合，但属对其数据库的**持久化写入**（`pg_roles.rolconfig`），对方 DBA 日后排查应能查到来源。已附执行对象/理由/权限实测/取值约束/ai 侧反向校验。**✅ 已按方案甲执行完毕（2026-08-01，ai DevOps）**：`pg_roles.rolconfig` 实际写入 `statement_timeout=4s` / `lock_timeout=3s` / `idle_in_transaction_session_timeout=60s`（执行前为空）；新连接实测三项生效。**核对提示：`rolconfig` 存的是 `60s`，而 `SHOW` 会规范化显示为 `1min`，两者是同一个值**——xiaobao 核对时勿误判为不一致。
- **KB 检索鉴权定案（CN-007）**：取**方案 A —— 同机内网直连 + IP 白名单，无需 token**。不采用方案 B（唯一可用的是 xiaobao **全权 `ADMIN_TOKEN`**，下发即授予其所有 admin 写权限，**违反最小权限**，双方均不采纳）。**部署约束须入部署就绪检查**：方案 A 的唯一前提是**同机**；任一侧迁机则 IP 白名单失效、KB 全部失败，且**主流程不中断只持续降级**——正因不中断更需显式核对。
- **联调判读须知**：`score_total` 在 database 模式无触发点，ai 写回后保持 NULL → 新闻排序沉底、评分徽章 0。**不是 ai 的缺陷**。
- 下一步入口：① ~~Architect 补 DB 超时配置入设计 §2.6 / §4.10~~ **已完成**（经 CN-008 落地，事务级取代语句级）；~~② CN-003~CN-007 待三方确认~~ **已完成**（六个 CN 全部确认完毕，2026-08-01）；~~③ CN-008 末票附条件待落地~~ **已完成**（四条全部闭合，详见下方「CN-008 末票附条件」）→ **设计定稿已无待办前置**；④ **进实现阶段**，按设计 §6.1 五步 + 步 0 先录黄金样本四类路径；⑤ 实现后跑真实数据端到端冒烟（数据已就绪）+ 多实例并发 claim 验证——**按 [v0.2.md §部署就绪检查](iterations/v0.2.md) 的 A~F 六组 24 条判据逐条执行**（2026-08-01 DevOps 已先行定义通过条件，含硬性证据要求；该缺口自 PRD R4 登记以来挂了四轮，本次清掉）。
- **✅ CN-008 末票附条件四条全部闭合（DevOps 提出 2026-08-01，当日落地完毕）**：
  - **中① ✅ 已落地**（Architect 设计 `614c0ff` + PM PRD `875735d`）：`AI_DB_CONNECT_TIMEOUT_MS 5000→1000`，不等式 3 由三个量扩为四个 —— `connect(1s) < lock(3s) < statement(4s) < tx(5s)`，**四个超时量全部进启动门禁、无一遗留在外**。
  - **中② ✅ 已落地**（DevOps `1246d46`，实机验证通过）：`deploy.sh` 新增 [4.6/6] DB 角色默认超时校验，以 `ai_worker` 裸连接读 `pg_settings`（该视图对这三项以 ms 返回整数，省掉 `'4s'`/`'4000ms'` 单位解析），角色默认严于应用层则 `exit 1` 并打印修复 SQL。实跑结果：`idle 60000ms` / `lock 3000ms` / `statement 4000ms` 三项均 ≥ 应用层，全绿。
  - **低③ ✅ 已知会**（PM `38c7068`）；**低④ ✅ 已落地**（PM 写入 AC-4.7 第 6 条：多算一个重试间隔是有意的保守，不得当笔误抹掉）。
  - 中① 原文（留档）：**`AI_DB_CONNECT_TIMEOUT_MS` 曾是唯一仍可自由漂移的超时量**。`run_tx` 的 `asyncio.wait_for` 包住 `_inner()`，而 `pool.connection()` 在 `_inner()` 内 → **建连耗时计入事务预算**；当前 `connect 5000 = tx 5000`，光建连即可吃光整个预算。按 Developer 注意点 (a)，事务超时会丢弃连接、紧接着的重试正好要新建连接 → 三次尝试可能全耗在建连上，**使 §4.6 的有限重试在最需要它的场景下失效**（18s 上界不破，停机安全性不受影响）。**这是「校验通过但保证不成立」的第四次**（前三次：CN-004 的 `N ≤ 8`、CN-005 的三层配一致、CN-008 的语句级 vs 事务级）。**订正方案**：`AI_DB_CONNECT_TIMEOUT_MS 5000→1000`，并入不等式 3 → `connect(1s) < lock(3s) < statement(4s) < tx(5s)`。实测支撑：同机内网建连+查询 35/37/35/35/36 ms，1000ms 为 25 倍余量。

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
| [CN-008](iterations/v0.2-cn-008.md) | claim 事务边界确认，`DB_OP_BOUND` 改用**事务级**超时（`statement_timeout` 逐语句、挡不住事务；推翻 DevOps 方案 A） | **三方已确认**（2026-08-01；设计 + PRD AC-4.7 均已落地） | ✅ **DevOps 末票 2 中 2 低已全部闭合**（当日）→ 随迭代归档 |
| [CN-007](iterations/v0.2-cn-007.md) | PRD 侧承接：**撤回 CN-004 变更 1** + 五项闭合 + O-11 降级 + KB 鉴权入 PRD | **三方已确认**（2026-07-30，**PRD 已落地**） | 随迭代归档 |
| [CN-006](iterations/v0.2-cn-006.md) | 设计侧承接（Architect 出）：§3.3 重写 + §4.13 新增 + 三项闭合回填 | **三方已确认**（2026-07-30，设计已落地） | 随迭代归档 |
| [CN-005](iterations/v0.2-cn-005.md) | 托管化范围追认（Owner 拍板部分纳入）+ 设计 R2 两方附条件 + 四条 PRD 追平 | **三方已确认**（2026-07-30，**PRD 已落地**；其变更 3 取值已由 CN-008 订正） | 随迭代归档 |
| [CN-004](iterations/v0.2-cn-004.md) | 据实机发现订正 AC-8.2 + 补吞吐观察项 O-11 + 补 `error_kind=budget_exhausted` | **三方已确认**（2026-07-30，**PRD 已落地**） | 随迭代归档 |
| [CN-003](iterations/v0.2-cn-003.md) | v0.2 PRD R4 两条附条件 + 三方中低项收敛（12 条） | **三方已确认**（2026-07-30，**PRD 已落地**） | 随迭代归档 |

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
| 2026-08-01 | DevOps | 六件事：① **CN-008 末票**——认账我的方案 A 被推翻（`statement_timeout` 逐语句，按实际语句数单条链路 67s ≫ 20s 余量，我的方案会让门禁变绿而保证是假的）② 末票发现**中① `connect_timeout` 是第四次同型漏洞**（`run_tx` 的 `wait_for` 包住取连接 → 建连吃光事务预算），当日经 Architect + PM 落地，四个超时量至此全部进门禁 ③ 订正 CN 留痕（六个 CN 状态全部过期 + 一处 CN-006 重复登记）④ **`ALTER ROLE` 方案甲执行**（跨项目约定，`rolconfig` 写入 4s/3s/60s，已回帖，xiaobao 核对通过、待跟进 14 闭合）⑤ **`deploy.sh` 新增 `[4.6/6]` DB 角色默认超时校验**（中② 的强制点，实跑三项全绿）⑥ **定义部署就绪检查通过条件**（A~F 六组 24 条判据，挂四轮的欠账）。另：**停止 8100 上运行 31 天的 v0.1 服务**并主动知会 xiaobao（其 prod 配置仍指向该端口，已登记待跟进 16） | 已收尾。CN-008 三方齐 + 四条附条件当日全闭；DevOps 侧**无可推进待办**（剩余两条均有前置） | Architect 设计定稿 → Developer 实现阶段步 0 录黄金样本；实现后按 [v0.2.md §部署就绪检查](iterations/v0.2.md) A~F 判据逐条执行；等 xiaobao 核对**待跟进 16**（prod 配置指向 → 其 DevOps；服务端点入契约 → 其 Architect） |
| 2026-07-30 | DevOps | 确认 CN-003~CN-007 五个 Change Note（**发现一处会卡住启动的算术错误**：`DB_OP_BOUND` 公式算出 27s 而文档写 18s，该条是启动门禁、按现默认值 worker 起不来；根因是我设计 R2 给的算式漏算首次尝试，三方同错）；**托管化实际落地**（专用用户 `niuma-ai` + `/srv/niuma-ai/test` + unit 安装启用于 8102，沙箱/日志/优雅停机/完整部署链路全绿，v0.1 未受影响）；旧 `.env` 权限 644→600；`deploy.sh` 修两处首次部署缺陷 | 已收尾。五个 CN 均已写入 DevOps 确认（3 直接 + 2 附条件）；托管化验证全绿 | **PM/Architect 落实 CN-005 两个 DB 超时默认值订正**（`8000→5000`/`5000→3000`，不改则实现阶段首次启动即被门禁拦下）；Developer 补确认 CN-003/004/007；xiaobao 回应 6i/6j；Owner 定 v0.1 服务何时停 |
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
| **P0** | **部署 `.env` 的 LLM 配置已失效，须更新** —— 现配 `base_url=…/api/coding/v3` + `VOLC_API_KEY`，该 CodingPlan 订阅**已过期**，实调返回 **HTTP 400**。当前不阻塞是因为 `niuma-ai-worker@test` 尚未 enable；**一旦 enable，全部条目会因 LLM 失败走满 3 次重试直接进 `final_failed`**，属部署前置。**可用替代已实测**：openclaw 的 `volcengine-plan`（`…/api/plan/v3`，模型名不变仍是 `doubao-seed-2.0-pro`）与 `deepseek` 均返回 200；凭据在服务器 `/root/.openclaw/openclaw.json`（root only，勿回显/勿入 git）。**建议两个都配**——ADR-0002 的 provider fallback 链至此才第一次真正生效（此前只配一个，链形同虚设）。本迭代联调与本次验证均以环境变量临时覆盖跑通，**未改部署配置**（越 Developer 权限） | **DevOps** | Developer 2026-08-02 真实 LLM 联调查出 / Owner 2026-08-02 指派运维落地 | **待 DevOps 执行** |
| P1 | **补 Change Note 追认 AC-2.4 适用范围收窄** —— Owner 2026-08-02 拍板「消除重复抓取」，Developer 已实现并真实验证（见下条与自测报告）。改动使 AC-2.4「入向映射必须回填 `raw_content.url`」不再无条件成立：该 AC 隐含前提是「有 URL ⇒ 那是待补充的外部材料」，对 `x_twitter` 不成立（其 URL 指向内容自身）。**代码与测试已落地，缺的是 PRD/设计侧的留痕**——不补则文档与实现对不上，且下一个人会把它当缺陷"修回去" | PM / Architect | Owner 2026-08-02 拍板 / Developer 实现后登记 | 待补 |
| P1 | **是否为「LLM 未给 scores」补 `degraded:scores_missing` 标记** —— 实测该情形产出「结构完整但全 0、reason 全空」，与 `needs_context` 的 `false` 双来源同形状（默认值与有效值混在同一取值、且落在错误一侧）。xiaobao 补算 tick 的「结构残缺则跳过」判据抓不到它，会把该条当有效 0 分加权、排到最后。已在 coordination 给出当下可用的判别手段（判 `reason` 非空而非 `score`），故**不阻塞联调**；但数据层直接可判优于靠推断。属范围决策，若定为要加须先出 Change Note | PM / Architect | Developer 2026-08-02 联调回帖实测 | 待判断 |
| P1 | REQ-001 真实 L1 处理（stub→真实）已转入 v0.1 标准迭代，由迭代记录跟踪 | PM | xiaobao 提报 REQ-001 / Owner 立项 | ✅ 已完成（v0.1 已关闭，2026-07-04） |
| P1 | REQ-002 数据架构调研：读 Horizon/aggregator、答 4 岔路口、出数据架构方案 | Architect | Owner 指派 REQ-002 / 2026-06-29 ai PM 承接 | 已完成（2026-06-29，见 ad-hoc spike） |
| P1 | 承接 coordination REQ-003（数据库边界异步解耦）：已于 2026-07-25 承接并转入 v0.2 标准迭代，由迭代记录跟踪 | PM | xiaobao PM 提报 REQ-003（2026-07-05 初版 / 07-12 R2）/ Owner 2026-07-25 拍板 v0.2 重排 | 进行中（PRD R4 已定稿，进设计阶段；C-11~C-13 + Q-1 待 xiaobao 回应，均不阻塞） |
| P0 | **v0.2 设计阶段开工即并行（CN-003 3.10 前移，原排部署阶段）：备服务器环境 + 注入 `ai_worker` 口令 + 跑 C-6 实证** —— 在服务器上从 `/root/.secrets/ai_worker_news_test.pw`（root only）直接读取，写入部署目录 `.env`（`chmod 600`、仓外），按 O-7 拆字段注入 `AI_DB_PASSWORD`。**同机部署，无需 Owner 人肉转交、不经对话传递**；口令不进 git / coordination / 任何 `docs/` / 会话明文。~~服务器环境整块缺失（ai 至今只在开发机跑过）~~ **该前提有误，已订正**：v0.1 服务一直在服务器上运行（pid 3026041，起于 2026-07-01，已连续 26 天），环境非缺失而是「已有一份、需规范化 + 升级」。 | DevOps | Owner 2026-07-27 定交付方式 / DevOps R3 问题 1 / CN-003 变更 3.10 | ✅ **已完成（2026-07-28）**：目标机 `zijie`/115.191.43.79，ai 部署于 `/opt/niuma-cheng-ai`（clone+venv+依赖，40 单测通过）；口令按 O-7 拆字段注入 `.env`（600、gitignore、未回显），`ai_worker` 实连 `news_test` 六项验证全过、权限矩阵与契约 v1.4 一致；LLM 凭据一并合并到位。**C-6 实证被实机发现 A 阻塞**（`tasks` 无 `l1_ai_process` 行），待 xiaobao 回应。证据见 [ad-hoc](ad-hoc/2026-07-28-ops-server-env-and-credential.md) |
| P1 | v0.2 顺延项 ①服务托管化（systemd/launchd）②工具调用并发化 | DevOps（①）+ Architect/Developer（②） | v0.1 发布检查项 1/4 / 2026-07-25 v0.2 范围重排 / Owner 2026-07-28 拍板托管化纳入 v0.2 | **① ✅ 已落地（2026-07-30）**：`niuma-ai-http@test` 已装并 enable，运行于 `/srv/niuma-ai/test`、专用用户 `niuma-ai`、端口 8102（**v0.1 的 8100 已于 2026-08-01 由 Owner 拍板停机**，8102 现为 ai 唯一在跑的 HTTP 服务；停机核实与恢复方法见 DevOps 日志 2026-08-01）；沙箱实测生效（写 `/etc` 被拒）、journal 收日志、优雅停机 136ms、重跑 `deploy.sh` 三层校验完整通过（`TimeoutStopSec=280s > 应用层 260s`）。`niuma-ai-worker@test` 已安装**未 enable**——等 v0.2 worker 代码实现后再启用。②仍排 v0.3 |
| P2 | v0.2 顺延项 ③RunRecord 持久化：与 v0.2 的 `processed_news`/`tasks` 写回存在职责重叠，待 DB 模式落地后重估还缺哪些审计信息 | Architect | v0.1 下一步入口 / 2026-07-25 v0.2 范围重排 | 待启动（排 v0.3，需先重估范围） |
| P1 | **部署就绪检查补一条：核对契约 `news-l1` v1.1 §服务端点与运行时坐标 所列坐标与实际部署一致**（六项：ai test/prod base URL、xiaobao kb-search test/prod base URL、`AI_INTEGRATION_MODE`、`RUN_MODE`）。**没有这条核对，该契约节会随时间烂掉、与不登记无异**——本迭代已见过同型（`AI_STALE_TIMEOUT_MS` 的 1800s 长期没人发现是错的，正因无任何机制会去读它一次）。另：ai prod base URL 待 v0.2 部署时由 DevOps 回填契约 | DevOps | Architect 2026-08-01 落契约 v1.1 时的连带要求（设计 §4.13）/ 源自 DevOps 8100 停机时提的结构性建议 | **① ✅ 已完成（2026-08-01）**：六项核对已落为**部署就绪检查 D6 判据**并完成**首次基线执行**——①`8102` ✓ `/health` 200 ②prod 未部署（`8100` 已停，符合预期）③`8001` ✓ 绑 `127.0.0.1` ④`8000` ✓ **绑 `0.0.0.0`**（非环回，功能上契约值可达）⑤实测 prod=`http`/test=`database`（**已回帖请对方回填契约**）⑥`RUN_MODE=http` ✓。判据中**写死查法**（须 `ss -ltn \| grep ':<port>'` 全接口匹配，不得只匹配环回——我首次执行即因窄匹配把绑 `0.0.0.0` 的 ④ 误判为「未监听」）。**② prod base URL 仍待 v0.2 部署 prod 时回填**（ai 权属，已在 coordination 2026-08-01 帖挂账）。**本行已合并 DevOps 于同日重复登记的一行**（我当时只看了 `88563cb` 的 commit message、未来 INDEX 查已登记行，导致重复） |
| P2 | v0.2 顺延项 ④生产 ≥2 provider 真实 fallback 验证 | DevOps | v0.1 发布检查项 3 / 2026-07-25 v0.2 范围重排 | 待启动（部署阶段或 v0.3） |
| P1 | ai↔xiaobao news-l1 真实数据端到端联调 + KB search 接入：① ai 测试环境部署、提供 `AI_HUB_BASE_URL`（`/health` 200，当前 127.0.0.1:8100 未运行）② 鉴权 token ③ 核对 `/v1/runs/news-l1` 与更新后 `contracts/news-l1.md` 一致 ④ 新接入 xiaobao `POST /v1/kb-search`（`x-admin-token`；v0.1 `tools/kb.py` 占位禁用、属新工作）⑤ 回填真实调用证据 | Developer | xiaobao 2026-07-01 响应（coordination `communications/REQ-001`、`contracts/kb-search.md`） | ✅ 已完成（2026-07-04，4 条用例通过，Owner 抽样验收通过，v0.1 已关闭；KB 空结果语义 D-3 待优化为非阻塞遗留，转入下一迭代） |

## Bootstrap 记录
- 时间：2026-06-21
- 状态：已完成
- Git 状态：仓库工作区干净（initial commit `0ee6c9a`）；本次先同步安装工作流框架（`agent-workflow@90edee2`），再执行 Bootstrap 初始化工作台
- 下一步：询问用户是否需要以某个角色或工作类型继续；如不需要，保持 General（通用助手）
