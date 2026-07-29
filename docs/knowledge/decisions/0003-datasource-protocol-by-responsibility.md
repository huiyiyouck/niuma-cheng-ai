# ADR-0003: 数据源协议按职责分层，不按模式对称
- 日期: 2026-07-27
- 状态: 提议

## 背景

v0.2 把 news-l1 的集成模式从「HTTP 同步调用」扩展为「数据库契约边界异步解耦」。PRD §1 约束 2 要求取数与写回封装为独立的数据源协议，处理核心不感知数据来源——这是 `decisions/0002`（ai 定位为生态内部通用 AI 中枢、多调用方预留）的硬要求：ai 直连 xiaobao 库读 schema 会把 ai 焊死在 xiaobao 上。

PRD R3 曾把协议写成「取批 / 写回成功 / 标记失败 / 释放锁」四个操作，并要求「DB 数据源与 HTTP 数据源**均为该协议的实现**」。Architect R3 Review 指出该形状有问题：两种模式的控制流方向相反——

- DB 模式是**拉**：worker 主动 `fetch_batch()` → 处理 → 写回。四个操作都有意义。
- HTTP 模式是**推**：FastAPI 端点收到请求才处理，数据由调用方推入，结果直接进响应体。**没有「取批」**（没人去取）、**没有「释放锁」**（没有锁）。

照字面实现，HTTP 数据源的四个方法里会有两到三个是 `pass` 或 `NotImplementedError`。而当时的验收判据是「切换数据源实现时处理核心 diff 为空」——**一组空实现完全能让它通过**，验收因此验不出协议是否真的对。这与「第二个调用方只需实现协议」的意图正相反：一个对半数实现者退化为空方法的协议，说明抽象切错了位置。

## 决策

**协议按职责分层，不按模式对称。** 拆成两个独立协议：

**① `L1Mapper`（映射协议）—— 两种模式均须真实实现**

```python
class L1Mapper(Protocol):
    def to_l1_input(self, record) -> L1Input: ...
    def from_l1_output(self, output: L1Output, ctx) -> Any: ...
```

这是「第二个调用方需要实现的东西」。HTTP 侧 `to_l1_input` 是**恒等映射**（`L1Input` 由 FastAPI 直接反序列化得到），`from_l1_output` 包装成 `RunResponse`；DB 侧分别是 `SourceRecord → L1Input` 与 `L1Output → WriteBackPayload`。

> 恒等映射属于**真实实现**——它明确表达了「HTTP 数据源的入向无需转换」这一事实。本协议禁止的是 `pass` / `NotImplementedError` / 返回 `None` 这类没有语义的占位。

**② `PullSource`（拉取型数据源协议）—— 仅 pull 型实现**

```python
class PullSource(Protocol):
    async def fetch_batch(self, n: int) -> list[ClaimedItem]: ...
    async def commit_success(self, item, payload) -> None: ...
    async def mark_failed(self, item, *, error_kind, message, retryable) -> None: ...
    async def reclaim_own_stale_locks(self) -> int: ...
```

HTTP 模式**不实现、也不假装实现**它。

**③ 源类型适配器注册表**：`DbL1Mapper` 内部按 `sources.type` 分发到 `SourceTypeAdapter`（`x_twitter` / `rss` / `jin10_flash`），新增一类 source type 只需新增一个适配器 + 一行注册，不动映射类、不动处理核心。

**④ 验收判据随之改为两条可证伪的**（原「核心代码完全相同」是同义反复，只要不把核心复制两份就必然成立）：

- **静态**：`grep` 断言处理核心（`tasks.py` / `graphs/` / `llm/`）不命中任何数据源概念词（表名、列名、`raw_items`、`tasks` 等）。可自动化。
- **动态**：同一份处理核心分别接上 HTTP 端点与 DB worker 两条控制流，两条均真实跑通。

## 考虑的替代方案

| 方案 | 优点 | 缺点 | 为什么不选 |
|------|------|------|-----------|
| **A. 单一四操作协议，HTTP 侧空实现**（PRD R3 原写法） | 只有一个协议，概念少 | HTTP 侧 2~3 个空方法；验收能被空实现通过；「第二调用方要实现什么」不清楚 | 抽象按模式对称而非按职责切分，是错位的；空方法会让 AC-2 失去判定力 |
| **B. 两个映射函数，不定义协议**（Architect R1 倾向、Developer 确认成本近零） | 成本几乎为零，v0.1 的 `run_task` 已经解耦 | 第二个调用方接入要回来改我们的代码 | 被 PRD §0 准则裁定 2 推翻——多调用方定位要求「实现协议」而非「改我们的代码」；协议化的代价现在付比第二调用方来敲门时付低得多 |
| **C. 按模式各定义一套完整协议**（HttpSource / DbSource 各自独立） | 各自最贴合 | 映射逻辑无法共享抽象；「第二调用方要实现什么」变成两个答案 | 丢掉了唯一真正共通的部分（映射），复用性反而更差 |
| **D. 在 `DbL1Mapper` 里写 `if source_type == …` 三分支**（替代 ③） | 少几个文件 | 新增 source type 要改核心映射类 | 违反开闭原则；xiaobao 已明确 rss/jin10 将来会接入 AI 链路 |

## 后果

**正面**

- 「第二个调用方需要做什么」有了单一答案：实现 `L1Mapper`。
- HTTP 与 DB 两条控制流各自完整，没有为了对称而生的空方法。
- AC-2 的判据变得可证伪（静态 grep + 动态双控制流），验收不再依赖主观判断。
- 新增 source type 的成本降到「一个文件 + 一行注册」。

**负面**

- 概念从一个协议变成两个协议 + 一个注册表，初次阅读的心智成本略高。
- `PullSource` 只有一个实现（`DbPullSource`），在 v0.2 范围内看起来「过度抽象」——它的价值要到第二个 pull 型数据源（或 v0.3 多实例）时才兑现。

**风险**

- 若将来出现「既推又拉」的数据源（例如 webhook + 补偿轮询），两个协议的组合方式需要再定；当前设计允许一个类同时实现两个协议，暂不构成阻塞。
- 静态 grep 判据依赖词表维护——新增表名列名时须同步更新断言词表，否则判据会漏。
