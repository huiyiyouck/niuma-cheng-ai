# 团队知识库索引

> 本索引用于快速定位项目级知识。Agent 启动时只读索引，不全文读取知识库。

## Product（产品）

## UI（界面）

## Architecture（架构）

## Engineering（工程）

## Testing（测试）

## DevOps（运维/部署）

- [跨层约束的强制点选址：谁读得到两端，谁才能强制](devops/cross-layer-constraint-enforcement-point.md) — 约束的两端分属不同层时，强制点应放在能读到两端的最低层，而非写下约束的那一层；找不到这样的层则该约束无法强制，须显式登记为无保证项
- [停服决策的证据标准：活跃连接数 0 不等于没人用](devops/service-decommission-evidence.md) — 批处理型调用方的连接数常态即为 0；判断依据应是请求日志的构成（总量+来源+时间分布）与调用方的配置指向
- [判据的盲区就是执行者的盲区：部署检查清单必须包含「服务核心能力」](devops/deployment-checklist-blind-spot.md) — 自己设计又自己执行的判据，漏掉的地方不会被看见；部署清单第一条应是「核心能力还在不在」的真实调用，不接受「配置项非空」这类间接判据

## Decisions（决策）

- [ADR-0001: news-l1 采用确定性条件图编排](decisions/0001-news-l1-deterministic-conditional-graph.md)
- [ADR-0002: 移植裁剪后的 OpenAI 兼容链式 LLM client](decisions/0002-openai-compatible-chained-llm-client.md)
- [ADR-0003: 数据源协议按职责分层，不按模式对称](decisions/0003-datasource-protocol-by-responsibility.md)
- [ADR-0004: 单条 wall-clock 预算优先于批量，批量大小取 1](decisions/0004-item-wall-clock-budget-and-batch-size.md)

## Opportunities（机会池）

## Retrospectives（复盘）
