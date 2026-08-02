"""`/health` 三重探活（AC-9.3 / 设计 §3.6、§8 测试 3/4/5）+ v0.1 兼容。

news-l1 相关测试（含预取上下文计数口径）在 tests/test_news_l1.py。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_hub.config import WorkerSettings
from agent_hub.health import build_health
from agent_hub.main import app
from agent_hub.worker.state import WorkerState

client = TestClient(app)


# --- v0.1 兼容：响应体是增量扩展，既有冒烟脚本不受影响（§6.3）---
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "niuma-cheng-ai"


def test_http_mode_has_no_worker_state():
    """HTTP 模式不建 worker，`worker_state` 为 null（AC-1.1）。"""
    body = client.get("/health").json()
    assert body["mode"] == "http"
    assert body["worker_state"] is None


# --- 三态 → 状态码映射：托管层判的是状态码（DevOps 设计 R1 中②）---
@pytest.mark.parametrize(
    "phase, expected_code, expected_status",
    [("running", 200, "ok"), ("stopping", 200, "stopping"), ("dead", 503, "dead")],
)
def test_phase_maps_to_status_code(phase, expected_code, expected_status):
    state = WorkerState(lock_token="w#1")
    state.phase = phase
    body, code = build_health(WorkerSettings(run_mode="db"), state)
    assert code == expected_code
    assert body["worker_state"] == phase
    assert body["status"] == expected_status


def test_stopping_must_stay_200():
    """停机期探针失败会让托管层判死并重启，正在收尾的写回反被打断。

    故 `stopping` 必须 200，停机时长由 TimeoutStopSec 管、不由探针管（AC-5.7）。
    """
    state = WorkerState(lock_token="w#1")
    state.request_stop()
    _, code = build_health(WorkerSettings(run_mode="db"), state)
    assert code == 200


def test_dead_returns_503_with_reason():
    """worker 协程已死而进程仍活——若只看进程，探针会完整地报告「健康」。"""
    state = WorkerState(lock_token="w#1")
    state.mark_dead("RuntimeError: boom")
    body, code = build_health(WorkerSettings(run_mode="db"), state)
    assert code == 503
    assert body["dead_reason"] == "RuntimeError: boom"


# --- 在途进度与空转可观测性 ---
def test_in_flight_and_started_at_exposed():
    """答「有没有卡住」：整批处理期间 last_poll_at 不更新，
    正常工作的 worker 与卡死的表现相同（DevOps 设计 R1 中④）。"""
    state = WorkerState(lock_token="w#1")
    state.begin_item()
    body, _ = build_health(WorkerSettings(run_mode="db"), state)
    assert body["in_flight"] == 1
    assert body["current_item_started_at"] is not None


def test_consecutive_empty_polls_exposed():
    """答「ai 侧一直没领到活」——「队列真空」与「有货但没有 task」在 ai 侧
    表现完全相同（ai 不做孤儿探测），这个计数器把静默状态变成可见信号。"""
    state = WorkerState(lock_token="w#1")
    for _ in range(3):
        state.touch_poll(claimed=0)
    body, _ = build_health(WorkerSettings(run_mode="db"), state)
    assert body["consecutive_empty_polls"] == 3

    state.touch_poll(claimed=1)
    body, _ = build_health(WorkerSettings(run_mode="db"), state)
    assert body["consecutive_empty_polls"] == 0


def test_stale_tolerance_is_computed_server_side():
    """由服务端算好给运维，避免两侧各算一遍算错（§3.6）。"""
    settings = WorkerSettings(run_mode="db")
    body, _ = build_health(settings, WorkerState(lock_token="w#1"))
    assert body["stale_tolerance_ms"] == (
        settings.claim_batch_size * settings.item_budget_ms + settings.poll_interval_ms
    )


def test_self_heal_failure_is_visible():
    """自愈失败不阻止启动，但必须可见——否则残留锁会静默等对方回收。"""
    state = WorkerState(lock_token="w#1")
    state.self_heal_failed = True
    body, _ = build_health(WorkerSettings(run_mode="db"), state)
    assert body["self_heal_failed"] is True


# --- 测试 4：worker 协程死亡必须被 /health 感知（AC-9.3）---
async def test_worker_crash_marks_dead_and_health_returns_503():
    """worker 协程抛异常 → worker_state=dead 且 /health 非 200。

    这条守的是最隐蔽的失效模式：worker 以 asyncio.create_task 跑在同一
    event loop 上时，其未捕获异常**不会终止进程**——只在 gc 时于 stderr 打
    一行 `Task exception was never retrieved`。此时 worker 已死而进程、HTTP、
    mode 全部正常，探针会完整地报告「健康」，托管层永远不会重启它。
    `add_done_callback` 里**取出 task.exception()** 是它的直接解法。
    """
    import asyncio

    from agent_hub.main import _on_worker_done

    state = WorkerState(lock_token="w#1")

    async def _boom():
        raise RuntimeError("worker exploded")

    task = asyncio.create_task(_boom())
    task.add_done_callback(lambda t: _on_worker_done(state, t))
    await asyncio.sleep(0)          # 让 task 跑完并触发回调
    await asyncio.sleep(0)

    assert state.phase == "dead"
    assert "worker exploded" in (state.dead_reason or "")

    body, code = build_health(WorkerSettings(run_mode="db"), state)
    assert code == 503, "worker 已死却返回 200 —— 托管层将永远不会重启它"
    assert body["worker_state"] == "dead"


async def test_worker_normal_exit_is_not_dead():
    """正常退出（停机路径）不应被标 dead——否则每次优雅停机都像崩溃。"""
    import asyncio

    from agent_hub.main import _on_worker_done

    state = WorkerState(lock_token="w#1")

    async def _clean():
        return None

    task = asyncio.create_task(_clean())
    task.add_done_callback(lambda t: _on_worker_done(state, t))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert state.phase == "stopping"
    _, code = build_health(WorkerSettings(run_mode="db"), state)
    assert code == 200
