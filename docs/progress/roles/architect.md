# Architect 角色日志

## 2026-07-25 — v0.2 PRD R1 Review（Architect）
- 本次角色：Architect（架构师）
- 动作：标准迭代 PRD 阶段 R1 Review（v0.2 范围重排后的重写版，主线 REQ-003）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 §Review 记录 · R1 — Architect Review + 订正 Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（PRD 阶段 R1 行 + Review 记录表）、`docs/progress/INDEX.md`（当前阶段 / 阻塞项 ④ / 下一步入口）；核对 coordination `contracts/news-l1-db.md` v1、`contracts/news-l1.md` v1、`communications/REQ-003-db-boundary-async.md`、`decisions/0002`，本项目 `src/agent_hub/{main,tasks,schemas}.py`、`graphs/news_l1.py`、`docs/baseline/project-context.md`
- 结论：**未通过**（3 阻塞 3 高 3 中 1 低，需 PM 修改后进 R2）
- 核心判断：worker 闭环的**输出侧**（写回 + 状态推进）契约描述较完整，**输入侧**（从 `raw_items` 构造等价处理输入）几乎无真源支撑；AC-8「两模式业务字段等价」按现有可读列授权**不可达**——`domain_tags`（L0 分类结果）与原文 URL（`source_item_url`，HTTP 契约靠调用方补进 `raw_content`）均不在 ai_worker 可读列，`link_read` 路径在 DB 模式整条失效；预取上下文无提供方 → KB 只能由 ai 主动回调 xiaobao `POST /v1/kb-search`，即 **DB 模式并未消除 ai↔xiaobao 的 HTTP 依赖，只是反转了方向**
- 三条阻塞：① DB 模式输入构造缺口（上条）② `tasks.status` 取值枚举与转移全缺（契约只给了 `l1_status` 枚举）→ AC-4/AC-5「同步更新 tasks 状态」不可实现且不可验证，ai 不得自行猜枚举污染 xiaobao 业务真源 ③ `processed_news` 由谁 INSERT 未定（职责表写 xiaobao「占位创建」但权限矩阵给 ai INSERT+UPDATE）+ `news_positions` 触发器是 INSERT 后触发 → 占位语义下触发器在结果为空时就跑，排序位如何更新无说明；架构倾向 ai INSERT + `raw_item_id` 幂等键 upsert
- 三条高：④ 契约 §task type 的退避 `[60s,300s,900s]` 未进 claim 规则 SQL（SQL 无任何时间条件）→ 失败条目按轮询节奏被立即重领，几十秒耗尽 3 次重试预算，退避形同虚设 ⑤ 确认 DevOps 的 `N × 79s < 1800s → N ≤ 22`、建议 N ≤ 8 推导成立，并判定该不变式是**正确性约束**（违反会产生 xiaobao 误回收 + ai 仍在处理的双写竞态），应写进 AC-3 而非只留在 O-3 ⑥ claim 原子性可实现性未验证：`tasks` 无 INSERT 权限（依赖 xiaobao 必建 task，契约未承诺）+ PG 的 `SELECT FOR UPDATE` 按表级 UPDATE 判权而契约只给列级，须在实库验证
- 开放问题结论：**O-1 支持方案 A**（`score_total` 归 xiaobao）——加权是消费侧策略而非处理侧事实、与 `decisions/0002` 多调用方定位冲突、会形成权重真源跨仓双向耦合；补充方案 A 必须同时定 xiaobao 补算时机（否则冲突从「谁算」推迟成「什么时候算」）。**O-4 定为进程级 + DB 模式仍监听 `/health`**（取 DevOps 问题 1 的方案①，两者不矛盾，复用成本近零，建议 `/health` 附 `mode` + `last_poll_at`）。**O-2 倾向切在 `tasks.run_task` 之上**（v0.1 入口已解耦，`main.py:32` 之下无传输层概念，适配层收敛为两个映射器 + worker 循环）。**O-6 倾向三表同事务，但 LLM 调用必须在事务外**（claim 短事务 / 处理无事务 / 写回短事务三段，避免 idle-in-transaction）
- 新增契约缺项 C-1~C-9（P0×3 / P1×2 / P2×4）已列表写入 PRD Review 记录，需 PM 转达 coordination `REQ-003` 待跟进表
- 与并行会话的关系：DevOps 会话同日已完成 R1 Review（未通过，4 高 2 中 1 低），其改动在工作区未提交；本次只追加自己的 Review 章节，未改动其产出（守 [P0] 不覆盖未归属修改 / Review 方不改正文）
- 遗留问题/风险：本会话**未写 coordination 仓** —— 协调仓工作区存在他人未提交改动（`REQUESTS.md` 为 M 状态），按 [P0] 跨仓写入需先确认 git 同步状态与改动范围，故 C-1~C-9 的跨仓落地留给 PM（PRD 产出方）并需 Owner 确认；另 O-1 仍待 xiaobao 回应，PRD 不得定稿
- 下一步入口：Developer 补做 PRD R1 Review；PM 按 DevOps + Architect 意见改 PRD 进 R2 并转达 C-1~C-9；三方通过 + O-1 有结论后 Architect 创建 `v0.2-design.md`（落 O-2 / O-6，适配层与 worker 分层 ADR）

## 2026-07-04 — v0.1 实现 R1 Review（Architect）
- 本次角色：Architect（架构师）
- 动作：标准迭代实现阶段 R1 Review
- 涉及文档：`docs/progress/iterations/v0.1-test-report.md`（追加 Review 记录）、`docs/progress/iterations/v0.1.md`（更新实现阶段 R1 Review 结果与阶段状态）、`docs/progress/INDEX.md`（更新当前阶段与下一步入口）；核对 `v0.1-design.md`、`v0.1-prd.md`、ADR-0001/0002、`src/agent_hub/{schemas,main,tasks,config,graphs/news_l1,llm/client,llm/prompts,llm/json,tools/kb,tools/base,tools/link_reader,tools/web_search}.py`、`tests/`、`.env.example`
- 结论：**通过**（实现忠实设计 ADR-0001/0002 与 PRD AC-1~9，对外契约不变；附 5 条非阻塞观察项）
- 核对要点：对外契约不变（`schemas`/`main` 仅 `/health` + `POST /v1/runs/news-l1`，failed+output=null 对齐 v1）；内部 registry（AC-9）落地且不暴露通用路由；条件图编排 kb>link>web 优先级忠实 ADR-0001；`ChainedAIClient` fallback 矩阵完整 + 显式总 timeout budget；降级语义对齐 AC-6；输出清洗 score clamp / context URL 过滤 / `processing` 标签到位；prompt 五类标签 + 中文摘要 + `translation.zh`；测试 40 passed 覆盖设计 §8 全 10 项；`.env.example` 补全
- 非阻塞观察项：① 设计文档未同步 CN-002 KB 主动路由（§4.3/§4.6/风险表仍写占位禁用）② `normalize_output` 兜底未完全实现 §4.7（缺失 reason / 空 summary 填空字符串而非降级说明）③ `kb_search_node` 未传 `exclude_raw_item_id`（可能自检索，需确认 kb-search v1 契约）④ `config.py` 的 `Config` 类与 `config` 实例为死代码 ⑤ `_http_call_provider` 400 非 quirk 错误 kind 标记为 `server_error`/`provider_5xx` 语义不准
- 遗留问题/风险：D-1 真实外部连通性（LLM/link/Tavily/KB）未在单测覆盖，待 DevOps 部署冒烟验证；单条约 104s 偏长待观察
- 下一步入口：DevOps Review 实现 R1（provider/Tavily/KB 配置 + 部署冒烟检查项 + D-1 真实连通性）；两方通过后实现 R1 定稿进 Owner 验收；非阻塞观察项 1/2 建议实现 R2 或下一迭代处理，3/4/5 视优先级安排

## 2026-07-01 — v0.1 设计 R1 Review 收口
- 本次角色：Architect（架构师）
- 动作：设计阶段 Review 收口
- 涉及文档：`docs/progress/iterations/v0.1-design.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`
- 结论：PM、Developer、DevOps 三方均通过，设计 R1 定稿；项目进入实现阶段，等待 Developer 启动。
- 遗留问题/风险：PM 的五类标签 / 中文摘要和翻译目标语言建议、Developer 的 `LLMResult` / 总 timeout budget / 测试口径提示、DevOps 的 `.env.example` / provider / Tavily / 日志脱敏检查项均为实现或部署阶段跟踪项，不阻塞设计定稿。
- 下一步入口：Developer 根据 `v0.1-prd.md`、`v0.1-design.md`、ADR-0001、ADR-0002 启动实现。

## 2026-06-30 — v0.1 详细设计 R1（Architect）
- 本次角色：Architect（架构师）
- 动作：标准迭代设计阶段 R1 初版
- 涉及文档：`docs/progress/iterations/v0.1-design.md`；ADR `docs/knowledge/decisions/0001-news-l1-deterministic-conditional-graph.md`、`docs/knowledge/decisions/0002-openai-compatible-chained-llm-client.md`；同步 `docs/knowledge/INDEX.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`
- 结论：设计 R1 已提交 Review；指定 PM、Developer、DevOps 作为 Review 方。
- 设计要点：对外契约不变；内部 task registry；确定性条件图；OpenAI 兼容链式 LLM client；Tavily adapter；预取上下文不计 `tool_summary`；部分可用结果按 `succeeded` 降级语义返回。
- 下一步入口：PM、Developer、DevOps Review `v0.1-design.md`；通过后设计定稿并进入实现阶段。

## 2026-06-30 — v0.1 PRD R2 复审（Architect）
- 本次角色：Architect（架构师）
- 动作：标准迭代 PRD R2 复审
- 涉及文档：`docs/progress/iterations/v0.1-prd.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`；复核 coordination `contracts/news-l1.md`
- 结论：通过；PRD 阶段已定稿，可进入设计阶段。
- 确认：AC-9 已收敛为内部 registry / dispatch，不改对外契约；AC-6 已对齐 `RunResponse` v1；AC-5 已明确 URL 来源与 `tool_summary` 主动调用统计口径；AC-7 配置细节留设计阶段落定。
- 下一步入口：Architect 创建设计文档，并落条件图编排与 LLM client 移植 ADR。

## 2026-06-30 — v0.1 PRD R1 Review（Architect）
- 本次角色：Architect（架构师）
- 动作：标准迭代 PRD R1 Review
- 涉及文档：`docs/progress/iterations/v0.1-prd.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/INDEX.md`；核对 coordination `contracts/news-l1.md` 与本项目 `src/agent_hub/{schemas.py,main.py,graphs/news_l1.py,config.py}`
- 结论：未通过；需 PM 修改后进入下一轮 Review。
- 主要问题：AC-9 / 范围边界与「本迭代不改契约」冲突；AC-6 失败时部分 output 与 `RunResponse` v1 语义冲突；AC-5 链接自抓 URL 来源和 `tool_summary.kb_search` 统计口径不清。
- 下一步入口：PM 修改 `v0.1-prd.md`；Developer 仍需完成 R1 Review；PRD 定稿后 Architect 进入设计阶段并落条件图编排、LLM client 移植 ADR。

## 2026-06-29 — REQ-002 数据架构调研（Tech Spike）
- 本次角色：Architect（架构师，ck）
- 动作：技术预研（承接 REQ-002）
- 涉及文档：`docs/progress/ad-hoc/2026-06-29-spike-req002-data-architecture.md`（产出）；调研 `/root/Horizon`、`/root/ai-news-aggregator`、本项目 `src/agent_hub/*` 与 `contracts/news-l1.md`
- 结论：4 个架构岔路口已逐一回答——
  1. L1 用**确定性 staged 编排**（保留 LangGraph 条件边，不引入自主 ReAct）；
  2. L0 用**规则预过滤 + LLM 兜底**（架构建议，归属仍在 xiaobao）；
  3. LLM 客户端**移植 Horizon `client.py` 内核**（链式 fallback + provider quirk），裁剪到 OpenAI 兼容，建议立 ADR；
  4. **不做强可重入**，run 仍是单条同步证据，落可选带 TTL 的轻量 RunRecord，不与 `tasks` 合流。
  另叠加「生态通用骨架」薄接缝（task registry / `{task_type}` 路由 / caller 标识 / RunRecord），原则做接缝不提前实现。
- 关联迭代：v0.1（待启动，建议据本结论立项）
- 关联非迭代工作：REQ-002 架构调研
- 关联 Change Note：无
- 遗留问题/风险：v0.1 决策项——条件图具体边、L0 归属/规则对齐（需 xiaobao）、client 移植依赖裁剪清单、RunRecord 存储后端选型
- 下一步入口：回 PM 创建 `v0.1-prd.md`；设计阶段把岔路口①③各落一份 ADR
- 收尾状态：已收尾（2026-06-29）
