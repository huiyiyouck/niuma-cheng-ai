"""HTTP 数据源：**只实现 `L1Mapper`**（设计 §3.1、ADR-0003）。

它不实现 `PullSource`、也不假装实现——HTTP 是「推」（端点被动接收、无取批、
无锁），套拉取协议会产生 2~3 个空方法，而 AC-2.2 的判据能被一组空实现糊弄
过去。这就是「按职责分层、不按模式对称」的形态（O-2 落定）。
"""
from __future__ import annotations

from typing import Any

from agent_hub.schemas import L1Input, L1Output, RunResponse, ToolSummary
from agent_hub.sources.base import MappingError


class HttpL1Mapper:
    """HTTP 侧映射：入向恒等、出向包装为 `RunResponse`。"""

    def to_l1_input(self, record: Any) -> L1Input:
        """**恒等映射**——入参已是 FastAPI 反序列化好的 `L1Input`。

        这是**真实实现**而非空方法：它明确表达「HTTP 数据源的入向无需转换」这一
        事实（AC-2.1 CN-003 澄清：恒等映射属真实实现）。与 DB 侧的差别在于
        DB 需要把库行映射成处理输入，HTTP 的调用方已经按契约构造好了。
        """
        if not isinstance(record, L1Input):
            raise MappingError("client_error", "expected L1Input")
        return record

    def from_l1_output(
        self,
        output: L1Output,
        ctx: Any,
    ) -> RunResponse:
        """出向**有实质逻辑**：包装 run_id / status / elapsed_ms / tool_summary。"""
        if not isinstance(ctx, dict):
            raise MappingError("server_error", "expected response context dict")
        try:
            return RunResponse(
                run_id=ctx["run_id"],
                status="succeeded",
                elapsed_ms=ctx["elapsed_ms"],
                tool_summary=ctx.get("tool_summary") or ToolSummary(),
                output=output,
            )
        except MappingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MappingError("server_error", f"response mapping: {type(exc).__name__}") from exc
