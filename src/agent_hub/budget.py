"""单条 wall-clock 预算与 deadline 传递（AC-3.8 / 设计 §2.4、§4.5）。

**放在 `agent_hub/` 顶层而非设计写的 `worker/budget.py`**：`ItemBudget` 要随
`L1State` 流经 graph 各节点，而 graph 属处理核心；设计 §1.3 的依赖方向明确
要求「处理核心对 `sources/` 与 `worker/` 零依赖」，若类型定义在 `worker/` 下，
处理核心就得反向 import 拉取型控制流的包，分层即被破坏。
`ItemBudget` 本身是**数据源无关**的量（§4.5 亦如此认定），放顶层由处理核心与
worker 共用，两侧都不产生跨层依赖。

预算覆盖 pipeline 全程，而非各段独立超时之和（AC-3.8.1）——各段在发起调用前
用 `slice_for` 换取本段可用时间，而不是各读各的配置常量。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# 低于该值即认为本段预算不足，直接跳过而不发起一次必然超时的调用（§2.4）
DEFAULT_MIN_SEGMENT_MS = 1000


@dataclass
class ItemBudget:
    total_ms: int
    min_segment_ms: int = DEFAULT_MIN_SEGMENT_MS
    started: float = field(default_factory=time.monotonic)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def remaining_ms(self) -> int:
        return max(0, self.total_ms - self.elapsed_ms())

    def exhausted(self) -> bool:
        return self.remaining_ms() <= 0

    def slice_for(self, segment_cap_ms: int) -> int:
        """换取本段可用时间；返回 0 表示预算不足以支撑该段、必须跳过。

        返回 0 而不是一个极小值，是为了避免用几百毫秒去发起一次**必然超时**的
        调用——那会被 AC-7.2 记成「调用故障」，让一条因预算耗尽而降级的记录
        看起来像下游服务挂了，污染的正是本设计最看重的观测面（§2.4）。
        """
        usable = min(segment_cap_ms, self.remaining_ms())
        return 0 if usable < self.min_segment_ms else usable
