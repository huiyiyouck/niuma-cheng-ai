"""黄金样本比对（AC-9.4 / 设计 §6.2，O-8 这个 P0 风险的客观兜底）。

用法：
    录制（仅在改造动手前的 v0.1 基线上执行一次）：
        GOLDEN_RECORD=1 PYTHONPATH=src pytest tests/test_golden.py -q
    比对（每步改造结束后执行，见设计 §6.1 步 1/2/3/4 的完成判据）：
        PYTHONPATH=src pytest tests/test_golden.py -q

为什么不能只靠既有单测：改造时那些单测的 fake 必须一起改 async，
「用改写后的测试证明改写后的代码行为不变」是循环论证。快照落盘且纳入
版本控制后，回归判据独立于测试代码的改写。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_hub.tasks import run_task
from tests.golden_cases import CASES

GOLDEN_DIR = Path(__file__).parent / "golden"
RECORD = os.getenv("GOLDEN_RECORD") == "1"


async def _snapshot(name: str) -> dict:
    """跑一类用例并归一化为可比对的快照。

    记录的是 `TaskRunResult` 的全部可观测字段，而不只是 `L1Output`——
    `tool_summary` 是 AC-5 的计数口径、`degradations` 是 AC-7 的直接对象，
    只比对 output 会漏掉这两处回归。
    `run_id` 不入快照（每次不同，且不属被测行为）。
    """
    inp, client, tools = CASES[name]()
    result = await run_task("news-l1", f"golden_{name}", inp, client=client, tools=tools)
    return {
        "output": result.output.model_dump(mode="json") if result.output else None,
        "tool_summary": result.tool_summary.model_dump(mode="json"),
        "needs_context": result.needs_context,
        "degradations": sorted(result.degradations),
        "error": result.error,
    }


@pytest.mark.parametrize("name", sorted(CASES))
async def test_golden(name: str):
    path = GOLDEN_DIR / f"{name}.json"
    actual = await _snapshot(name)

    if RECORD:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pytest.skip(f"recorded {path.name}")

    assert path.exists(), (
        f"缺少黄金样本 {path.name}——须先在改造前的基线上执行 "
        f"`GOLDEN_RECORD=1 pytest tests/test_golden.py` 录制"
    )
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected, f"{name} 与黄金样本不一致（async 改造引入了行为变化）"
