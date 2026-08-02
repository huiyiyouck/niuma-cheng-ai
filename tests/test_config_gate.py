"""启动门禁：配置不变式（设计 §2.6、§8 测试 12 与测试 25③，AC-3.6 / AC-4.7 / AC-1.3）。

这些不等式是**正确性约束、不是调优建议**，故不满足即拒绝启动、不允许 WARN
后继续。本迭代已经栽过两次「式子算得过、实际不够」：一次是 N ≤ 8 建立在
未被保证的 79s 均值上，一次是 DB_OP_BOUND 把 statement_timeout（每条语句）
当成一次写回（3 条语句）的上界。门禁的价值就在于把这类错误挡在启动处。
"""
from __future__ import annotations

import pytest

from agent_hub.config import (
    ConfigInvariantError,
    WorkerSettings,
    load_worker_settings,
    validate_worker_settings,
)


def test_defaults_pass_and_match_documented_values():
    """默认取值须与设计 §2.6 / CN-008 写的数字逐一吻合。"""
    s = validate_worker_settings(WorkerSettings())
    assert s.writeback_bound_ms == 18000      # 3 × (5000 + 1000)
    assert s.db_op_bound_ms == 23000          # tx 5000 + writeback 18000
    assert s.shutdown_grace_ms - s.claim_batch_size * s.item_budget_ms == 20000
    assert s.item_budget_ms + s.db_op_bound_ms == 263000


def test_stale_threshold_is_600s_not_1800s():
    """卡死回收阈值是 **600s**。

    1800s 是对方契约起草时臆定、无实现依据的数字（2026-07-30 其 Architect
    主动查出并认账，契约 v1.7 回填）。若沿用 1800s，不变式 2 的余量会被
    高估近 3 倍——门禁会放行实际不安全的取值。
    """
    assert WorkerSettings().stale_timeout_ms == 600000


def test_batch_size_violating_invariant_is_rejected():
    """N 调大到单条链路 ≥ 阈值 × 0.6 时拒绝启动（AC-3.6）。

    PRD 暂定的 N=8 正是在这里被挡下：8 × 263s = 2104s ≫ 360s。
    """
    with pytest.raises(ConfigInvariantError) as ei:
        validate_worker_settings(WorkerSettings(claim_batch_size=8))
    assert "360000" in str(ei.value)


def test_grace_too_small_for_writeback_is_rejected():
    """收尾余量不足以跑完写回重试时拒绝启动（不等式 1）。

    只约束上限是不够的：配 90s 完全符合「< 卡死阈值」，但在真实批量下每次
    停机都会中途强杀，残留锁照样产生（DevOps 设计 R1 问题 2）。
    """
    with pytest.raises(ConfigInvariantError) as ei:
        validate_worker_settings(WorkerSettings(shutdown_grace_ms=245000))
    assert "收尾余量" in str(ei.value)


def test_grace_must_be_below_stale_threshold():
    with pytest.raises(ConfigInvariantError):
        validate_worker_settings(WorkerSettings(shutdown_grace_ms=600000))


@pytest.mark.parametrize(
    "over",
    [
        {"lock_timeout_ms": 5000},        # lock 不小于 statement
        {"statement_timeout_ms": 6000},   # statement 不小于 tx
        {"connect_timeout_ms": 5000},     # 建连不小于 tx：重试会全耗在建连上
    ],
    ids=["lock_ge_statement", "statement_ge_tx", "connect_ge_tx"],
)
def test_timeout_layering_is_enforced(over):
    """三层超时须逐层收紧，否则日志里无法区分等锁 / 查询慢 / 事务超时。"""
    with pytest.raises(ConfigInvariantError):
        validate_worker_settings(WorkerSettings(**over))


def test_db_mode_missing_credentials_is_rejected():
    with pytest.raises(ConfigInvariantError) as ei:
        validate_worker_settings(WorkerSettings(run_mode="db"))
    assert "AI_DB_HOST" in str(ei.value)


# --- AC-1.3：模式开关的失败安全默认 ---
@pytest.mark.parametrize("raw", ["", "DB_MODE", "1", "yes", "  "])
def test_invalid_run_mode_falls_back_to_http(monkeypatch, raw):
    """缺失或非法 → 回落 http 并 WARN，**不得静默进入 db 模式**。"""
    monkeypatch.setenv("RUN_MODE", raw)
    assert load_worker_settings().run_mode == "http"


@pytest.mark.parametrize("raw, expected", [("db", "db"), ("DB", "db"), ("http", "http")])
def test_valid_run_mode_is_honored(monkeypatch, raw, expected):
    monkeypatch.setenv("RUN_MODE", raw)
    assert load_worker_settings().run_mode == expected


def test_non_integer_config_is_rejected(monkeypatch):
    monkeypatch.setenv("L1_ITEM_BUDGET_MS", "abc")
    with pytest.raises(ConfigInvariantError):
        load_worker_settings()
