"""库内检索（KB）工具（设计 §4.3，O-3 / CN-001）。

预取 KB 上下文（`L1Input.kb_results`）由 graph 的 ingest_context 直接消费，不经本模块。
主动实时 KB 检索依赖 xiaobao 提供接口（已选方案 b，契约未落地），v0.1 默认禁用；
缺口通过 `needs_context` 标记，不阻塞其余处理。接口在此占位，待契约落地后接入。
"""
from __future__ import annotations


def kb_realtime_enabled() -> bool:
    """实时 KB 检索是否可用。v0.1 恒为 False（xiaobao 接口契约未落地）。"""
    return False
