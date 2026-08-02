"""worker 三态机与在途进度（AC-9.3 / 设计 §2.5、§4.9）。

三重探活各答一个问题，缺一不可：
- `worker_state`——**还在不在**（worker 协程死了但进程活着时，`/health` 若只
  看进程就会完整地报告「健康」，托管层永远不会重启它）；
- `in_flight` / `current_item_started_at`——**有没有卡住**（整批处理期间
  `last_poll_at` 不更新，正常工作的 worker 与卡死的表现相同）；
- 2s 内返回——**探活本身可不可信**（async 改造若不彻底，探针会按超时判死）。
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

WorkerPhase = Literal["running", "stopping", "dead"]


def make_lock_token(worker_id: str | None = None) -> str:
    """`{worker_id}#{run_token}`（O-10 落定）。

    两段式是「能自愈自己上次进程的锁」与「多实例互不误伤」能同时成立的前提：
    - `worker_id`：**稳定身份**，同一部署位置跨重启不变 → 自愈时能认出自己；
    - `run_token`：**本次运行标识**，每次启动不同 → 能区分「上次进程留下的」。

    若只用 `hostname:pid` 会误判（pid 会复用）；若把启动时间揉进 `worker_id`，
    自愈就永远匹配不到自己上次的锁。
    """
    wid = (worker_id or "").strip() or socket.gethostname()
    return f"{wid}#{time.time_ns():x}"


def worker_id_of(lock_token: str) -> str:
    return lock_token.split("#", 1)[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WorkerState:
    lock_token: str = field(default_factory=make_lock_token)
    phase: WorkerPhase = "running"
    dead_reason: str | None = None
    last_poll_at: datetime | None = None
    in_flight: int = 0
    current_item_started_at: datetime | None = None
    consecutive_empty_polls: int = 0
    self_heal_failed: bool = False
    """启动自愈失败不阻止启动（DevOps R1 问题 3）——可用性优先，但须在
    `/health` 暴露，否则残留锁会静默等对方的回收阈值。"""

    @property
    def worker_id(self) -> str:
        return worker_id_of(self.lock_token)

    def request_stop(self) -> None:
        """收到 SIGTERM：转 `stopping`，`/health` 仍返回 200。

        停机期间探针失败会被托管层判死并重启，正在收尾的写回反而被打断——
        故 `stopping` 必须是 200，由 `TimeoutStopSec` 而非探针来管停机时长。
        """
        if self.phase == "running":
            self.phase = "stopping"

    def mark_dead(self, reason: str) -> None:
        self.phase = "dead"
        self.dead_reason = reason

    def mark_stopped(self) -> None:
        """worker 协程正常退出（停机路径），不是异常死亡。"""
        self.phase = "stopping"

    def touch_poll(self, claimed: int) -> None:
        self.last_poll_at = _now()
        self.consecutive_empty_polls = 0 if claimed else self.consecutive_empty_polls + 1

    def begin_item(self) -> None:
        self.in_flight += 1
        self.current_item_started_at = _now()

    def end_item(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        if self.in_flight == 0:
            self.current_item_started_at = None

    @property
    def is_running(self) -> bool:
        return self.phase == "running"
