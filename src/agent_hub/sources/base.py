"""数据源层协议与公共类型（设计 §2.1-2.3、§3.1-3.3，ADR-0003）。

**协议按职责分层，不按模式对称**（O-2 落定）：
- `L1Mapper`——两种模式**均真实实现**，是「第二个调用方需要实现的东西」；
- `PullSource`——**仅 pull 型数据源实现**，HTTP 模式不实现、也不假装实现。

HTTP 是「推」（端点被动接收、无取批、无锁），DB 是「拉」，控制流方向相反；
套同一个协议会让 HTTP 侧产生 2~3 个空方法，而 AC-2.2 的判据能被一组空实现
糊弄过去（ADR-0003）。

本模块的类型全部是**进程内类型**，不是跨服务契约——跨服务契约是
`news-l1` HTTP v1 与 `news-l1-db` v1.9，两者本迭代均不改。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from agent_hub.schemas import L1Input, L1Output


class MappingError(Exception):
    """映射失败（AC-2.5）。

    `kind` 决定重试语义：入向映射失败（必填缺失 / 类型不符）归 `client_error`，
    **不可重试**——同一份脏数据重试不会变干净；出向映射失败归 `server_error`，
    可重试。
    """

    def __init__(self, kind: Literal["client_error", "server_error"], message: str = ""):
        super().__init__(message or kind)
        self.kind = kind
        self.message = message


@dataclass
class SourceRecord:
    """数据源交给映射层的原始记录（§2.1）——数据源无关的中间表示。"""

    raw_item_id: UUID
    source_type: str
    source_identity: str
    content: dict = field(default_factory=dict)
    source_config: dict = field(default_factory=dict)
    source_item_url: str | None = None
    source_domain_tags: Any = None
    """`sources.domain_tags`(jsonb) 原值。**类型不保证**——实机核出该列既有
    `array` 也有 `object {}`，故此处不标注 `list[str]`，由 `map_domain_tags`
    做类型判定（CN-006 / CN-004 留痕的实现约束）。"""
    l0_label: str | None = None
    """v0.2 **不消费**：CN-006 已确认它是流程标记（实测唯一取值 `direct_display`）
    而非领域分类，`domain_tags` 的真源是 `sources.domain_tags`。保留字段以备
    v0.3 的 needs_context 候选。"""
    published_at: datetime | None = None


@dataclass
class ClaimedItem:
    """claim 事务的产出（§2.2）。"""

    task_id: UUID
    record: SourceRecord
    attempt: int
    max_attempts: int
    """读 `tasks.max_attempts` 列，**禁止硬编码 3**（AC-5.1 / C-8）。"""
    lock_token: str
    claimed_at: float
    """`time.monotonic()`——不用 wall clock，避免系统时钟跳变影响预算计时。"""


@dataclass
class WriteBackPayload:
    """出向映射的产物（§2.3）——唯一带列名的进程内类型，定义在数据源层内。

    **`score_total` 与 `id` 不出现在本类型中**：前者归 xiaobao 加权（O-1），
    后者由数据库生成。实现约束见 `sources/db/sql.py`——不是「写 NULL」，是
    **根本不提及**，否则 `ON CONFLICT DO UPDATE` 会把对方已算好的值覆盖成 NULL。
    """

    raw_item_id: UUID
    title: str
    summary: str
    translation: dict
    context: list
    analysis: str | None
    score_dimensions: dict
    tags_v2: dict
    language: str
    published_at: datetime | None
    needs_context: bool
    """CN-009 定案（契约 v1.9）：对方已补列，ai 写入。该信号 ai 本就在产出，
    此前因无列而丢弃。"""


@dataclass
class L1InputParts:
    """源类型适配器的产物（§3.3）——只负责 content 内的差异部分。"""

    title: str
    raw_text: str
    extra_raw_content: dict = field(default_factory=dict)
    url_adds_content: bool = True
    """抓 `source_item_url` 能否带来 `raw_text` 之外的新内容。

    `x_twitter` 为 `False`——其 `source_item_url` 指向的**就是这条推文本身**，
    正文已由 xiaobao 抓好放在 `content.text`（实测该键即 X API 的推文全文），
    再抓一次拿到的是同一份内容；且 x.com 需认证，抓取必然失败。代价不止是白
    耗一次工具预算：`degraded:link_read_failed` 对该源**恒为真**因而失去区分
    度，真出抓取故障时无法分辨（联调 8/8 条全带该标记）。

    `rss` / `jin10_flash` 保持 `True`：其 `content.summary` 可能只是摘要
    （`contentSnippet || content`），原文确在链接里，抓取有实质收益。

    判定放在适配层而非处理核心：**只有适配层知道某个源的 `content` 是全文还
    是摘要**；让处理核心按 `source_type` 特判会把数据源概念漏进核心（AC-2.2）。
    """


class SourceTypeAdapter(Protocol):
    """按 `sources.type` 分发的映射适配器。

    新增一类 source type 只需新增一个适配器 + 一行注册，不动 `DbL1Mapper`、
    不动处理核心（§7.1 决策 2 的高复用兑现）。
    """

    source_type: str

    def build(self, record: SourceRecord) -> L1InputParts: ...


class L1Mapper(Protocol):
    """数据来源 ↔ 处理核心 的双向映射。第二个调用方接入时，这是唯一需实现的协议。"""

    def to_l1_input(self, record: Any) -> L1Input:
        """源记录 → 处理输入。允许恒等映射（AC-2.1 CN-003 澄清：恒等亦属真实实现）。

        失败须抛 `MappingError(kind="client_error")`——不可重试（AC-2.5）。
        """

    def from_l1_output(self, output: L1Output, ctx: Any) -> Any:
        """处理输出 → 落地表示。DB 侧产出 `WriteBackPayload`，HTTP 侧产出 `RunResponse`。

        失败须抛 `MappingError(kind="server_error")`——可重试（AC-2.5）。
        """


class PullSource(Protocol):
    """主动拉取型数据源。HTTP 模式不实现、也不假装实现（AC-2.1）。"""

    async def fetch_batch(self, n: int) -> list[ClaimedItem]:
        """原子领取至多 n 条并置为处理中。无可领条目时返回 `[]`（不是异常，AC-3.4）。"""

    async def commit_success(self, item: ClaimedItem, payload: WriteBackPayload) -> None:
        """单事务写回结果 + 推进状态 + 释放锁（AC-4.3/4.4）。"""

    async def mark_failed(
        self, item: ClaimedItem, *, error_kind: str, message: str, retryable: bool
    ) -> None:
        """单事务标记失败 + 退避 + 释放锁（AC-5.3/5.4）。"""

    async def release(self, item: ClaimedItem) -> None:
        """主动释放一个「已 claim、未开始处理」的条目（停机路径）。

        单事务退回 `queued` + 清锁，且**不动 `attempt`、不写 `last_error`**——
        它既非成功也非失败。走 `mark_failed(retryable=True)` 会污染 `attempt` 与
        `last_error_kind`，让一次正常停机在对方侧看起来像一次处理失败，并白白
        消耗一次重试配额（设计 R1 Developer 问题 1）。
        """

    async def reclaim_own_stale_locks(self) -> int:
        """启动自愈：仅回收 `worker_id` 相同、`run_token` 不同的残留锁（AC-5.6）。"""
