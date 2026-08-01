# Developer 角色日志

## 2026-08-01 — CN-009 受影响角色确认（Developer）

- 本次角色：Developer
- 动作：Change Note 确认（变更 1 直接进实现范围，开工前须落地）
- 涉及文档：`docs/progress/iterations/v0.2-cn-009.md`（填本角色确认意见）；核对设计 §4.6 写回 SQL、§2.3 `WriteBackPayload`、`src/agent_hub/schemas.py:57`
- 结论：**已确认，四条变更全部同意**；附一条必须补的实现落点 + 一处章节号订正。
  1. **必须两处都加，缺一即静默失效（本 CN 未写，是我补的）**：设计 §4.6 写回是 `INSERT ... ON CONFLICT (raw_item_id) DO UPDATE SET ...`，而 C-3 定案是 **ai UPDATE 占位行**——占位行由 xiaobao 在 L0 通过时创建，故**「冲突并走 DO UPDATE 分支」是常态而非例外**。若只把 `needs_context` 加进 INSERT 列清单、漏了 `DO UPDATE SET`，该列会**永远保持 NULL 且不报错**——与本 CN 要修的「列存在但信号永远缺失」**完全同型**，成因只是从「没写列」换成「没写 SET」。实现两处一起加，自测断言须覆盖「占位行已存在」这条路径（只测 INSERT 分支会漏）。
  2. **章节号订正**：本 CN 正文与 Architect 行均写「设计 §3.4 写回映射」，但 **§3.4 是 claim SQL**；实际落点是 **§2.3 `WriteBackPayload`** + **§4.6 写回 SQL 两处**。
  3. **类型与权限核实无问题**：`L1Output.needs_context` 为 `bool = False`（`schemas.py:57`），不会为 None，直接映射 boolean 列；`processed_news` 是**表级** SELECT/INSERT/UPDATE，新列自动覆盖，「无 GRANT 动作」正确。
  4. **变更 4 补一条自测排期约束**：并发 claim 与事务回滚（测试 6/7/22/23）**可全程 `ROLLBACK` 不消耗队列**（C-6 实证已验证该做法），而**端到端冒烟（测试 20）必然消耗**。自测计划把两类分开，**优先保留至少 1 条 `domain_tags` 非空条目给端到端**——否则「有值」路径（同时进 prompt 与 `kb-search` 查询条件）会直到生产才首次执行。
  5. **列迁移不阻塞开工**：对方 `ALTER TABLE ADD COLUMN` 未落地，但单测/黄金样本走 fixture 与 mock、不碰真实库；仅真实库测试（7/20/22/23）需列到位。按「有列」实现并推进单测，冒烟前由 DevOps 实查一次即可，不必互等。
  6. **变更 2/3 无实现动作**：`score_total` 差异性质变为「有方案的临时状态」，联调判读须知照旧；`language` 我方本就写「固定 `'zh'`」。
- 关联迭代：v0.2
- 关联 Change Note：CN-009（本条）
- 遗留问题/风险：① 若实现时漏了 `DO UPDATE SET` 子句，会重演本 CN 要修的静默缺失（已写入确认意见与自测断言要求）② `domain_tags` 非空条目稀缺（实查为准），自测消耗需用 ROLLBACK 保护 ③ 对方列迁移须在联调冒烟前落地，归 DevOps 前置核对
- 下一步入口：CN-009 待 Architect / DevOps 确认 → Architect 按订正后的落点（§2.3 + §4.6）补设计 → 实现阶段开工（§6.1 步 0 先录黄金样本）
- 收尾状态：已收尾

## 2026-07-30 — 一次性确认 CN-003 / CN-004 / CN-007 / CN-008（Developer）

- 本次角色：Developer
- 动作：Change Note 确认 ×4（补齐本角色全部待确认项；此前已确认 CN-005 / CN-006，至此 CN-003~008 六个全部确认完毕）
- 涉及文档：`v0.2-cn-003.md` / `-004.md` / `-007.md` / `-008.md`（各填本角色确认意见）；核对设计 §3.4 / §4.6 / §4.7 / §4.10 / §4.11 / §4.12、`llm/client.py:99-111`、`tools/kb.py:37-40`
- 结论：**四个全部确认同意**，其中 CN-008 附两条实现注意点。
  1. **CN-008（最实质，且源于我在 CN-005 提的问题）**：事务边界点算与三条不等式**逐条复核成立**——claim 4 条 / 写回 3 条 / 失败 2 条语句与设计对得上；`DB_WRITEBACK_BOUND = 3 × 6000 = 18s ≤ 260−240 = 20s` ✔、`DB_OP_BOUND = 5+18 = 23s` → `1 × 263s < 1080s` ✔、`3s < 4s < 5s` ✔。**拆两个量正确**（收尾余量只需覆盖停机瞬间的写回，AC-3.6 要覆盖 claim→写回完整链路，原式漏了 claim）；另核失败路径 250s < 写回路径 263s，取 263s 覆盖最坏成立。**「PG 无内建事务执行超时」的根因判断正确**——事务级上界只能来自应用层 `asyncio.wait_for`，不能靠 `ALTER ROLE` 绕开。**我在 CN-005 提的是「假设不成立」，本 CN 给的是「换封堵方式」，数值仍是 18s、变的是它成立的前提**。
  2. **CN-008 两条实现注意点**：**(a)** `wait_for` 取消后 psycopg3 连接可能不能安全归还池（ROLLBACK 本身也需与服务端通信），`psycopg_pool` 会检测丢弃重建——功能安全但每次超时消耗一个连接，池 `min=1/max=3` 下超时频发会抖动；`statement_timeout=4s < tx_timeout=5s` 的价值正在于让单条卡死由服务端先中断，`wait_for` 只在「多条累计超时」时开火。测试 25② 里我会顺带断言超时后连接池仍可取连接。**(b)** `CancelledError`（BaseException，外部取消/优雅停机，须向上传播）与 `TimeoutError`（Exception，超时，计入重试）的区分自洽，但**一旦有人在 `run_tx` 外层写 `except BaseException`，超时重试与优雅停机会同时失效**——与 O-8 的规定呼应，实现时按 `except Exception` 写并加注释。
  3. **CN-003**：我 R4 的中①（`READ COMMITTED`）中②（AC-2.2 判据拆分）均已并入且位置摆对。**补一条实现侧事实**：C-6 已闭合、claim 用写法 A，而**写法 A 不依赖 `READ COMMITTED`**，该约束现在守的是写法 B 这条备用路径——**启动期断言仍须保留**，否则将来切写法 B 那天没人会回头补前提。变更 2 的黄金样本四类由我在实现阶段录制，承接时守两条：步 0 必须在改造动手前完成；四类样本**均不含「工具成功但无结果」场景**（该场景是 AC-7 有意变更的对象，混进去会让「行为不变」与「有意改变」在同一判据下打架）。
  4. **CN-004**：变更 3 的 `budget_exhausted` 确认落地，其价值在于把两类处置指向分开（段上限分配 vs provider 侧）。**变更 1 虽被 CN-007 整条撤回，但它引出的「入向映射须做 jsonb 类型判定」必须幸存**——数据源换成 `sources.domain_tags` 后理由更硬：该列类型不统一（实机 4 行中 2 array / 2 object），5 条冒烟条目 JOIN 出的全是 `{}`，按数组直接构造会 `MappingError(client_error)` → 不可重试 `final_failed` → 冒烟全废。
  5. **CN-007**：撤回成立，但实现基准按已收紧口径记——「取数路径等价成立、值一定非空不成立」，冒烟阶段该字段实际仍为空，联调时不得误判为映射 bug。变更 5 的一句话分量最重：**KB 迁机后「主流程不中断、只持续降级」**——没有报错没有告警，只有评分标签静默变差；我会在自测报告里把「KB 是否真的命中」作为独立观察项，不让它混在「主流程通过」里算过。
- 关联迭代：v0.2
- 关联 Change Note：CN-003 / CN-004 / CN-007 / CN-008（本条）；CN-005 / CN-006 此前已确认
- 遗留问题/风险：① CN-008 的配置项订正（新增 `AI_DB_TX_TIMEOUT_MS=5000`、`STATEMENT 8000→4000`、`LOCK 5000→3000`）与 PRD AC-4.7 表述待 PM 同步——**CN-005 方案 A 的 `8000→5000` 已被本 CN 取代，不要再按那组值落地** ② 6i / 6j 待 xiaobao 回应（`domain_tags` 预期类型 + `tasks.status` 取 `running` 还是 `processing`）③ ~~我在 CN-005 提的「`_on_worker_done` 判定 dead 后主动退进程」待判断~~ → **已自行撤回（2026-07-30，Owner 指出「健康检查已顺延 v0.3、且留了痕」）**：CN-005 变更 1 顺延的是「worker 协程级自动恢复」这个**能力**、且正文点名 `_on_worker_done`，Owner 拍板时已知晓并接受该边界；我按**实现路径**切而范围决策按**能力**切，用路径差异给已拍板结论开口子，与范围纪律相悖。v0.2 不做，随 v0.3 healthcheck timer 一并考虑，不再需要任何判定
- 下一步入口：六个 CN 的 Developer 侧已全部确认，实现依据齐备 → 待 PM/Architect 落实 CN-008 的配置订正 + 各 CN 执行状态勾选 → **进实现阶段**（§6.1 步 0 先录黄金样本四类，再自底向上五步）
- 收尾状态：已收尾

## 2026-07-30 — CN-005 受影响角色确认（Developer）

- 本次角色：Developer
- 动作：Change Note 确认（变更 3 的超时配置与 AC-3.6 新不变式是实现依据、变更 6 的字段进实现清单）
- 涉及文档：`docs/progress/iterations/v0.2-cn-005.md`（填本角色确认意见）；核对设计 §2.6 校验表与 §4.6 写回事务的语句构成
- 结论：**已确认，六条全部同意**；附一条补充、一条观察。
  1. **DevOps 的算术订正我独立复算成立**：现默认值 `(2+1) × (8000+1000) = 27s`，而门禁要求 ≤20s → 为假、**worker 拒绝启动**；方案 A `(2+1) × (5000+1000) = 18s ≤ 20s` ✔、`1 × (240+18) = 258s < 1080s` ✔，与文档已写的 18s / 258s 吻合，确实只需改两个默认值。公式**偏保守约 1s**（真实 `3×5 + 2×1 = 17s`，公式把间隔算了 3 次），高估方向安全、不必改。
  2. **补充：`statement_timeout` 是「每语句」超时而非事务超时**（DevOps 与 Architect 均未涉及）。写回事务含三条 SQL，故公式把单次尝试上界取作 `statement_timeout` 隐含了「一次尝试内至多一条语句耗尽超时」的假设；严格理论上界是 `3 × statement_timeout = 15s` → `3 × (15+1) = 48s > 20s`。**不推翻方案 A**（第一条超时即事务 abort、后两条不执行，且三条均为毫秒级主键操作），但该假设应写进 AC-4.7 第 2 条——否则将来调大超时或往写回事务加语句时会再现「式子算得过、实际不够」，**本迭代已栽过两次同型**（CN-004 A 项 + 本条）。
  3. **变更 6** `budget_remaining_ms` 确认进实现清单（设计 R2 复审中已评价其价值：`budget_exhausted` 只说"耗尽了"，逐步剩余预算才能定位是哪段吃掉的）。
  4. **其余四条对实现的影响**：变更 2 的应用侧启动门禁只校验两个量（三层关系归部署脚本），边界清楚；变更 5 应用侧零改动（照样写 stdout）；变更 1/4 不改实现动作，但 `_on_worker_done` 仍须照设计实现。
  5. **一条观察（提出但不主张，属范围决策）**：v0.2 已有 systemd 托管，而 `_on_worker_done` 目前只标 `dead` 不退进程，等于放弃了已到手的自动拉起能力。若判定 `dead` 后让进程以非零码退出，`Restart=on-failure` 即可兜底，成本约一行、不需要 v0.3 的 healthcheck timer；代价是 `/health` 的 503 诊断窗口消失（但 `dead_reason` 已进 journal，信息不丢），风险是配置类错误会重启循环、需 `StartLimitBurst` 兜底。变更 1 顺延 v0.3 的是「健康检查驱动的重启」，这是另一条路径，故交 PM / Architect 判断是否属 v0.2 范围。
- 关联迭代：v0.2
- 关联 Change Note：CN-005（本条）
- 遗留问题/风险：① 变更 3 的两个默认值须由 PM/Architect 实际订正，否则实现阶段第一次启动即被自己的门禁拦下 ② 我的补充②若不写进 AC-4.7，将来改超时值或加写回语句时会重现同型问题
- 下一步入口：CN-005 三方确认已齐（DevOps 附条件 / Architect / Developer）→ 待 PM 落实两个默认值订正并勾选执行状态 → 实现阶段开工
- 收尾状态：已收尾

## 2026-07-30 — CN-006 受影响角色确认（Developer）

- 本次角色：Developer
- 动作：Change Note 确认（非 Review 轮次——不评判方案，只核实变更对实现的影响与其中的技术断言）
- 涉及文档：`docs/progress/iterations/v0.2-cn-006.md`（填本角色确认意见）；核对 `src/agent_hub/tools/kb.py:32-48`、设计 §3.3 / §3.4 / §8 测试 11/20
- 结论：**已确认，同意**。三条变更全部落在实现依据上（入向映射数据源、claim SQL 写法定选、KB 配置），故本确认有实质内容而非流程形式；三处技术断言逐一核实**均成立**：
  1. **变更 3「KB 零代码改动」成立**：`kb.py:37-40` 是 `token = getenv("KB_ADMIN_TOKEN","").strip()` + `if token: headers[...]`，不配置该 env 即不发头。禁止下发 xiaobao 全权 `ADMIN_TOKEN` 我完全同意——只读检索需求换来改源/删空间/同步规则的写权限，完全不成比例。
  2. **变更 1 归一化成立**：`if not isinstance(raw, list): return []` 覆盖实机存在的 `{}` object 形态。**DevOps 的实机订正是我最关心的一条**：`{}` 是 falsy，若「优化」成 `raw or []` 恰好蒙对而 `{"a":1}` 会漏 → pydantic 校验失败 → `MappingError(client_error)` → 不可重试 `final_failed` → 5 条冒烟一次报废。实现照 `isinstance` 写，不做等价改写。
  3. **变更 2 成立且强于 CN 表述**：CN-006 写「对方只验权限侧、仍须自测并发」，但设计 §3.4 显示 ai DevOps 已补齐并发侧（两会话 claim 拿到不同行、`SKIP LOCKED` 生效、全程 `ROLLBACK` 未耗队列）→ C-6 为两侧各验一半的完整闭合。按写法 A 实现，写法 B 留作权限变更退路。
- 关联迭代：v0.2
- 关联 Change Note：CN-006（本条）；其 PRD 侧连带动作由 CN-007 完成
- 遗留问题/风险：**§3.4 待确认 6j 是实现期最需盯的一条**——契约 C-2 的 `tasks.status` 枚举为 `running`，xiaobao 的 C-6 实证 SQL 写 `processing`，而 `tasks` 无 CHECK 约束，**写错不报错、只表现为对方状态不动**。按设计取 `running`，冒烟时把「对方状态是否随之推进」列为必查项，不靠无报错判断正确。
- 下一步入口：三方确认已齐（PM / Developer / DevOps 均 2026-07-30 确认）→ 待 PM 勾选执行状态并登记 `v0.2.md` Change Notes 表 → 实现阶段开工（§6.1 步 0 先录黄金样本）
- 收尾状态：已收尾

## 2026-07-28 — v0.2 设计 R2 复审（通过）

- 本次角色：Developer
- 动作：Review（设计 R2 三方复核第一交；PM / DevOps 待做）
- 涉及文档：`docs/progress/iterations/v0.2-design.md`（追加 R2 Review 记录 + Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（设计门禁 + Review 记录）；逐条实读 §2.4 / §3.2 / §3.4 / §4.5~4.7 / §4.11 / §4.12 / §6.1 / §8 / §11；核对 `tests/test_news_l1.py:60-75` `NullTools`、`tests/test_news_l1_tools.py:16-45` `FakeTools` 的 `ToolResult` 返回语义
- 结论：**设计 R2 Developer 复审通过**（2 中 2 低，均不阻塞定稿）。
  1. **R1 八条全部收敛到位**（逐条实读核验，非只看修改记录）：`release` 补进 §3.2 且联动 §4.7 失败表「主动释放」独立行 / §7.1 取舍 / 测试 21；§1.3 与 §6.1 步 4 的 `run_task` 签名已一致；§4.5 预算改走 `complete_json(timeout_ms=budget.remaining_ms())` 并写明「本处只需一行改动」；`MIN_SEGMENT_MS` 进 §2.4 定义 + §2.6 配置 + 测试 18；`l1_attempt` 移入 §3.4 步骤 4 且 §4.6/§4.7 重复递增已删干净 + 测试 23 验崩溃窗口；§6.1 步 1/2/4 均已补黄金样本判据；低⑧ 按 PRD 边界不改判、只补 §7.2 与日志标注。
  2. **三处处置强于我的原建议**：① 写回重试把可重试 PG 错误类（连接错误 / `deadlock_detected` / `serialization_failure`）与确定性错误分开列举，并算清重试耗时与停机宽限期 20s 余量的关系；② `slice_for` 阈值之外还统一了 `error_kind=budget_exhausted`（配合 CN-004），把「预算跳过」与「工具故障」在日志层彻底分开；③ `release` 不止补方法，还把「为什么不能复用 `mark_failed`」写成正文旁注——实现最可能图省事的正是这一处。
  3. **中①黄金样本与 AC-7 的边界未声明**：步 3 同时做「要求行为不变的 async 改造」与「有意改变行为的 AC-7 三分支」，而完成判据是「黄金样本四类逐字段比对通过」，样本 ② 恰好断言 `tags.processing` 的 `degraded:` 标记完全一致——而 AC-7 修复正是要改变空结果时的 `degradations` 产出。实查现有 fake：`NullTools` 三方法均返回 `ToolResult(ok=False, error="disabled")`、`FakeTools` 默认 `ok=False, error="failed"`，**均为故障语义**，故照现有 fake 录制不会撞车；但这是巧合非设计保证（`FakeTools` 支持传入 `ok=True, items=[]`）。建议 §6.2 写死「四类样本均不得含『调用成功但无结果』场景，该场景由测试 17 独立覆盖且期望值是改造后的新语义」。
  4. **中②§8 测试 8 的 `error_kind` 漏改**：§11 称四处正文的 `timeout` 已全部订正为 `budget_exhausted`（我逐处核对确已订正），唯独**验证这件事的测试 8** 仍写 `error_kind=timeout`，与 §4.5 直接冲突；且与新增测试 18 断言同一件事却取值相反，两条测试会互相打架。CN-004 变更 3 的要点正是「两者必须分开记」，漏改位置恰是它的验证点。
  5. **低③④**：§3.2 末尾旁注仍写「四个方法」（新增 `release` 后应为五个，且该句就在新增方法正下方）；预算跳过时 `tool_budget_used` 是否递增未说明（与 `tool_summary` 在同一 updates 字典 `news_l1.py:209-212`，不明确会白吃一次 `max_tool_calls` 配额、影响 `_budget_ok` 路由判定）。
  6. **R2 新增内容评估**：§4.11 四行判定表把三种情形在 `degradations`/`tool_summary`/日志三维度定死，可直接照写；**把 AC-7 与 deadline 并入步 3「同一段代码只动一次」的判断正确**（三处 `if result.ok and result.items:` 确实同时是两件事的改动点）；§4.12 新增 `budget_remaining_ms` 对灰度期定位「预算被谁吃掉」很有用；测试 17~24 与新增条款一一对应、无凑数项。
  7. **工作量**：§4.11/§4.12 属已授权范围内的落点补齐（AC-7、AC-6 本就在 PRD 内，R1 只是漏了落点），两个新配置项是我方 R1 意见的直接产物。**与 PRD §8 成本表仍相符，未扩范围。**
- 关联迭代：v0.2
- 关联非迭代工作：无
- 关联 Change Note：CN-004（`error_kind` 新增 `budget_exhausted`，本轮中② 即其漏改点）
- 遗留问题/风险：① 中①② 若不在定稿前订正，会分别导致「录样本时踩坑要到步 3 才暴露」与「两条测试断言打架」② `domain_tags` 在 DB 模式实际恒为 `[]`（发现 B）仍待 C-14 确认 ③ 测试 20（AC-10.2 端到端）前置为发现 A 闭合（xiaobao 补建 task 行）
- 下一步入口：PM / DevOps 完成设计 R2 复核 → 三方齐后设计定稿 → 进实现阶段（按 §6.1 步 0 先录黄金样本，再自底向上五步）
- 收尾状态：已收尾（复审交付完成）

## 2026-07-28 — v0.2 设计 R1 Review

- 本次角色：Developer
- 动作：Review（设计 R1 三方之一：PM / Developer / DevOps）
- 涉及文档：`docs/progress/iterations/v0.2-design.md`（追加 R1 Review 记录 + Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（设计门禁 + Review 记录）；实读 ADR-0003 / ADR-0004、`v0.2-prd.md` R4 + CN-003；核对 `llm/client.py:88-160/211-221`、`graphs/news_l1.py:327-335`、`tools/base.py:33-60`、`tasks.py:55-72`
- 结论：**设计 R1 Developer Review 未通过**（1 高 5 中 2 低）。**无方向性分歧**——协议分层、三段式事务、`lock_token` 两段式、deadline 传递、五步自底向上改造都能直接落地；本轮问题全部是「实现会话照文档写会卡住或走偏」的具体缺口，修正量小。
  1. **高①`PullSource` 协议缺 `release`**：§4.2 主循环第 474 行 `await source.release(item)`，而 §3.2 只定义四个方法 → 照文档实现直接撞 `AttributeError`。且语义未定义：停机释放「已 claim 未处理」的条目应退回 `queued` + 清锁 + **不动 `attempt`**；复用 `mark_failed(retryable=True)` 会污染 `attempt` 与 `last_error_kind`，让一次正常停机看起来像处理失败并白耗一次重试配额。
  2. **中②`run_task` 签名文档自相矛盾**：§1.3 第 53 行「签名不变」vs §4.5 第 497 行「新增 `budget` 参数」。认同 §4.5 的实质（budget 是数据源无关量，不违反 AC-2.2），应订正 §1.3。
  3. **中③LLM 预算传递路径写反方向，实际比设计描述的更简单**：`budget_ms` 是 `__init__` 构造参数（`client.py:88-93`）而 `remaining_ms()` 每条不同，走它需每条重建 client。核对 `client.py:99-111` 确认——**链共享预算语义 v0.1 本就正确实现**（每 provider 前算 `remaining = budget - elapsed`，`<=0` 记 `budget_exhausted` 并 break）。本迭代只需把 `news_l1.py:333` 的 `timeout_ms=inp.options.timeout_ms` 换成 `budget.remaining_ms()`，**一行**。AC-3.8 注的「v0.1 未传」应精确为「`budget_ms` 构造参数从未被使用（`build_ai_client()` 不传，`client.py:215`），`complete_json` 的 `timeout_ms` 一直在传」。
  4. **中④`slice_for` 极小残值会发起必然超时的调用**：跳过闸门只有 `exhausted()`（`remaining<=0`），故 `remaining=300ms` 时不跳过 → `slice_for(15000)` 返 300ms → 调 KB 必然超时 → 按 AC-7.2 记为「工具故障」进 `degradations`。预算耗尽被误报成 xiaobao KB 挂了，灰度期最费时间的一类误报。需最小段阈值（如 1000ms）+ 跳过条件改用 `slice_for(...)==0`，统一记 `degraded:{tool}_budget_exhausted`。
  5. **中⑤`l1_attempt` 递增时点在写回事务**，与 PRD AC-5.1「镜像值、同事务一并推进」不符：`tasks.attempt` 在 claim 事务 +1（§3.4 步骤 2），`l1_attempt` 在 §4.6/§4.7 才 +1 → claim 后崩溃（240s 窗口，最可能的崩溃点）两者永久差 1，xiaobao 侧看到的展示值失真。建议移入 claim 事务（§3.4 步骤 4 已在写 `raw_items`，成本为零），并删除写回/失败路径的重复递增。
  6. **中⑥DB 写回失败直接丢弃结果，未做任何重试**：一条已花 240s 预算 + 一次 LLM 调用（含费用）的结果，因几毫秒的连接抖动或死锁被整个丢弃，条目还额外占队列 30 分钟；而写回事务是毫秒级、失败多为瞬时。与 §1.2「高可靠」准则不一致，且是 §7.1 八条取舍里**唯一没记录理由**的省力选择。建议有限重试 2 次（间隔 1s，仅对连接错误/死锁/序列化失败），且须在预算之外。
  7. **低⑦⑧**：§6.1 正文「每步都跑黄金样本」与表格完成判据不一致（只有步 3 写了）；出向映射失败是确定性失败，可重试语义会白耗 3~5 次 × 240s，建议 §7.2 记一行 + 日志标注 `mapping_error` 子类型。
  8. **指派项结论**：① 协议与 SQL——除问题 1 外可直接照写，两种 claim SQL 无歧义，`score_total`/`id` 不出现的约束写得足够醒目（§2.3「不是写 NULL，是根本不提及」是最易写错处）；② async 切分——五步自底向上正确，每层下游都已 async，不会出现同步/异步混用中间态；③ 黄金样本——四类覆盖到位，样本 ④ 点名 `httpx.TimeoutException` vs `asyncio.TimeoutError` 是本次改造最易静默变化处，§7.2 对 mock 保真度的自我质疑尤其到位；④ **工作量与 PRD §8 相符，未发现悄悄扩大范围**（协议分层的增量来自 §0 准则裁定 2 与 DevOps 发现 B，属已授权）。
- 关联迭代：v0.2
- 关联非迭代工作：无
- 关联 Change Note：无（设计据 DevOps 实机发现 B 要求 PM 订正 PRD AC-8.2「不再恒空」，属 Architect 已提的 C-14 转达项）
- 遗留问题/风险：① 问题 1 不修则实现阶段必卡 ② 问题 4/5/6 都属「不修也能跑通、但会在灰度期变成难查的现象」——误报工具故障 / 展示值漂移 / 结果丢失 ③ `domain_tags` 在 DB 模式实际恒为 `[]`（发现 B），DB 模式处理质量系统性低于 HTTP 模式且不报错，待 C-14 确认
- 下一步入口：PM / DevOps 完成设计 R1 Review → Architect 按三方意见改 R2 → 设计定稿后进实现阶段（按 §6.1 五步 + 步 0 先录黄金样本）
- 收尾状态：已收尾（Review 交付完成）

## 2026-07-27 — v0.2 PRD R4 复审（通过）

- 本次角色：Developer
- 动作：Review（R4 三方复审第一交；Architect 随后通过·附条件，DevOps 待做）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 R4 Review 记录 + Review 状态表本角色行推进至 R4）、`docs/progress/iterations/v0.2.md`（PRD 门禁 + Review 记录）；实查 `tools/link_reader.py:23`、`tools/base.py:50`、`graphs/news_l1.py:121/142/269/407` 的 URL 判定链路
- 结论：**PRD R4 Developer 复审通过**（2 中 2 低，均不阻塞定稿）。
  1. **R1 六条 + R3 七条已全部收敛**，其中 5 条逐字采纳：AC-9.5（HTTP 并发不退化，N≥3 总耗时 <1.5× 单条）、AC-9.4（黄金样本外部化写死，连"为什么不能只靠单测"的论证与 21/36 例实查数据一并收进）、AC-8.2（`l0_label` 空值兜底为 `[]`）、O-9（psycopg3(async)，Architect 采纳）、§5（部署环境 + 口令双待办前移为实现阶段开工前置）。
  2. **认领一处订正**：AC-2.4 的 URL 判定落点我 R1/R3 两轮都引错。实查确认——`_should_link_read`（`:269`）走 `tools.extract_url` → `base.py:50` → **`link_reader.py:23`**（额外要求 `http(s)://` 前缀），而我引用的 `news_l1.py:407` `_extract_url` **只被 `:121` `ingest_context_node` 用**、不检查前缀。结论方向（不回填 URL 键则 link_read 静默失效）成立，但落点指错，**且我没发现两处判定不一致**——Architect 的发现比我原问题更深一层。R4 的规范化处置（统一为带前缀、三例验证）充分。
  3. **O-8 还订正了我的 async 划线说法**：判据应为「无 IO **且耗时为毫秒级**」，而非我说的"有 IO 才 async"——同步节点在协程中被直接执行、其耗时会占用 event loop，将来纯计算节点变重必须移出。订正准确，接受。
  4. **中①AC-3.7 的 fallback 隐式依赖 READ COMMITTED**：「UPDATE 阻塞→重新求值→`status='queued'` 不成立故排除」只在 READ COMMITTED（PG 默认）下成立，REPEATABLE READ 及以上会抛 `could not serialize access` 而非安全跳过；且其并发语义与 `SKIP LOCKED` 不等价——并发 worker 的子查询是快照读、会选出同一批 id，第二个拿 **0 行**而非"另外 N 条"，v0.3 多实例时吞吐受限。建议补隔离级别约束 + 登记已知限制（并入设计阶段 O-6/O-9）。**Architect 独立确认了这条，并补充「v0.3 多实例前必须先解决 C-6」应写进 §4 顺延项。**
  5. **中②AC-2.2 判据前半句是同义反复**：「同一份处理核心……代码完全相同」只要不复制成两份必然成立，不可证伪；有牙齿的是后半句（核心内不得出现表名/列名/`raw_items`·`tasks` 概念）。建议拆为①静态（对 `tasks.py`/`graphs/`/`llm/` grep 数据源概念词，可自动化）②动态（两条控制流各跑通一条真实用例）。
  6. **低③**Review 状态表未推进到 R4（三方状态仍是 R3 结论）；**低④**单测分母口径不一（AC-9.4 写 40、§8 与实查为 36，应以 `pytest --collect-only` 实收集数统一）。
  7. **成本表复核（本轮指派）**：§8 的 R4 重写准确、可直接用于设计切分——「仍成立的红利（依赖方向）/ 已不成立的（代码零改动）」拆分消除了我 R3 指出的误导，五块表改动面与我实查一致。**块 4 风险由「中（依赖 C-2/C-5/C-6）」降为「中（C-6 已有 fallback）」确认成立**：fallback 只需列级 UPDATE 权限、不触发 `FOR UPDATE` 的表级权限检查，C-6 不再决定 claim 地基形态，只决定用哪种写法——这解除了我 R3 高③里「claim 是 worker 循环地基、返工代价大」的那一半担忧。
- 关联迭代：v0.2
- 关联非迭代工作：无
- 关联 Change Note：无（Architect 的附条件「黄金样本四类路径覆盖」将由 PM 出 Change Note，与我 AC-9.4 的意见同源、方向一致，我认可其加严）
- 遗留问题/风险：① 中①中② 建议若不在定稿前订正，须在设计阶段 O-6/O-9 落定时一并处理 ② C-6 实证仍待服务器环境 + 口令到位（已有 fallback，不阻塞实现）③ 单测分母口径需在实现阶段以实收集数确认
- 下一步入口：DevOps 完成 R4 复审 → 三方齐后 PRD 定稿（Architect 附条件的 Change Note 须于设计阶段开工前落地）→ 设计阶段（O-2 协议按职责分层 / O-6 事务与连接含隔离级别 / O-8 async 切分与回归 P0 / O-9 驱动选型 / O-10 `locked_by` 规则）
- 收尾状态：已收尾（复审交付完成）

## 2026-07-27 — v0.2 PRD R3 复审

- 本次角色：Developer
- 动作：Review（R3 三方复审第一交，Architect / DevOps 待做）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 R3 Review 记录 + Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（PRD 门禁 + Review 记录）、`docs/progress/INDEX.md`；实查 `grep -rn "httpx\.(get|post|Client|AsyncClient)" src/`（全仓 4 处）、`grep -rn "\.invoke(" src/`、`tests/` fake 实现与用例分布
- 结论：**PRD R3 Developer 复审未通过**（3 高 2 中 2 低）。**R1 六条已全部收敛到位**，本轮新问题**全部落在 R2/R3 新增的 async 范围内**，属补充而非推翻。
  1. **R1 收敛复核（本轮指派任务）全部到位**：① `tags_v2` → C-10 定案 `processing` ② 同步/探活 → 改 async 地基，且我提的「处理中 ≥60s 时 `/health` 须 2s 内返回」被完整保留为 AC-9.3 ③ AC-7 三点全采纳（空条款已删、缺陷位置写明 graph 三处、三工具统一）④ AC-2/AC-8 判据已分开写死 ⑤ AC-2.4 保留 URL 回填要求与静默失效说明 ⑥ AC-4.6 逐字段表已确定。
  2. **三处被推翻判断，我逐条确认接受**：C-3「ai UPDATE 占位行」——占位行是 xiaobao 产品硬约束，ai 从数据库语义推不出来，`ON CONFLICT DO UPDATE` 写法我逐条核过无坑；C-4 退避根因（我现象推演对、根因归错）；**Q-4「rss 无原文链接」是我的错且错法值得记**——我依据对方 R-5 字段表得出否定结论并已写成"已知限制"结案，而该表只覆盖 `content` jsonb、未覆盖一级列。**教训认领：对"对方确实没有某物"的否定结论，不能靠对方交付物的沉默证实，须回问一次。**
  3. **高①HTTP 模式并发退化无验收覆盖**：PRD 在 US-8 背景里点出"同步端点靠线程池兜底"，但推论只写了一半——端点由 `def` 改 `async def` 后 FastAPI **不再派发线程池**，改造若有任一遗漏，HTTP 模式会从"线程池并发"退化为"event loop 串行"，**比 v0.1 更糟**；AC-1 说"与 v0.1 等价"却未界定等价维度，AC-9.3 只覆盖 DB 模式。需补对称的并发验收（N≥3 并发，总耗时 < 1.5×单条）。
  4. **高②AC-9.4「行为不变」是循环论证**：实查 `test_news_l1.py:44` `FakeClient`、`:64-73` `NullTools`、`test_news_l1_tools.py:16` `FakeTools` 全为同步签名，协议改 async 后必须一并改写（约 21/36 例受影响，`TestClient`→`ASGITransport`），"用改写后的测试证明改写后代码行为不变"验不住，"断言语义不得放宽"不是可执行判据。需把 O-8 的"黄金样本快照"**提升进 AC-9.4** 作为验证方式写死（验收标准不能依赖尚未决定的方法）。
  5. **高③AC-3.6 与 §5 时序冲突**：C-6 行锁实证要求"实现前"完成，口令注入却归部署阶段。xiaobao 已预判列级授权很可能不满足 `FOR UPDATE`，若推迟到部署阶段才失败，claim / 事务边界 / 并发测试全部返工（claim 是 worker 循环地基）。建议口令注入**前移为实现阶段开工前置**（§5 已简化为同机直读，成本极低）。
  6. **中④§8 成本表未按 async 重估**：它沿用了我 R1 在**线程方案前提**下的"处理核心零改动"结论，async 下只对一半——解耦*方向*仍是红利（协议切点不挪），但*代码*要碰 4 个出网点 + `AIClient`/`NewsTools` 两协议 + `DefaultNewsTools` + 4 个 IO 节点 + `tasks.py:64` `invoke→ainvoke` + `run_task` + `main.py` 端点 + 过半单测，是全仓 IO 代码一次性翻新。会让 Architect 切分与 PM 排期低估。
  7. **中⑤`l0_label` 空值兜底未写**：NULL/空串若直接包成 `[l0_label]` → `['']` 是**真值**，会穿过 `news_l1.py:206` 的 `or None` 把空标签传给 xiaobao KB 检索。需明确映射为 `[]`。
  8. **低⑥⑦**：O-9 驱动选型建议 **psycopg3(async)** 而非 asyncpg（占位符 `%s` 便于 C-6 失败后改写 SQL、同步/async API 同构、对 v0.3 RunRecord 友好；asyncpg 性能优势在 74~79s LLM 瓶颈下无意义）；async 划线按"**有 IO 才 async**"（`ingest_context`/`normalize_output` 纯计算节点改 async 无收益，非图便捷）。
  9. **工程成本重估（本轮指派任务）**：async 地基为**新增最大块**，其余四块持平或略增。**风险重心已从"契约缺项"转移到"async 回归"**——R1 时阻塞全是外部契约缺项（现闭合 9/10），R3 后 ai 侧最大不确定性是 async 回归；O-8 自评"风险在回归不在重写"准确，正因如此高②的黄金样本基线是该 P0 风险**唯一的客观兜底**。
  10. **AC-9.1 的 IO 点清单经实查完全准确**：全仓 `httpx` 出网点有且仅有 PRD 所列四处，行号逐一对得上。
  11. **订正（同日追加）**：DevOps 并行复审的问题 1 指出我的问题 3 只说到表层——即便口令到位，C-6 实证仍做不了，因为 **ai 在那台服务器上根本没有运行环境**。其三条实查事实我已独立复现全部成立（`uname -s`=Darwin、`/root` 不存在、本机 `5432`/`8100` 无监听、`scripts/`/`deploy/`/`.env` 均不存在）。**我的建议③作废并入其问题 1**：要前移的是整个服务器部署环境准备，不只是口令注入；否则时序冲突只解一半。仍成立的部分：AC-3.6 与 §5 的冲突本身存在，且 C-6 拖到部署阶段才失败会导致 claim/事务/并发测试返工的后果判断不变。
- 关联迭代：v0.2
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：① C-6 行锁实证若失败需 xiaobao 改授表级 GRANT，结论须回帖 coordination；**且实证前置于服务器部署环境准备（DevOps R3 问题 1）** ② Q-1 `needs_context` 待 xiaobao PM 表态 ③ async 回归是本迭代最大技术风险，回归基线形式（黄金样本）需在 R4 或设计阶段落定 ④ §0 准则下"不图便捷"与"不做无谓改动"的边界需在设计阶段把握（问题 7）
- 下一步入口：Architect / DevOps 完成 R3 复审 → PM 按三方意见改 R4（重点：补 HTTP 并发验收、黄金样本进 AC-9.4、口令注入前移）→ R4 定稿后进设计阶段（O-8 async 切分与回归策略、O-9 驱动选型、O-2 协议边界、O-6 事务边界）
- 收尾状态：已收尾（复审交付完成）

## 2026-07-26 — v0.2 PRD R1 Review

- 本次角色：Developer
- 动作：Review（PRD R1 三方之末，DevOps / Architect 已先交，均未通过）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 Review 记录 + Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（PRD 门禁 + Review 记录）、`docs/progress/INDEX.md`；实读 coordination `contracts/news-l1-db.md` v1.1、`contracts/news-l1.md` v1、`communications/REQ-003-db-boundary-async.md`；核对 `src/agent_hub/{main,tasks,schemas,config}.py`、`graphs/news_l1.py`、`llm/client.py`、`tools/{base,kb}.py`、`tests/`、`requirements.txt`、`.env.example`
- 结论：**PRD R1 Developer Review 未通过**（2 阻塞 3 高 1 中 + 事实层刷新 8 项）。
  1. **阻塞①`tags_v2` 第五类契约冲突**：`news-l1-db` v1.1 要 `sentiment`，`news-l1` HTTP 契约（L133）与 ai `schemas.py:41-46` 均为 `processing`，ai 从不产 `sentiment` → AC-4 写回内容无法确定。且 `processing` 承载 `engine:`/`llm:`/`degraded:` 标识（`news_l1.py:370-372`），是 worker 模式下判断降级的唯一结构化线索，不能丢。与 O-1 同类型的起草笔误，提 C-10 请 xiaobao 订正。
  2. **阻塞②同步基线 + `/health` 探活 + 74~79s 阻塞三者不可同时成立**：实查 `async def|await` **0 命中**，LLM 走同步 `httpx.post`。Architect O-4（DB 模式仍监听 `/health`）+ DevOps 探活要求组合后，若 worker 与 uvicorn 同 event loop，单条处理会整段阻塞 `/health` → 假死误判 → 重启 → 反制造残留 `processing` 锁（比无探活更糟）。建议增补「处理中 ≥60s 时 `/health` 仍须 2s 内返回」AC + §5 写死「本迭代不引入 async 改造」（连带约束驱动选型倾向 psycopg3 同步）。
  3. **高③AC-7 三点**：末句「`processing` 不含 `stub`」已满足（`src/` 0 命中 + `test_news_l1.py:186` 已有断言）属空条款；缺陷实际在 `news_l1.py:213` 而非 `kb.py`（`kb.py:72` 空结果已返回 `ok=True, items=[]`，语义本就正确）；同一 bug 在 `:150`(link)/`:179`(web)/`:213`(kb) 三处同构，只修 KB 会留三工具语义不一致。
  4. **高④AC-2 与 AC-8 判据互斥**：同一次验证会同时判通过与不通过（AC-2 验"跑通"、AC-8 验"等价"，而 DB 模式输入本就不等价）。建议 AC-2 判依赖方向（核心 diff 为空 + 两侧均产合法 `L1Output`）、AC-8 判"输入等价前提下语义一致"并列出已知差异。
  5. **高⑤C-1 应拆分**：对照 R-5 结构说明，`source_item_url` **可撤回**（x_twitter 可由 `tweet_id`+`author_username` 构造，R-5 给了空 username 兜底规则；rss 无链接字段但仅单测覆盖不阻塞），`domain_tags` **仍缺仍需订正**。实现要点：`_extract_url`（`:407`）只认 `raw_content["url"]`/`["canonical_url"]`，x_twitter content 两键皆无 → 适配层必须显式回填，否则 link_read 不报错不降级、静默失效。
  6. **中⑥AC-4 字段来源**：`analysis` 空值规则未定；`context` 因 URL 证据过滤（`:362-367`）在 DB 模式大概率恒空；`needs_context` 在 `processed_news` 无列可写，丢弃需显式决策。
  7. **工程成本判断**：处理核心（`tasks.py`/`graphs/`/`llm/`）**零改动**——`run_task` 签名已与传输层无关，Architect O-2 倾向确认成立且成本近零，是 v0.2 最大复用面。新增量集中在入向映射 / 出向映射+写回事务 / claim+worker 循环+优雅停机 / 结构化 logging 四块；其中 logging 是横切改造（现状零 logging），与 AC-2「核心零改动」存张力，需以注入方式实现。并发 claim 与事务回滚必须对真实 PG 测，会消耗 R-4 预置的 5 条队列。
  8. **契约版本核对（附带产出）**：另两方实读依据标注 v1，契约实为 v1.1。逐条复核 C-1~C-9 对 v1.1 **除 C-1 的 URL 分支外全部仍成立**；O-1/O-5 已闭环。建议后续 Review 标注契约版本号。
- 关联迭代：v0.2
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：① PRD 事实层已被 coordination 07-25~07-26 三帖推翻（O-1 已定案方案 A、契约订正 v1.1、R-1/R-2/R-4/R-5 前置已解除、造数已预置 5 条、系统仅有 x_twitter 真实数据），R2 须先刷新 8 项再改意见，否则定稿带过期前提 ② 新增契约缺项 C-10（`tags_v2`）需 PM 转达 xiaobao ③ ai 侧唯一剩余外部依赖是 `ai_worker` 口令待 Owner 带外交付 ④ 生产库 GRANT 未执行（上生产前置，不进 v0.2 部署就绪检查）
- 下一步入口：PM 按三方意见改 PRD R2（含事实层刷新 + 三类源验收分层进 §3 + C-10 转达 xiaobao）；R2 定稿后进设计阶段（Architect 定适配层分层 O-2 / worker 参数 O-3 / 事务边界 O-6）
- 收尾状态：已收尾（Review 交付完成）

## 2026-07-04 — v0.1 实现 R1 收尾铺写（Developer 侧）
- 本次角色：Developer（收尾铺写，不改代码 —— 实现 R1 已定稿，再改需走 R2）
- 动作：核实联调证据 + 同步元信息 + 登记发布检查项归属 + 铺写迭代关闭归档区
- 涉及文档：`docs/progress/iterations/v0.1-test-report.md`（文档状态 / 结论 / 回归结论 / 缺陷表 D-1 闭环 + D-3 登记）、`docs/progress/iterations/v0.1.md`（概览当前阶段 / 部署就绪检查表 + 发布检查项归属表 / CN-002 执行状态 / 迭代关闭归档区）、`docs/progress/INDEX.md`（当前状态 / 版本列表 / 最近收尾摘要 / 跨任务待办 REQ-001 联调条）、`docs/progress/roles/developer.md`（本条）；核实 coordination `communications/REQ-001-news-l1.md` + `STATUS.md`
- 结论：
  1. **联调证据已齐**：coordination 仓 2026-07-04 记录端到端联调完成，4 条用例通过（公网 `run_7e626cf5f391` / 内网 `run_2a4dbc15f308` / KB 命中 `run_2e0072cba2a3` / KB 空结果），单条耗时 74~79s（较 6 月底 104s 优化约 25-30%），Owner 抽样验收通过；REQ-001 可进入关闭。
  2. **实现 R1 定稿 + 端到端联调通过**：Architect + DevOps 两方 Review 均通过（2026-07-04），pytest 40 passed，D-1 真实连通性已闭环；D-2（上下文充分性阈值）/ D-3（KB 空结果语义）为非阻塞遗留。
  3. **发布检查项归属区分**（DevOps Review 提出 4 条）：① 服务托管化 → DevOps 运维侧；② 结构化 logging → Developer 代码侧；③ 生产 ≥2 provider → DevOps 运维侧；④ 单条耗时 → Developer 代码侧（需 Architect 评估模型选型）。
  4. **迭代关闭判断**：Developer 侧证据齐备，不阻塞关闭；但 Owner 验收状态本仓 INDEX 旧记「未验收」与 coordination 2026-07-04「抽样验收通过」不一致，需 Owner 同步；迭代关闭检查机制由 Owner 触发，Developer 不代写关闭结论。
  5. **联调文档完整**：coordination `communications/REQ-001-news-l1.md` 头部字段齐全，2026-07-04 联调完成条含双方角色 / 范围 / xiaobao 侧补充数据 / 配置确认 / 当前结论，无需补。
- 关联迭代：v0.1
- 关联非迭代工作：无
- 关联 Change Note：CN-002（端到端联调通过，D-3 待优化）
- 遗留问题/风险：① Owner 验收状态需 Owner 同步；② 4 条发布检查项跟踪到部署阶段（不阻塞关闭）；③ Architect 5 条非阻塞观察项 + D-2/D-3 入 R2 或下一迭代；④ Architect 需同步 `v0.1-test-report.md` Review 状态表 Architect 行（仍标「待Review」）
- 下一步入口：Owner 同步验收状态并触发迭代关闭检查机制；R2 或下一迭代处理发布检查项 + Architect 观察项 + D-2/D-3
- 收尾状态：已收尾（Developer 侧铺写完成，迭代关闭待 Owner）

## 2026-07-01 — v0.1 实现 R1（S1~S5）+ ai 测试环境部署 + news-l1 联调回填
- 本次角色：Developer（实现）+ DevOps（部署，另见 devops 日志）
- 动作：产出（实现 S1~S5）+ 部署（测试环境）+ 跨项目协作（提报 + 回填）
- 涉及文档：ai `src/agent_hub/{tasks,main,config}.py`、`graphs/news_l1.py`、`llm/{client,json,prompts}.py`、`tools/{base,link_reader,web_search,kb}.py`、`tests/*`、`docs/progress/iterations/v0.1.md`、`v0.1-test-report.md`、`INDEX.md`；coordination `communications/REQ-001-news-l1.md`、`STATUS.md`
- 结论：
  1. v0.1 实现阶段 R1 四片完成（S1 骨架真实化 / S2 LLM client fallback / S3 工具真实化 / S4 收尾），pytest 36 passed，自测报告 `v0.1-test-report.md`；实现阶段 R1 置「Review中」待 Architect/DevOps 复核。base `2605c07` → head `0863c6a`。
  2. 跨项目：ai `/v1/runs/news-l1` 就绪后向 xiaobao 提 news-l1 **联调触发入口**诉求（coordination commit `8eecdde` 已 push；两入口只差新闻来源、不改 v1 契约）。
  3. xiaobao 已响应（见 communications/REQ-001 2026-07-01 条）：实现前端 `/debug/ai` 联调验收页 + 后端 `POST /v1/ai-debug/news-l1-runs`、`GET /v1/ai-debug/candidates`、`POST /v1/kb-search`（KB search v1，新增 `contracts/kb-search.md`），补齐 `contracts/news-l1.md` 字段语义；向 ai 提 5 点对接需求。
  4. **S5（CN-002，Owner 2026-07-01 批准）KB 主动检索纳入 v0.1**：`tools/kb.py` 真实调 xiaobao `/v1/kb-search` + graph 主动 KB 路由（优先级 kb>link>web），pytest **40 passed**；实现 R1 head→`344ad49`（已 push）。
  5. **部署（DevOps 职责）**：ai 服务起测试环境 `127.0.0.1:8100` 常驻（uvicorn，LLM=openclaw 火山 `doubao-seed-2.0-pro`），`/health` 200，真实 news-l1 `succeeded`（run `run_bcf24393b947`，四维评分/标签/摘要真实产出，Tavily 通、KB 降级）；回填 coordination（ai 就绪 + 回应 xiaobao 5 点，`97ae5e0`），ai 仓已 push（`123ad4e`）。
- 关联迭代：v0.1
- 关联非迭代工作：news-l1 跨项目联调（REQ-001）
- 关联 Change Note：CN-001、CN-002（KB 纳入 v0.1）
- 遗留问题/风险：① KB 端到端待 xiaobao 起 `8001` + 确认是否需 `x-admin-token`（ai 侧 `KB_ADMIN_TOKEN` 留空）② 服务为 `nohup` 后台起，会话/机器重启不自动拉起，长期常驻需 systemd/supervisor ③ 实现阶段 R1（含 S5）仍待 Architect/DevOps 复核 ④ 单条约 104s 偏长（reasoning 模型+工具串行）待观察/调模型 ⑤ 鉴权测试环境不启用（Owner 定），上线前再加。
- 下一步入口：xiaobao 配 `AI_HUB_BASE_URL=http://127.0.0.1:8100` + 起 `8001` → `/debug/ai` 端到端验收；Architect/DevOps 复核实现 R1。
- 收尾状态：已收尾

## 2026-07-01 — v0.1 设计 R1 Review
- 本次角色：Developer
- 动作：Review
- 涉及文档：`docs/progress/iterations/v0.1-design.md`、`docs/progress/iterations/v0.1-prd.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`、`docs/knowledge/decisions/0001-news-l1-deterministic-conditional-graph.md`、`docs/knowledge/decisions/0002-openai-compatible-chained-llm-client.md`
- 结论：设计 R1 Developer Review 通过。模块划分、内部接口、数据流、fallback 矩阵、工具统计口径和测试清单均可落地。
- 关联迭代：v0.1
- 关联非迭代工作：无
- 关联 Change Note：CN-001（工具后端分工细化）
- 遗留问题/风险：实现阶段需补清 `LLMResult` 最小字段、显式维护总 timeout budget，并先修正 `tests/test_health.py` 中预取上下文计入 `tool_summary` 的旧断言；DevOps R1 仍待 Review。
- 下一步入口：DevOps Review `v0.1-design.md`；三方通过后设计可定稿并进入实现阶段。
- 收尾状态：已收尾

## 2026-06-30 — v0.1 PRD R2 复审
- 本次角色：Developer
- 动作：Review
- 涉及文档：`docs/progress/iterations/v0.1-prd.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`；核对 `src/agent_hub/{main.py,schemas.py,graphs/news_l1.py,config.py}` 与 `tests/test_health.py`
- 结论：PRD R2 Developer 复审通过。R1 的实现阻塞点已处理：AC-9 收敛为内部 registry 且不改对外契约；AC-6 降级状态语义可测试；AC-5 URL 来源和 `tool_summary` 口径明确；AC-7 provider 配置细节留设计阶段落定。
- 关联迭代：v0.1
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：实现阶段需调整现有骨架测试中预取 `kb_results` 计入 `tool_summary.kb_search` 的旧口径；Architect R2 仍待复审。
- 下一步入口：Architect R2 复审 `v0.1-prd.md`；若通过则 PRD 可定稿并进入设计阶段。
- 收尾状态：已收尾

## 2026-06-30 — v0.1 PRD R1 Review
- 本次角色：Developer
- 动作：Review
- 涉及文档：`docs/progress/iterations/v0.1-prd.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`；核对 `src/agent_hub/{main.py,schemas.py,graphs/news_l1.py,config.py}`
- 结论：PRD R1 未通过。主要问题：AC-9 对外入口/契约边界不清；AC-6 部分可用结果的状态语义不可测试；AC-5 URL 来源与工具统计口径不清；AC-7 多 provider fallback 缺少最小配置形状和失败判定矩阵。
- 关联迭代：v0.1
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：需 PM 修改 PRD 后重新 Review；实现阶段不得在这些语义未定时自行改契约。
- 下一步入口：PM 修改 `v0.1-prd.md`，处理 Architect / Developer R1 反馈。
- 收尾状态：已收尾

