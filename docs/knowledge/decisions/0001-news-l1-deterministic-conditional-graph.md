# ADR-0001: news-l1 采用确定性条件图编排
- 日期: 2026-06-30
- 状态: 提议

## 背景

v0.1 要把 `news-l1` 从 stub 做成真实 L1 处理，包含评分、标签、摘要、翻译和按需工具。REQ-002 调研已指出该任务是有界处理任务，不需要开放式自主规划；同时 `RunOptions.max_tool_calls` 和同步 HTTP 响应要求成本、延迟、工具次数可控。

当前代码是线性 LangGraph：`kb_search -> link_read -> web_search -> llm_process`。这会让预取上下文、链接读取、Web 搜索的触发语义不清，也无法表达“证据不足才补上下文”。

## 决策

v0.1 采用确定性条件图编排：

```text
ingest_context -> maybe_link_read -> maybe_web_search -> llm_process -> normalize_output
```

- 保留 LangGraph，用于条件边、状态传递和未来 checkpoint 扩展。
- 不引入 ReAct / 自主 agent 循环。
- link/web 是否触发由上下文充分性、URL 是否存在、Tavily 是否配置和工具预算共同决定。
- 主动 KB search 在 xiaobao 实时接口契约落地前不触发；缺口通过 `needs_context` 标记。
- 工具调用计数只统计 ai 主动调用，预取上下文不计入 `tool_summary`。

## 考虑的替代方案

| 方案 | 优点 | 缺点 | 为什么不选 |
|------|------|------|------------|
| 继续线性流水线 | 改动小 | 每个节点语义僵硬，无法表达按需工具，统计容易误导 | 不满足 AC-5 的按需工具和统计口径 |
| 自主 ReAct agent | 灵活，未来扩展强 | 成本/延迟不可控，测试复杂，工具次数难稳定约束 | `news-l1` 是有界任务，边际收益低 |
| 普通 Python if/else，不用 LangGraph | 简单直接 | 后续加入任务图、checkpoint、观测会更难演进 | 项目已引入 LangGraph，条件图能保留演进空间 |

## 后果（正面 / 负面 / 风险）

正面：
- 工具调用和延迟有边界。
- 每个分支可单测，Developer 可以用 fake tool / fake LLM 覆盖。
- 对外契约不变，内部仍能预留多 task 图结构。

负面：
- 首版上下文充分性只能用启发式，质量需要后续根据真实数据调整。
- 不支持多轮自主探索，复杂调查类任务未来需要另起 task type。

风险：
- 如果 xiaobao 后续要求实时 KB search，本图需要接入 KB adapter 和对应契约。
- Tavily API 或外部搜索质量波动会影响 grounding，需要 adapter 层隔离。
