"""`/health` 三重探活契约（AC-9.3 / 设计 §3.6、§4.9）。

**处理函数不做任何 IO、不取连接池连接**，纯读内存中的 `WorkerState`——因此
天然满足 ≤2s。DB 模式下它与 worker 协程共享同一 event loop：**如果 async
改造有遗漏（某个同步 IO 阻塞了 loop），这个端点会超时**。这正是 AC-9.3 把它
设为验收项的原因——它是 async 彻底性的运行时闸门，不是普通健康检查。
"""
from __future__ import annotations

from agent_hub.config import WorkerSettings
from agent_hub.worker.state import WorkerState

# 三态 → HTTP 状态码。托管层判的是**状态码**，只改字段名等于没改
# （DevOps 设计 R1 中②）。
_PHASE_STATUS = {"running": 200, "stopping": 200, "dead": 503}
_PHASE_TEXT = {"running": "ok", "stopping": "stopping", "dead": "dead"}


def build_health(settings: WorkerSettings, state: WorkerState | None) -> tuple[dict, int]:
    """返回 (响应体, HTTP 状态码)。"""
    body: dict = {
        # v0.1 的两个键保留原位原值语义，既有冒烟脚本不受影响（§6.3）
        "status": "ok",
        "service": "niuma-cheng-ai",
        "mode": settings.run_mode,
        "worker_state": None,
    }

    if settings.run_mode != "db" or state is None:
        return body, 200

    code = _PHASE_STATUS[state.phase]
    body.update(
        {
            "status": _PHASE_TEXT[state.phase],
            "worker_state": state.phase,
            "last_poll_at": state.last_poll_at.isoformat() if state.last_poll_at else None,
            "in_flight": state.in_flight,
            "current_item_started_at": (
                state.current_item_started_at.isoformat()
                if state.current_item_started_at
                else None
            ),
            # 持续增长说明 ai 侧一直没领到活——「队列真空」与「有货但没有 task」
            # 在 ai 侧表现完全相同（按 C-5 结论 ai 不做孤儿探测），这个计数器把
            # 一个静默状态变成可见信号（§2.5 空转可观测性，据发现 A 补）
            "consecutive_empty_polls": state.consecutive_empty_polls,
            # 由服务端算好给运维，避免两侧各算一遍算错（§3.6）
            "stale_tolerance_ms": (
                settings.claim_batch_size * settings.item_budget_ms + settings.poll_interval_ms
            ),
            # 连续失败期间 worker 仍 running、状态码仍 200——**判死之前它就是
            # 「活着但在挣扎」，这正是要暴露的信息，不是要改判的状态**。不暴露
            # 的话，5 分钟的自愈能力会变成 5 分钟的静默：运维看到「服务 200、
            # 队列不动」，与「一切正常但队列本来就空」在探针上完全同形
            # （CN-010 变更 4，与 `self_heal_failed` 同一条推理）
            "consecutive_db_failures": state.consecutive_db_failures,
            # 与上一个分开：claim 失败是「DB 不可达」，写回失败是「可达但写不
            # 进」。后者下 claim 一直成功，合并计数会**恒为 0**，而队列正被
            # 静默烧成 final_failed（CN-010 变更 6）
            "consecutive_writeback_failures": state.consecutive_writeback_failures,
            "dead_reason": state.dead_reason,
            "self_heal_failed": state.self_heal_failed,
        }
    )
    return body, code
