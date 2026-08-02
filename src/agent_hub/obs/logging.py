"""结构化日志（AC-6 全六条 / 设计 §4.12）。

worker 模式下没有 HTTP 响应可看，日志是主要观测面（US-6）。每条一行 JSON
输出到 **stdout**，由托管层收集——v0.2 起 systemd unit 用 `StandardOutput=journal`，
journald 自带轮转与配额，**应用内不实现轮转**（AC-6.3，CN-005 变更 5 订正）。

**注入式**（AC-6.4）：logger 随 state 或依赖传入，`graphs/` 内不得直接 import
全局 logger——否则与 AC-2 的依赖方向耦合，且不可测试、不可替换。
"""
from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# 口令最常见的泄漏路径不是主动打印，而是**连接失败时驱动异常带出 DSN**
# （AC-6.2）。这些模式在记录前统一重写。
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*=\s*[^\s'\";]+"), r"\1=***"),
    (re.compile(r"(?i)\b(api[_-]?key|token|authorization)\s*[=:]\s*[^\s'\";]+"), r"\1=***"),
    (re.compile(r"postgres(?:ql)?://[^\s'\"]+"), "postgresql://***"),  # 整串 DSN
]


def redact(text: Any) -> str:
    """脱敏：口令 / key / 整串 DSN 一律替换。

    验证方式见测试——以错误口令构造连接错误，断言日志中不出现口令子串。
    """
    s = str(text)
    for pattern, replacement in _SECRET_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["error_message"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def init_logging(level: str = "INFO") -> None:
    """进程启动时初始化统一格式（AC-6.1）。输出到 stdout，不落盘、不轮转。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


class StepLogger:
    """按处理步骤记录的注入式 logger。

    统一字段（AC-6.1）：`run_id` / `raw_item_id` / `task_id` / `step` /
    `status` / `duration_ms` / `budget_remaining_ms` / `error_kind` /
    `error_message`。其中 `budget_remaining_ms` 是本设计新增——
    `error_kind=budget_exhausted` 只能告知「预算耗尽了」，逐步的剩余预算才能
    定位是**哪一段**吃掉的，从而判断该调 KB/WEB 段上限还是总预算。
    """

    def __init__(self, run_id: str, *, raw_item_id: str | None = None,
                 task_id: str | None = None, logger: logging.Logger | None = None):
        self._base = {"run_id": run_id}
        if raw_item_id:
            self._base["raw_item_id"] = raw_item_id
        if task_id:
            self._base["task_id"] = task_id
        self._log = logger or logging.getLogger("agent_hub")

    def step(self, step: str, status: str, **fields) -> None:
        payload = {**self._base, "step": step, "status": status}
        payload.update({k: v for k, v in fields.items() if v is not None})
        if "error_message" in payload:
            payload["error_message"] = redact(payload["error_message"])
        level = logging.ERROR if status == "failed" else logging.INFO
        self._log.log(level, step, extra={"fields": payload})

    def degradations(self, provider: str | None, degraded: list[str]) -> None:
        """降级与 provider 事实**在日志中冗余一份**（AC-6.6）。

        `tags_v2.processing` 是 C-10 定案后唯一承载这些标记的结构化字段，
        PRD 特意要求日志再记一份作为第二条线索——写回失败时前者就没了。
        """
        self._log.info(
            "outcome",
            extra={"fields": {**self._base, "step": "outcome", "status": "ok",
                              "llm_provider": provider, "degradations": degraded}},
        )
