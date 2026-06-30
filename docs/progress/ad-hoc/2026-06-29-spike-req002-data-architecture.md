# 临时工作记录

## 基本信息
- 日期：2026-06-29
- 模式：Tech Spike（架构调研 / 预研，承接 REQ-002）
- 执行角色：Architect（架构师，ck）
- 是否进入迭代：否（为 v0.1 标准迭代提供架构输入；REQ-002 是 REQ-001「L1 真实化」的前置）
- 关联迭代：v0.1（待启动）
- 当前状态：已完成（4 岔路口已逐一回答，待 Owner / PM Review 后转 v0.1 设计）

## 背景

REQ-002（coordination `REQUESTS.md` §REQ-002）由 xiaobao·Architect 提报、Owner 指派给 ai，2026-06-29 ai PM 正式承接，架构方案实质产出归 Architect。要求：

1. 调研两个本地参考项目：`Horizon`（`/root/Horizon`，Python+asyncio，重度 LLM，与 Agent Hub 几乎同构）、`ai-news-aggregator`（`/root/ai-news-aggregator`，TS/Node，零 LLM 反向参照）；
2. 回答 4 个架构岔路口；
3. 形成 ai 自己的架构方案，并叠加定位升级（Owner 2026-06-29 拍板 ai = **生态内部通用 AI 处理中枢**，coordination `decisions/0002` supersede D5）带来的「生态通用骨架」维度。

边界：本调研为**预研性质，非契约变更**；`news-l1` 契约真源仍以 coordination `contracts/news-l1.md` 为准，结论若要改契约须另走契约流程。L0 归属仍在 xiaobao，本文对 L0 的结论是**架构建议**，不改归属。

## 操作/产出

### 调研覆盖文件（已通读）

| 项目 | 文件 | 提炼到的证据 |
|------|------|------|
| Horizon | `src/ai/analyzer.py` | 便宜模型批量打分（0–10）、`asyncio.Semaphore` 限并发、`tenacity` 重试、失败降级 score=0 |
| Horizon | `src/ai/enricher.py` | **写死三步「伪 Agent」**：概念抽取→Web 搜索→grounding 合成；失败降级到「仅翻译」；**引用校验**只留搜索结果里真实出现的 URL |
| Horizon | `src/ai/client.py` | `AIClient` ABC + 多 provider 实现 + **`ChainedAIClient` 链式 fallback**；大量 provider quirk（temperature learn-on-400、`max_completion_tokens` 回退、`response_format` 例外、ollama URL 规整、usage 记账） |
| Horizon | `src/ai/prompts.py` / `docs/scoring.md` | 评分 system prompt + JSON 协议；**阈值闸门**（`ai_score_threshold` 默认 7.0）后才进 enrich |
| Horizon | `src/mcp/run_store.py` / `mcp/README.md` | `RunStore` 分阶段产物落盘（raw/scored/filtered/enriched/summary）+ `has_stage()` **可重入**；设计原则「MCP 不重实现业务，分阶段 tool + 中间产物可重入」 |
| Horizon | `docs/horizon-hub-design.md` | Hub 作为 ecosystem **Control Plane** 聚合多个独立 Agent 判断（相关性低，仅取「中枢聚合多调用方」的类比） |
| aggregator | `src/filters/ai-related.ts` / `config.ts:141` | **AI 相关性 = 纯关键词正则**，零 LLM |
| aggregator | `src/filters/dedupe.ts` | 标题+URL 归一化的**确定性去重**，零 LLM |
| aggregator | `TECH_SPEC.md` / `translate/google.ts` | 连「翻译」都用 **Google Translate API（非 LLM）** + 增量（每轮≤80）+ 缓存复用 |
| ai（本项目） | `src/agent_hub/{main,schemas,graphs/news_l1}.py`、`contracts/news-l1.md` | 现有骨架：固定线性流水线 `kb_search→link_read→web_search→llm_process`，`llm_process` 为 stub；单条同步 HTTP，`run` 仅处理证据，`tasks` 真源在 xiaobao |

---

## 结论：4 个架构岔路口的回答

### 岔路口① L1 第一版：确定性 staged 编排 vs 真 agent 自主工具调用？

**结论：确定性 staged 编排（保留 LangGraph 的条件边 + checkpoint 能力，但不引入自主 ReAct 循环）。**

依据：
- **Horizon 已证明**：`enricher` 的「按需工具调用」是写死三步（LLM 列概念 → 代码/Web 搜索 → 喂回 grounding），**无 ReAct 自主循环**，在生产中质量足够。L1 任务是**有界的**（评分+标签+摘要+翻译+可选 grounding），不存在需要自主多轮规划的开放式推理。
- **契约要求确定性**：`RunOptions` 带 `max_tool_calls=4` + `timeout_ms=180000`，调用方按同步 HTTP 等结果。确定性编排才能保证**成本有界、延迟有界、可测试、可复现**；自主 agent 循环成本/延迟不可控，单测困难，对这个有界任务边际收益极低。
- **对 LangGraph 选型的修正**：LangGraph 在这里的正当性**不是「agent 框架」而是「带条件边 + 可选 checkpoint 的图编排」**。现有骨架是纯线性图（每个节点必跑），其实没用上 LangGraph 的价值。建议改为**条件图**：
  - `kb_search`/`link_read`/`web_search` 由 `needs_context` 与输入是否已预取来**条件触发**（借鉴点 2 + 5：Horizon 概念抽取为空就跳过搜索）；
  - 工具调用计数受 `max_tool_calls` 闸门约束。
- 这样既保留「未来要加自主性时图结构不用推倒重来」的演进空间，又不在 v1 承担自主 agent 的不确定性。

落到代码（建议签名，v0.1 设计阶段细化）：
```python
# 条件边：按需触发工具节点，不再每节点必跑
def route_after_kb(state) -> Literal["link_read", "web_search", "llm_process"]: ...
# llm_process 内部仍是「确定性多步 prompt」而非自主循环
```

### 岔路口② L0：用 LLM vs 规则预过滤 + LLM 兜底？

**结论：规则预过滤 + LLM 兜底（确定性预过滤放在 LLM 之前）。** 注：L0 归属在 xiaobao，本结论是架构建议；若未来 L0 作为一种 task type 进中枢，按此设计。

依据：
- **aggregator 是最强反向参照**：它的 AI 相关性判定是**纯关键词正则**（`config.ts:141` 一条正则覆盖 ai/llm/gpt/agent…），去重是**确定性**的标题+URL 归一化，**连翻译都不用 LLM**（Google Translate + 缓存）。证明 L0 级别的「相关性过滤 + 去重」**大头不需要 LLM**。
- **Horizon 同构印证**：便宜模型批量打分 + `ai_score_threshold` **阈值闸门**，过阈值才进昂贵 enrich——**省钱靠闸门不靠模型选型**（借鉴点 1+7）。
- 因此 L0 推荐分层：① 确定性预过滤（关键词相关性 + 确定性去重）免费筛掉明显噪声/重复；② 仅对**规则判不准的残差**用 LLM 兜底。成本最优，且预过滤结果可解释、可测试。
- **风险/边界**：纯规则会漏判「语义相关但无关键词」的条目，故保留 LLM 兜底层而非纯规则；阈值与关键词表需可配置、可迭代。

### 岔路口③ LLM 客户端：移植 Horizon `client.py` vs 自研？

**结论：移植「抽象 + 链式 fallback + provider quirk 处理」内核，裁剪到 ai 当前只需的 OpenAI 兼容 + 解耦 Horizon 内部模型。建议立 ADR。**

依据：
- `client.py`（653 行）里最值钱的不是结构，是**踩过坑的 provider quirk 知识**：temperature 不支持时 learn-on-400 自动停发、`max_completion_tokens` vs `max_tokens` 回退、`response_format` 例外集合、temperature clamp、ollama URL 规整、usage 记账。这类知识**不该靠生产事故重新发现**，是整仓最值得移植的文件（借鉴点 3）。
- **`ChainedAIClient` 直接服务可靠性**：可重试错误（429/401/403/quota/502/503/空响应）自动降级到链上下一个 provider，client 懒加载（下游缺 key 不阻塞启动）。这正对应中枢作为服务方的**多 provider 容错**需求。
- **裁剪原则**（避免过度移植，对齐项目 `config.py` 只配 `OPENAI_BASE_URL/KEY/MODEL`）：
  - 保留：`AIClient` ABC + `OpenAIClient`（含 quirk 处理）+ `ChainedAIClient` 链式 fallback + JSON 解析鲁棒性（`utils.parse_json_response`，借鉴点对应 enrich 的多策略解析）。
  - v1 暂不移植：Anthropic / Gemini / Azure 原生 client（按需再加，OpenAI 兼容已覆盖大多数）。
  - 必须解耦：Horizon 的 `AIConfig` / `record_usage` / `models.py` 依赖，适配到 ai 的 `config.py`；不照搬 `rich`/`tenacity` 之外的内部依赖。
- 这是一个有明确取舍的决策 → v0.1 设计阶段落 **ADR**（移植范围、解耦边界、不引入哪些 provider 的理由）。

### 岔路口④ L1 子阶段产物落盘可重入 + 与 `tasks` 表如何合流？

**结论：不做强可重入；run 仍是单条同步处理证据。落「可选、带 TTL 的轻量 run 记录」用于审计/调试/复现，不与 `tasks` 合流。**

依据与边界：
- **Horizon 的 `RunStore` 是为批量管线设计的**：raw→scored→filtered→enriched 跨大量条目，中间落盘可重入能省昂贵重算。ai 的 `news-l1` 是**单条、同步、受 `timeout_ms` 约束**的 run——单条短 run 内做断点重入边际价值很低（整条重试更简单）。
- **契约红线**：`contracts/news-l1.md` 明确「`tasks` 为业务真源、`run` 仅处理证据」「一次 run 仅处理单条证据，不持有任务状态」。ai **绝不能变成有状态的任务存储**，否则越界吃掉 xiaobao 的调度真源。
- **合流方式**：**不合流**。xiaobao 的 `tasks` 仍是调度真源；ai 生成 `run_id` 回传（`RunResponse.run_id` 已有），xiaobao 在自己的 task 上记录 `run_id` 做关联即可。
- **采纳的部分**：借 `RunStore` 的「分阶段产物」思想做**可选 run 记录**（非重入 checkpoint）：
  ```text
  RunRecord(run_id, task_type, caller, status, elapsed_ms,
            input_snapshot, node_outputs[], tool_summary, error, created_at)
  存储：可选后端（先文件/后 PG），带 TTL，仅用于审计/调试/复现，默认关。
  ```
- **演进扩展点**：若未来出现多调用方大批量 / 异步处理需求，再引入 `RunStore` 式分阶段落盘 + LangGraph checkpointer。本期**标记为扩展点，不提前实现**（对齐简单优先）。

---

## 生态通用骨架维度（定位升级 `decisions/0002` 带来）

定位升级为「生态内部通用 AI 处理中枢」后，需**预留**多调用方 / 多任务类型扩展点。原则：**做薄接缝，不提前实现**——v0.1 仍只交付 `news-l1` 真实化，但代码结构让下列扩展是「注册一个图」而非「改框架」。

| 扩展点 | 现状 | 建议（薄接缝） |
|--------|------|----------------|
| 接口分发 | `POST /v1/runs/news-l1` 单一路由 | 泛化为 `POST /v1/runs/{task_type}`，`task_type` 路由到对应图；`news-l1` 是首个注册项 |
| 任务注册 | 硬编码 `news_l1_graph` | `task registry`: `task_type → (InputSchema, graph_builder, OutputSchema)`；新任务=注册一项 |
| 调用方标识 | 仅 `L1Input.source_identity`（业务域，非调用方） | 传输层加 `caller`/`client_id`（建议 header，与业务 payload 分离），用于归因 / 配额 / 观测 |
| 运行记录模型 | `RunResponse` 即走即弃 | 统一 `RunRecord`（见④），跨 task_type 复用 |
| 共享基建 | 散落 | LLM client（③）、JSON 解析、工具层（kb/link/web）、优雅降级、引用校验跨 task_type 复用 |

> 注意不过度设计：以上仅在 v0.1 设计阶段定义**接口形状**（薄抽象），具体多任务实现等真有第二个调用方/任务时再做。

## 跨切面采纳（7 借鉴点落点汇总）

| 借鉴点 | 落点 |
|--------|------|
| 1 两段式 pipeline（便宜打分→过阈值才贵处理） | 岔路口① 条件 enrich 闸门 + ② L0 阈值 |
| 2 伪 Agent 确定性编排 | 岔路口①（核心结论） |
| 3 多 provider + 链式 fallback | 岔路口③（移植 `client.py` 内核） |
| 4 分阶段产物落盘可重入 | 岔路口④（裁剪为可选 run 记录，不做强重入） |
| 5 优雅降级链（enrich 失败→翻译兜底→不丢条目） | **新增架构原则**：LLM 失败时尽量返回部分 `L1Output`（如仅翻译/score 默认），`RunResponse.status=failed` 时也带可用部分；不轻易给调用方抛 5xx |
| 6 引用校验防幻觉 | `web_search` grounding 仅保留搜索结果里真实出现的 URL，写入 `L1Output.context`；过滤 LLM 编造链接 |
| 7 确定性预过滤放 LLM 之前 | 岔路口②（核心结论） |

## 验证证据
- 已验证：以上结论均有参考项目源码逐处对应（见「调研覆盖文件」表，行级证据：`config.ts:141` 关键词正则、`enricher.py:158-199` 三步伪 Agent + 降级、`client.py:538-606` ChainedAIClient、`run_store.py:50-57` `has_stage` 重入、`scoring.md:42` 阈值闸门）。
- 未验证原因：本期为**纸面架构调研**，未写代码、未实测 LLM 调用与延迟/成本；移植 `client.py` 的实际适配成本、条件图的 LangGraph 实现细节待 v0.1 设计/实现阶段验证。

## 后续建议
- **是否建议升级为标准迭代：是。** REQ-002 已给出架构结论，建议回 PM 创建 `v0.1-prd.md` 启动标准迭代（REQ-001 L1 真实化 + 本文 4 岔路口结论作为设计输入）。REQ-001 与 REQ-002 可合并到 v0.1 同一迭代。
- **建议起始角色：PM**（创建 PRD），随后 Architect 进设计阶段，把③（client 移植）与①（条件图编排）各落一份 ADR 到 `docs/knowledge/decisions/`。
- **遗留待 v0.1 决策**：① 条件图的具体边与 `needs_context` 语义；② L0 规则表/阈值是否进 ai（还是留 xiaobao）需与 xiaobao 对齐；③ `client.py` 移植的依赖裁剪清单；④ `RunRecord` 存储后端选型（文件 vs PG）与默认开关。

## 收尾归档
- 收尾日期：2026-06-29
- 最终状态：已完成（结论待 Owner/PM Review，未自动落地为迭代）
- 已更新当前角色日志：是（`docs/progress/roles/architect.md`，已标已收尾）
- 其他角色待补充/确认：
  - PM：据本结论评估是否创建 `v0.1-prd.md` 立项（REQ-001 前置已解除）
  - xiaobao（跨项目）：L0 归属/规则对齐，本会话不改其仓
  - **coordination 回执待跟进**：REQ-002 在 coordination `REQUESTS.md` §REQ-002 / `communications/REQ-002-arch-research.md` 待跟进项仍为「待启动」，应更新为「已完成调研」。属跨项目写入，待 Owner 确认后由有权限会话按 `cross-project-collaboration.md` 落（本会话未写）。
- 已更新 `docs/progress/INDEX.md`：是（当前状态、非迭代工作表、最近收尾摘要、跨任务待办 REQ-002 置已完成）
- 已更新知识库：否——岔路口①③ 的 ADR 留到 v0.1 设计阶段落 `docs/knowledge/decisions/`（理由：预研结论未定稿落地，PRD 未创建，过早写 ADR 不符状态）
- 元信息变更：无（本次为预研，未变更项目定位/名称/技术栈/上线/接入状态，无需登记生态台账）
- 关联 commit：（见本次收尾提交）
- 下一次启动建议：PM 创建 `v0.1-prd.md`（REQ-001 L1 真实化 + 本文 4 岔路口结论作设计输入）
