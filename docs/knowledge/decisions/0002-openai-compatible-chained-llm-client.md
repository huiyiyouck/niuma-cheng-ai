# ADR-0002: 移植裁剪后的 OpenAI 兼容链式 LLM client
- 日期: 2026-06-30
- 状态: 提议

## 背景

v0.1 要求多 provider fallback：主 LLM 在限流、超时、错误或空响应时自动切到备用 provider。REQ-002 调研发现 Horizon 的 `client.py` 已沉淀 provider quirk 处理和 `ChainedAIClient` fallback 经验，包括 response format 降级、temperature 不支持时停发、`max_completion_tokens` / `max_tokens` 差异、空响应和 5xx fallback 等。

本项目当前只有单组 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `L1_LLM_MODEL`，无法满足多 provider fallback。

## 决策

v0.1 移植 Horizon client 的内核思想，但裁剪到本项目需要：

- 保留：
  - `AIClient` 抽象
  - OpenAI 兼容 chat completions client
  - `ChainedAIClient` provider 顺序 fallback
  - JSON 解析和本地修复
  - provider quirk 处理
- 不移植：
  - Anthropic / Gemini / Azure 原生 client
  - Horizon 的内部 `AIConfig`、usage 记账、业务模型依赖
  - 与本服务无关的 CLI / rich 输出
- 配置：
  - 推荐 `LLM_PROVIDERS_JSON` 描述 provider 列表
  - key 通过 `api_key_env` 指向环境变量
  - 保留现有 `OPENAI_*` 作为单 provider 兼容路径

## 考虑的替代方案

| 方案 | 优点 | 缺点 | 为什么不选 |
|------|------|------|------------|
| 直接自研最小 httpx 调用 | 代码少 | provider quirk 会在生产中重复踩坑，fallback 语义容易漏 | v0.1 明确要求可靠 fallback |
| 完整复制 Horizon client | 快速复用 | 带入过多无关 provider、配置和 usage 依赖 | 本项目只需要 OpenAI 兼容外部 API |
| 引入第三方 LLM SDK 聚合层 | 功能多 | 新依赖和抽象成本高，provider 行为仍需本地兜底 | 当前需求有限，httpx + 裁剪 client 足够 |

## 后果（正面 / 负面 / 风险）

正面：
- 多 provider fallback 有明确实现边界和测试矩阵。
- provider key 不写入 JSON 配置，降低泄漏风险。
- 保留单 provider 兼容路径，降低本地开发成本。

负面：
- 需要新增 LLM client 模块和 fake provider 测试。
- provider quirk 处理会让 client 代码比简单 httpx 调用更复杂。

风险：
- 不同 OpenAI 兼容 provider 的错误格式不一致，fallback 分类需要持续补充。
- `LLM_PROVIDERS_JSON` 配置错误可能导致全部 provider 不可用，DevOps Review 需重点检查配置样例和启动校验。
