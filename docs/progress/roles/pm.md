# PM（产品经理）角色日志

## 2026-07-26 — 会话摘要（PRD R2：按三方 Review + Owner 核心原则重排）

### ⭐ Owner 核心开发原则（2026-07-26 定，长期有效，优先于成本考量）

> **以基础夯实、可扩展性强的方式开发，而不是图便捷。宁可现在麻烦一点、活多一点，也要让系统更健全、后期接入更友好。**

依据（Owner 原话要点）：ai 是**持续迭代**的产品，基础越牢，后续可扩展的功能越多。已写入 `v0.2-prd.md` §0 与 `INDEX.md` 项目状态区，**后续所有技术取舍按此裁定**。

- 本次角色：PM（产品经理，ck）
- 动作：R1 三方 Review 全部完成（均未通过）→ PM 出 PRD R2 → 汇总 10 条契约缺项转达 xiaobao。
- R1 Review 结果：DevOps 4 高 2 中 1 低（07-25）、Architect 3 阻塞 3 高 3 中 1 低（07-25）、Developer 2 阻塞 3 高 1 中 + 事实层刷新 8 项（07-26）。
- **按核心原则推翻 R1 三处「成本最优解」**（本次最重要的判断）：
  1. **async 地基改造进范围**（推翻 Developer 推荐的「worker 跑独立线程、处理核心零改造」）。理由：线程方案是绕过而非解决；同步阻塞是**既有架构债在新形态下暴露**（FastAPI 是 async 框架，v0.1 全同步靠线程池兜底，worker 自控循环后该保护消失）；v0.3 的工具并发与批内并发必然要还，届时 worker 推倒重来。成本核实：出网调用仅 4 点且全走 httpx（`client.py:176`/`kb.py:50`/`web_search.py:24`/`link_reader.py:38`），有对等 AsyncClient，LangGraph 原生支持 async 节点——**风险在回归不在重写**。连带反转 Developer 建议的「§5 写明不引入 async、驱动倾向 psycopg3 同步」→ 驱动须与 async 一致。
  2. **适配层定义为数据源协议**（推翻「两个映射函数、成本几乎为零」）。理由：映射函数方案下第二调用方接入要回来改我们代码，与 `decisions/0002` 多调用方定位冲突。
  3. **`tags_v2` 主张两个语义都保留**（推翻「二选一」）。理由：`sentiment` 是业务标签、`processing` 是降级/provider 的唯一结构化线索，二者非同类，丢任一削弱可诊断性。
- **克制范围的判断**：async 地基进 v0.2，但**工具并发化仍留 v0.3**（并发有独立验收成本），只要求 v0.2 设计保证「并发化时不需再动架构」。地基进当前迭代、收割留下一迭代。
- PRD R2 其余修改：AC-2/AC-8 判据分开写死（解 Developer 指出的互斥——我 R1 写的两条会同时判通过与不通过）；AC-3 补批量上限不变式（N ≤ 8 属正确性约束非调优）+ claim 原子性实证前置；AC-4 字段来源逐条标注 + 三段式事务（LLM 调用绝不持有事务）；AC-5 补退避判定、重试真源、残留锁自愈、优雅停机；AC-6 补 DSN 脱敏可验证断言 + 注入式 logging + 降级事实冗余进日志；AC-7 删空条款（`stub` 已 0 命中）+ 缺陷定位订正至 `news_l1.py:150/179/213` + 扩为三工具；新增 AC-9（async + 处理中 `/health` 2s 响应）、AC-10（三类源验收分层，**不得虚报三类均真实验收**）；新增 §6 契约缺项清单、§8 工程成本切片；事实层刷新 8 项全部落实。
- 契约缺项 C-1~C-10 已转达 coordination（`0d6a40b`）：**C-2/C-3/C-5/C-10 四条阻塞 ai PRD 定稿**；撤回 1 条（`source_item_url` 可由适配层构造）。
- 跨项目进展（同期）：O-1 定案方案 A + 契约订正 v1.1；xiaobao DevOps 执行迁移并实测（角色+GRANT+越权拦截+造数 5 条+R-5 结构说明），DB 前置解除；ai 侧唯一剩余外部依赖 = **Owner 交付 `ai_worker` 口令**。
- 我的两处失误（已修正并留痕）：① R1 写的 AC-2 与 AC-8 判据互斥（Developer 指出）；② 上一轮向 Owner 汇报「再没有对小报的阻塞了」，被 Architect Review 推翻（3 条阻塞均为契约缺项，需回找 xiaobao）。
- 关联迭代：v0.2（PRD 阶段，R2 待三方复审）
- 遗留问题/风险：**O-8 async 改造的切分与回归策略是本迭代最大技术风险**（40 例单测需迁移 `pytest-asyncio`，v0.1 已验证逻辑要重测）；4 条契约缺项未闭合前不得定稿。
- 下一步入口：① 切 Architect / Developer / DevOps 做 R2 复审（**不减方**，R2 的 async 变更直接推翻了 Developer R1 的推荐解法）；② Owner 交付口令；③ xiaobao 回应 C-1~C-10。
- 收尾状态：已收尾（2026-07-26）

## 2026-07-25 — 会话摘要（状态重新对齐 + 承接 REQ-003 + v0.2 范围重排）
- 本次角色：PM（产品经理，ck）
- 动作：Owner 要求「看项目 + 拉最新代码 + 全面重新对齐 + 汇报进度」。执行工作流启动例行 → 核对代码/文档/协调仓三方实况 → 发现并处理 3 条对齐缺口 → 承接 REQ-003 → 按 Owner 拍板重排 v0.2 范围。
- 同步结果：ai 与 coordination 两仓均 `git pull --rebase` → Already up to date（ai HEAD `a53b680`，coordination HEAD `156b008`）。**无新代码，但协调仓有 20 天未响应的 REQ-003。**
- 发现的 3 条对齐缺口：
  1. **重大**：coordination `REQ-003`（v0.6.1 集成模式变更，状态「待 ai · PM 评估承接」——责任方即本席位）2026-07-05 提报、07-12 R2 更新，至 07-25 无人响应约 20 天；xiaobao 侧前置全部就绪（PRD R2 定稿 / 设计 R2 三方通过 / `contracts/news-l1-db.md` v1 出稿）在等 ai。且 v0.2 PRD 起草于 07-04，比 REQ-003 提报早一天，完全未包含它。
  2. `INDEX.md` 阻塞项写「无」，实际卡在 REQ-003 未评估导致范围未定。
  3. `project-context.md` 模块地图仍是 v0.1 前状态（「⚠️ 当前为骨架 / `llm_process` 返回占位输出 / `tags.processing` 含 `stub`」），且漏 `llm/`、`tools/`、`tasks.py` 三块，会直接误导新接手会话。
- Owner 决策（2026-07-25）：① **v0.2 重排，REQ-003 为主线**（而非排 v0.3 或作废 v0.2）；② 两处过期记录当场订正。
- REQ-003 评估结论（承接）：无异议部分——轮询 worker、适配层封装、翻译留 ai 侧、schema 权属归 xiaobao、双模式并行非替换、卡死回收由 xiaobao 执行。**核对出 1 个 P0 契约冲突**：`news-l1-db` v1 要求 ai 写 `score_total` 最终值，与 ① `news-l1` HTTP v1「不由 ai 计算」② ai 业务边界「不做 `score_total`」③ 该契约自身「输出语义以 HTTP 契约为准」三处冲突（契约内部自相矛盾）。另核对确认 `title`/`context`/`analysis` 在 HTTP v1 output 与 `L1Output` 中本已存在，非新增能力。
- 本次产出（ai 侧）：
  - 重写 `v0.2-prd.md`：主线 REQ-003，7 条用户故事（US-1~7）、8 条验收标准（AC-1~8）、7 条开放问题（O-1~7，O-1 为 P0 阻塞定稿）；Review 方由两方扩为**三方**（新增 DevOps，理由：运行形态从 HTTP 服务变常驻 worker + 新增数据库凭据，原「PRD 阶段不涉及部署变更」的免除理由已不成立）
  - 更新 `v0.2.md`：概览改写 + 新增「范围重排记录」小节；PRD 阶段门禁把旧 R1 标「未 Review（范围重排作废）」、新增重写后的 R1 行
  - 更新 `INDEX.md`：当前阶段 / 阻塞项（写明 O-1）/ 下一步入口 / 版本列表状态；跨任务待办登记 REQ-003 承接 + 4 条顺延项（含归属角色）
  - 订正 `project-context.md` 模块地图：删过期骨架警示、补 `llm/`+`tools/`+`tasks.py`+`tests/`、写明 v0.1 已交付实况
- 本次产出（coordination 侧，PM 跨项目权限内）：
  - `REQUESTS.md`：REQ-003 承接方填 ai·PM（ck）、转入迭代 ai v0.2、状态「已提报」→「开发中（转入迭代）」+ 标注待回应冲突
  - 新建 `communications/REQ-003-db-boundary-async.md`：承接结论 + 迟滞说明 + O-1 冲突（含方案 A/B）+ O-5 枚举瑕疵 + R-1~R-3 就绪度确认 + 待跟进表 7 项
  - `STATUS.md`：最近更新、ai 行、xiaobao 行备注、新增 §4 REQ-003 谁等谁、下一步汇总加 2 条
- 范围顺延（转 v0.3 / 部署阶段）：服务托管化、工具调用并发化、RunRecord 持久化、多 provider 生产验证。理由：形态均依赖 worker 架构，先做外围会返工。
- 边界守规：未替 Architect 定适配层分层/事务边界（列为 O-2/O-6）；未替 DevOps 定托管与凭据方案（O-7）；**未自行修改任何 contracts/**（O-1/O-5 均以沟通文档向 xiaobao 提出，契约变更由权属方执行）；未改 xiaobao 的 `docs/progress/`。
- 关联迭代：v0.2（PRD 阶段，R1 待三方 Review）
- 关联非迭代工作：跨项目协作 · REQ-003 承接
- 关联 Change Note：无（PRD 未定稿，走重写而非 Change Note）
- 遗留问题/风险：
  - **O-1 `score_total` 归属冲突未解 → v0.2 PRD 不得定稿**，需 xiaobao 回应或 Owner 拍板。
  - `ai_worker` 角色 GRANT、schema 迁移落地、凭据注入渠道三项就绪度未知，是实现阶段前置。
  - 本机无 `.venv`，本次未跑单测（PM 职责不含跑测试，但 Developer 进场前需先建环境）。
  - 响应端可见性缺口是本次 20 天迟滞的根因，已由 REQ-004（参谋长提报、待 workboard 承接）覆盖；ai 侧对策：每次会话启动扫协调仓需求池。
- 下一步入口：① 切 Architect 做 v0.2 PRD R1 Review（重点 O-1 架构影响 / O-2 适配层边界 / O-3 worker 参数 / O-6 事务边界）；② 切 Developer 做 R1 Review（工程成本 / claim 与写回实现 / 验收可验证性）；③ 切 DevOps 做 R1 Review（运行形态 / 凭据注入 O-7）；④ Owner 或 xiaobao 会话回应 REQ-003 的 5 项。
- coordination 依据：`../niuma-cheng-coordination`，操作前 `git pull --rebase` 已是最新（HEAD `156b008`）。
- 收尾状态：已收尾（2026-07-25，两仓改动已 commit/push）

### 补充（同日第二轮）— Owner 追问「有没有架构师的活该 PM 揽下来」后的全仓复扫

- **Owner 方法论纠正**：PM 不能只盯自己角色的活；协调仓里指派给本项目**其他角色**的活，PM 也该主动揽下来（承接登记 + 找到归属 + 给 Review 席位）。既有先例即 REQ-002「PM 承接登记、产出归 Architect」。本次首轮只盯 REQ-003，未做全仓复扫，Owner 追问后补做。
- **复扫方式**：全仓 grep 点名 ai 的条目（REQUESTS / STATUS / CHANGELOG / PROJECTS / contracts / communications）+ 通读 BCR 池 15 条状态表。
- **复扫结论 — 架构师的活分三类**：
  1. **REQ-002（唯一指派给 ai·Architect 的专属需求）：活早干完，账没销。** Architect 2026-06-29 已产出 4 岔路口结论（衍生 ADR-0001/0002，已用于 v0.1 设计，v0.1 已关闭），但协调仓 REQUESTS 行仍挂「已承接 / 转入迭代：ai v0.1（前置，**待启动**）」、沟通文档待跟进表仍写「ai·Architect **待启动**」——**滞留约 26 天**。本轮已销账。
  2. **REQ-003 内含的架构活已揽下**，走标准迭代流程：架构改造 + 适配层分层挂为 PRD 开放问题 O-2/O-3/O-6 交设计阶段 Architect，并把 Architect 列入 PRD R1 Review 方。
  3. **BCR 池无 ai·Architect 的活**：BCR-014 待 Owner+参谋长评估；**BCR-015（2026-07-25 新立，Owner 发起、参谋长代拟，全链路自动化 L1）** 回流清单 ai 为「待」——ai 是回流对象非执行方，但 L1 会改 PRD / 迭代记录 / 自测报告模板 + CI 门禁，**落地后 v0.2 PRD 可能需按新模板补「验收可执行化」**，PM 需跟踪。
- **本轮产出（coordination）**：
  - REQ-002 销账：REQUESTS 表状态「已承接」→「已关闭（2026-06-29 调研完成，2026-07-25 销账）」+ 转入迭代订正；REQ-002 段补「完成与关闭」+「销账迟滞说明」；沟通文档补 2026-07-25 销账条 + 待跟进表两行置已完成 + 收尾说明
  - REQ-003 补 **R-4 测试库造数依赖**（来源：ai·DevOps 在 PRD R1 Review 问题 4 指出——ai 对 `raw_items` 仅 SELECT 权限、无法自行造数，DB 模式冒烟存在硬性跨项目依赖，PM 侧动作）；就绪度确认表 + 待跟进表 + STATUS §4（5 项→6 项）同步
- **报给 Owner、不属 PM 权限的 3 处过期**（未擅改）：`PROJECTS.md:17/:31`「REQ-003 待 ai·PM 评估承接」（参谋长白名单）、`contracts/news-l1-db.md:5`「待 ai 侧承接确认」（xiaobao 权属）、`CHANGELOG.md:9` 同（随契约变更走）。
- **同期他会话进展（非本会话产出，仅记录）**：DevOps 已交 v0.2 PRD R1 Review = **未通过**（4 高 2 中 1 低：DB 模式探活面缺失 / 优雅停机与回滚残留锁未覆盖 / DB 连接异常口令脱敏 / 测试库造数未列前置；另给出 O-7 凭据注入结论与 O-3 运维侧约束 N≤8、轮询 10~30s、灰度期单实例），并实查出测试环境已不在（`.env` 不存在、8100 与 5432 均无监听）。
- 遗留问题/风险（本轮新增）：
  - PM 侧欠 PRD 修改进 R2（DevOps 4 条必改 + 2 条宜改）。**按 PM 手册启动检查第 7/8 条，等 Architect 与 Developer 也交 R1 后再一次性改进 R2**，避免改一次被下一位 Review 方推翻。
  - 响应侧迟滞已出现两次（REQ-003 二十天、REQ-002 二十六天），同源于「无时间节拍、靠恰好开对会话」。ai 侧对策落在会话启动扫需求池；机制侧覆盖在 REQ-004。
- 下一步入口（更新）：① Architect + Developer 补交 PRD R1 Review；② 三方齐后 PM 一次性修改进 R2；③ xiaobao 回应 6 项（P0 的 O-1 仍是硬阻塞）；④ 跟踪 BCR-015 L1 落地对 PRD 模板的影响。

## 2026-07-04 — 会话摘要（v0.2 标准迭代启动）
- 本次角色：PM（产品经理，ck）
- 动作：创建 v0.2 PRD 启动标准迭代，承接 v0.1 遗留问题。
- 背景：v0.1 已关闭（2026-07-04），遗留项转入 v0.2：4 条发布检查项（托管化 / logging / 生产多 provider / 耗时调优）、Architect 5 条观察项、D-2（上下文充分性阈值）、D-3（KB 空结果语义）。
- v0.2 范围：服务稳定性提升（结构化 logging、服务托管化、KB 空结果语义优化、工具并发）+ RunRecord 持久化审计记录 + 多 provider 生产验证准备。不改对外 news-l1 v1 契约。
- 本次产出：
  - 创建 `v0.2.md`：迭代记录，PRD 阶段 R1 待 Review
  - 创建 `v0.2-prd.md`：PRD R1（6 条用户故事 US-1~6，7 条验收标准 AC-1~7，5 条开放问题 O-1~5）
  - 更新 `INDEX.md`：当前状态切「v0.2 标准迭代 · PRD 阶段」、版本列表加 v0.2 行、下一步入口更新
  - 更新 PM 角色日志（本条）
- Review：指定 Architect + Developer，PRD R1 待 Review
- 关联迭代：v0.2（进行中）
- 关联 Change Note：无（初版 PRD，待 Review 后可能产生 CN）
- 遗留问题 / 下一步：
  - Architect + Developer 做 PRD R1 Review
  - 设计阶段 Architect 落地结构化 logging、工具并发、RunRecord 存储方案
  - 实现阶段 Developer 落地各项功能
- 收尾状态：进行中（v0.2 PRD 阶段，未收尾）

## 2026-07-04 — 会话摘要（v0.1 迭代关闭检查 + 收尾归档）
- 本次角色：PM（产品经理，ck）
- 动作：执行 v0.1 迭代关闭检查 9 项清单，通过后执行收尾归档。
- 背景：
  - 实现 R1 Architect + DevOps 两方 Review 均通过（2026-07-04）
  - 端到端联调 4 条用例通过（公网端到端 / 内网直连 / KB 命中 / KB 空结果）
  - Owner 抽样验收通过（coordination 2026-07-04 记录）
  - Developer 自测 40 passed
  - 前置小问题：test-report Architect 状态表未同步、36→40 passed 不一致、部署就绪耗时数字未更新
- 关闭检查结论：**通过**，9 项清单全部满足（含 2 项流程门禁：实现 R1 Review 已补结论、Owner 验收已确认）
- 本次产出：
  - 修 `v0.1-test-report.md`：Architect Review 状态表从「待Review」→「通过」；结论段 36 passed → 40 passed
  - 更新 `v0.1.md`：概览置「已关闭」、实现阶段表格状态更新、部署就绪检查置通过、CN-001/CN-002 归档、迭代关闭归档区全量填充（Owner 验收通过、关闭结论可关闭、遗留项清单）
  - 更新 `INDEX.md`：当前状态置「v0.1 已关闭」、版本列表加 summary 链接、最近收尾摘要加 PM 行、跨任务待办 REQ-001 + 端到端联调置已完成、Change Notes 加归档提示
  - 生成 `v0.1-summary.md`：迭代归档摘要（基本信息 / 各阶段状态 / 交付物 / AC 映射 / CN / 测试质量 / 遗留项 / 关键数据 / 下一步）
  - 更新 PM 角色日志（本条）
  - coordination 侧：REQ-001 置已关闭（见 coordination `communications/REQ-001-news-l1.md` + `REQUESTS.md`）
- 关联迭代：v0.1（已关闭）
- 关联 Change Note：CN-001 / CN-002 已随 v0.1 归档
- 遗留问题 / 下一步：
  - v0.2 立项（PM，待 Owner 确定范围）：建议含发布检查项 1/2（托管化 + logging）+ D-3（KB 空结果语义）+ Architect 观察项 1/2
  - 部署阶段：DevOps 托管化 + 生产多 provider 验证
  - 非阻塞遗留项：4 条发布检查项 + Architect 5 条观察项 + D-2 + D-3，全部转入下一迭代
- 收尾状态：已收尾（v0.1 已关闭）

## 2026-06-30 — 会话摘要（设计 R1 PM Review）
- 本次角色：PM（产品经理，ck）
- 动作：作为设计文档指定 Review 方之一，review `v0.1-design.md`（R1）。
- 结论：**通过**。设计完整承接 PRD（US-1~7 / AC-1~9 全映射）+ CN-001（Tavily 直连、KB 方案 b 占位），范围无跑偏。附 2 条非阻塞建议：① [中] 4.6 prompt 明确产出五类标签（对齐 AC-2）；② [低] 明确翻译=zh / 摘要语言长度（收敛 O-4，对齐 AC-3/4）。
- 边界：只审需求覆盖 / 范围，未审架构优劣 / 技术选型（Developer / DevOps 边界）。
- 关联迭代：v0.1（设计阶段 R1）
- 遗留 / 下一步：待 Developer、DevOps R1 review；三方通过则设计定稿进实现阶段。
- 收尾状态：进行中（设计 R1，未收尾）

## 2026-06-29 — 会话摘要（v0.1 PRD 启动 + 工具能力诉求）
- 本次角色：PM（产品经理，ck）
- 动作：据 REQ-002 架构结论创建 v0.1 PRD 启动标准迭代；在 REQ-001 交流文档向 xiaobao 提工具能力诉求（非新需求，派生自 REQ-001 的协作沟通）。
- 产出：`iterations/v0.1-prd.md`（R1 待 Review）、`iterations/v0.1.md`（迭代记录）；INDEX 切「v0.1 标准迭代 · PRD 阶段」。
- v0.1 范围（Owner 确认）：news-l1 五项**全量**真实化（路径=先最小骨架跑通→逐项填满）；多 provider fallback **进**、RunRecord **延后**；生态薄接缝只留接口形状。不做 L0 / `score_total` / 强重入 / 第二调用方实现 / 改契约。
- 工具后端分工（Owner 2026-06-29 拍定）：**KB 检索→xiaobao 提供**（已在 REQ-001 交流文档提诉求，coordination 待响应）；**链接读取→ai 自抓 HTTP**；**Web 搜索→Owner 提供 key、ai 自配**。
- Review：指定 Architect + Developer，PRD R1 Review中。
- 关联迭代：v0.1（PRD 阶段）
- 遗留/下一步：Owner 待办——提供 web search key；切 Architect/Developer 做 PRD R1 Review；KB 检索待 xiaobao 响应（交流文档「待跟进」已登记）。
- 收尾状态：进行中（迭代 PRD 阶段，未收尾）

## 2026-06-29 — 会话摘要（产品定位升级 + REQ-002 承接）
- 本次角色：PM（产品经理，ck）
- 动作：理清 ai 产品定位 → Owner 拍板正式升级定位 + 跨仓决策/承接/元信息留痕（非迭代 Product Brief）。
- 背景纠偏：初次跳过调研、直接用选项题拍定位（与已拍板 D5 冲突），经 Owner 指正后补做 coordination 真源调研（`contracts`/`decisions`/`REQUESTS`/`communications`/`STATUS`），发现 ① D5「不做泛化多项目通用平台」② 待承接的 REQ-002 架构调研。
- 产品定位结论：Owner 2026-06-29 拍板把 ai 从 D5「xiaobao 专属」升级为「**niuma-cheng 生态内部通用 AI 处理中枢**」；仅 supersede D5，D1–D4 仍有效；落地「通用骨架预留扩展点 + 先做 xiaobao news-l1」，v0.1 不为不存在的第二调用方写实现。定位 Brief 经两轮 Owner review 定稿。
- coordination 留痕（已 push，commit `7fa7820`）：新建 `decisions/0002`（supersede D5）+ `0001` 标注；`REQUESTS` 回填 REQ-002 ai PM 承接 + 建 `communications/REQ-002-arch-research.md`；`STATUS` 元信息台账登记 ai「定位」变更（第 1 棒，PROJECTS/根索引同步转协调/根会话）。
- 角色边界：数据架构定位属 Architect，本会话未替架构拍板；REQ-002 架构方案实质产出归 Architect。
- 关联迭代：v0.1（待启动，前置 REQ-002 架构调研）
- 关联非迭代工作：产品定位升级 Product Brief（见 `ad-hoc/2026-06-29-product-brief-positioning.md`）
- 关联 Change Note：无
- 遗留问题/风险：元信息同步差第 2/3 棒（`PROJECTS.md` / 根索引）未闭环，已登记台账转交对应会话。
- 下一步入口：切 Architect 承接 REQ-002 做数据架构定位（读 Horizon/aggregator、答 4 岔路口）→ 回 PM 创建 `v0.1-prd.md`。
- coordination 依据：`/root/Project/niuma-cheng-coordination`，操作前 already up to date（HEAD `85fc21f` → push `7fa7820`）。
- 收尾状态：已收尾（2026-06-29）

## 2026-06-22 — 会话摘要（BCR-002 真源回流）
- 本次角色：PM（产品经理）
- 动作：从框架真源同步工作流基线（`sync-downstream.sh`），回流 BCR-002。
- 涉及文档：本项目 `.workflow-version`、`docs/baseline/cross-project-collaboration.md`、`docs/progress/INDEX.md`；coordination 仓 `REQUESTS.md`、`PROJECTS.md`、`communications/README.md`。
- 结论：本项目 baseline 由 `agent-workflow@c8c66ce` 同步至 `@1b01fba`，已包含 BCR-002 真源落地：跨项目 `communications/` 从「按项目对一份」改为「按需求一份」，命名为 `communications/{REQ-id}-{短名}.md`，REQ 与沟通文档一一对应。
- coordination 依据：`/root/Project/niuma-cheng-coordination`，同步前 `git pull --rebase` 已是最新；BCR-002 真源落地记录为 `b5a29a3`（merge `0a76dca`），真源当前 HEAD `1b01fba`；coordination 最新记录 `0dd6e02` 已将 BCR-002 置为「已回流下游」（ai `1b01fba`、xiaobao `91b442a`）。
- 关联迭代：无（框架维护，非迭代）
- 关联非迭代工作：BCR-002 真源回流（见 `INDEX.md` 非迭代工作表）
- 关联 Change Note：无
- 遗留问题/风险：无。BCR-002 已在 coordination 置为「已回流下游」；本会话未改 xiaobao `docs/progress/`。
- 下一步入口：REQ-001 下一步不变——Owner 确认后由 PM 创建 `v0.1-prd.md` 启动标准迭代。
- 收尾状态：已完成（2026-06-22）

## 2026-06-22 — 会话摘要（工作流真源同步）
- 本次角色：PM（产品经理）
- 动作：从框架真源同步工作流基线（`sync-downstream.sh`）
- 涉及文档：本项目 `docs/baseline/` 6 文件 + `.workflow-version`；真源 `agent-workflow@c8c66ce`
- 结论：本项目 baseline 由 `agent-workflow@90edee2` 同步至 `@c8c66ce`，落地 **P8 基线修正提案（BCR）机制**——`runtime.md`/`mechanisms.md`/`multi-agent-workflow.md`/`non-iteration-quick.md`/`work-modes.md` 把"基线修正提案"指向从「带回真源仓库」改为「写 `BCR-###` 入 coordination 基线修正提案池」；`cross-project-collaboration.md` 新增《基线修正提案流转（BCR）》整节。`docs/progress/`、`project-context.md`、`docs/knowledge/`、入口文件未受影响。
- 关联迭代：无（框架维护，非迭代）
- 关联非迭代工作：工作流真源同步（见 `INDEX.md` 非迭代工作表）
- 关联 Change Note：无
- 遗留问题/风险：今后本项目发现框架需改时改走 `BCR-###`，不再写 `[基线修正提案]` 人肉带回。
- 下一步入口：不变——Owner 确认后由 PM 创建 `v0.1-prd.md` 启动标准迭代。
- 收尾状态：已收尾（2026-06-22，改动已 commit/push）

## 2026-06-22 — 会话摘要
- 本次角色：PM（产品经理）
- 动作：跨项目需求承接留痕（REQ-001）
- 涉及文档：coordination 仓 `REQUESTS.md` / `communications/xiaobao__ai.md` / `STATUS.md`；本项目 `docs/progress/INDEX.md`
- 结论：正式承接 xiaobao 提报的 REQ-001「新闻 L1 处理」，补齐「正规提报（xiaobao · Developer）→ 承接（ai · PM ck）」留痕闭环；规划转入 ai v0.1 标准迭代（待启动）。按 Owner 决策**仅补登承接方/转入迭代字段，REQ-001 状态保持「联调中」未改**。
- 关联迭代：v0.1（待启动，尚未创建 PRD）
- 关联非迭代工作：REQ-001 承接留痕（跨项目协作）
- 关联 Change Note：无
- 遗留问题/风险：
  - ai 代码各节点仍为 stub（`graphs/news_l1.py` `llm_process` 返回占位评分/标签/摘要/翻译），真实 L1 处理待 v0.1 迭代实现。
  - `project-context.md` 的「项目一句话/业务边界」仍为「xiaobao 新闻专用」旧定位，与 Owner 新确立的「生态内部多项目通用 AI 中枢」定位不一致，待后续更新。
- 下一步入口：Owner 确认启动 ai v0.1 标准迭代时，由 PM 创建 `docs/progress/iterations/v0.1-prd.md`，把 REQ-001 转为标准迭代。
- 收尾状态：已收尾（2026-06-22，两仓改动已 commit/push：ai `752bf14`、coordination `ab2543c`）
