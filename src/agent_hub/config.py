"""环境变量配置。

AI 推理走外部 API（OpenAI 兼容），本服务为 IO-bound 协调者（见提案 §12.3）。
多 provider fallback 配置见 ADR-0002：优先 `LLM_PROVIDERS_JSON`，缺失时回退到
单组 `OPENAI_*` 兼容路径。key 通过 `api_key_env` 指向环境变量，不写入 JSON。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Config:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8100"))

    # LLM（OpenAI 兼容外部 API）
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    l1_llm_model: str = os.getenv("L1_LLM_MODEL", "gpt-4o-mini")
    llm_timeout_ms: int = int(os.getenv("LLM_TIMEOUT_MS", "60000"))

    # 外部搜索
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))


config = Config()


class ProviderConfigError(ValueError):
    """LLM provider 配置非法（JSON 解析失败 / 缺必填字段）。"""


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str
    timeout_ms: Optional[int] = None
    supports_response_format: Optional[bool] = None
    temperature: Optional[float] = 0.2


_REQUIRED = ("name", "base_url", "api_key_env", "model")


def load_providers() -> list[ProviderConfig]:
    """解析 provider 列表。运行时读取环境变量，便于测试与热配置。

    优先级：`LLM_PROVIDERS_JSON` > 单组 `OPENAI_*` 兼容 > 空列表。
    """
    raw = os.getenv("LLM_PROVIDERS_JSON")
    if raw:
        return _parse_providers_json(raw)

    api_key_val = os.getenv("OPENAI_API_KEY", "")
    if api_key_val:
        return [
            ProviderConfig(
                name="default",
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key_env="OPENAI_API_KEY",
                model=os.getenv("L1_LLM_MODEL", "gpt-4o-mini"),
                timeout_ms=int(os.getenv("LLM_TIMEOUT_MS", "60000")),
            )
        ]
    return []


def _parse_providers_json(raw: str) -> list[ProviderConfig]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderConfigError(f"LLM_PROVIDERS_JSON 不是合法 JSON: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ProviderConfigError("LLM_PROVIDERS_JSON 必须是非空数组")

    providers: list[ProviderConfig] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ProviderConfigError(f"provider[{i}] 必须是对象")
        missing = [k for k in _REQUIRED if not item.get(k)]
        if missing:
            raise ProviderConfigError(f"provider[{i}] 缺少字段: {', '.join(missing)}")
        providers.append(
            ProviderConfig(
                name=item["name"],
                base_url=item["base_url"],
                api_key_env=item["api_key_env"],
                model=item["model"],
                timeout_ms=item.get("timeout_ms"),
                supports_response_format=item.get("supports_response_format"),
                temperature=item.get("temperature", 0.2),
            )
        )
    return providers


# ── v0.2 DB 模式配置与启动门禁（设计 §2.6，AC-1.3 / AC-3.6 / AC-4.7 / AC-5.7）──


class ConfigInvariantError(RuntimeError):
    """启动门禁不通过。

    带不等式的约束是**正确性约束、不是调优建议**，故任一不满足即拒绝启动并
    打印算式，不允许 WARN 后继续（§2.6）。
    """


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigInvariantError(f"{name} 不是整数: {raw!r}") from exc


@dataclass
class WorkerSettings:
    """DB 模式运行参数。用函数加载而非类属性，避免受模块导入时机影响、便于测试。"""

    run_mode: str = "http"
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    item_budget_ms: int = 240000
    claim_batch_size: int = 1
    poll_interval_ms: int = 15000
    shutdown_grace_ms: int = 260000
    worker_id: str = ""
    pool_min: int = 1
    pool_max: int = 3
    connect_timeout_ms: int = 1000
    tx_timeout_ms: int = 5000
    statement_timeout_ms: int = 4000
    lock_timeout_ms: int = 3000
    empty_poll_warn: int = 20
    min_segment_ms: int = 1000
    writeback_retry: int = 2
    writeback_retry_delay_ms: int = 1000

    loop_failure_limit: int = 15
    """主循环连续 DB 失败多少次后判死（CN-010 变更 1/3）。

    **15 而非 20**：一轮失败的真实周期是 `tx_timeout + poll_interval = 20s`，
    不是 `poll_interval = 15s`——每次失败**自身**要先耗掉一个事务超时才走到
    sleep。按真实周期，20 次得 400s，已越过不变式 4 的 360s 线。
    """

    writeback_failure_limit: int = 3
    """写回连续失败多少次后判死（CN-010 变更 6）。

    **阈值只有 claim 的五分之一，因为单次代价差两个数量级**：claim 失败一次
    = 20s 空转；写回失败一次 = 240s 算力 + 一次 LLM 调用费 + 烧掉一条
    `attempt`，且该条已内部重试过才算一次。3 条连续失败 ≈ 13 分钟，足以排除
    偶发，同时把烧掉的 `attempt` 控制在 3 条以内。
    """

    # 对方的卡死回收阈值。**600s 不是 1800s**——1800 是契约起草时臆定、无实现
    # 依据的数字，实际为其 AI_STALE_TIMEOUT_MS 默认值 600000ms，test/prod 生效值
    # 均已核实（2026-07-30 其 Architect 主动查出，契约 v1.7 回填）。
    stale_timeout_ms: int = 600000

    @property
    def effective_connect_timeout_s(self) -> int:
        """libpq 实际生效的建连超时（秒）——**不等于配置值**（CN-010 变更 2）。

        libpq 的 `connect_timeout` 下限是 **2 秒**，写 1 会被解释成 2。实测
        （psycopg 连不可路由地址）：`1 → 2.02s`、`2 → 2.02s`、`3 → 3.03s`。
        门禁若按配置值 1000 断言，就是在断言一个不生效的数：把
        `AI_DB_LOCK_TIMEOUT_MS` 调到 2000 以下时门禁仍放行，而实际
        `connect(2000) > lock(1800)`，三层超时的日志区分意图静默失效。

        **用 floor 而非 round**：`round` 是银行家舍入，`3500 → 4`——配 3.5s
        得 4s，**生效值超出配置意图**；floor 下 `3500 → 3`。对超时量，只可
        少不可多（Developer 票低③）。

        **默认值不改成 2000**：那会让「配什么就生效什么」看起来成立，反而
        藏起 libpq 的下限语义，下一个把它调到 1500 的人会再踩一次。
        """
        return max(2, self.connect_timeout_ms // 1000)

    @property
    def loop_failure_window_ms(self) -> int:
        """判死窗口 = 失败次数 × 一轮失败的真实周期（CN-010 变更 3）。

        **一轮是 `tx + poll` 不是 `poll`**：`fetch_batch` 经 `run_tx`，失败前
        先被 `asyncio.wait_for` 封顶一个 `tx_timeout`，之后才退避一个轮询间隔。
        漏掉 `tx` 这一项正是本迭代第七次「校验通过但保证不成立」。

        `run_tx` **不含重试**（重试只在写回），故一轮的上界就到此为止——若它
        当初也做了重试，这里还要再乘一次尝试数。
        """
        return self.loop_failure_limit * (self.poll_interval_ms + self.tx_timeout_ms)

    @property
    def writeback_bound_ms(self) -> int:
        """一次写回（含重试）的耗时上界。

        用**事务级**超时而非 `statement_timeout`：后者在 PG 中是「每条语句」的，
        而一次写回是 3 条语句，拿它当一次写回的上界会低估（CN-008）。
        """
        return (self.writeback_retry + 1) * (self.tx_timeout_ms + self.writeback_retry_delay_ms)

    @property
    def db_op_bound_ms(self) -> int:
        """单条链路的 DB 操作上界 = claim 一个事务 + 写回（含重试）。

        AC-3.6 的不变式要覆盖 claim → 写回的**完整链路**，原式漏了 claim 事务。
        """
        return self.tx_timeout_ms + self.writeback_bound_ms


def load_worker_settings() -> WorkerSettings:
    raw_mode = os.getenv("RUN_MODE", "").strip().lower()
    # AC-1.3：缺失或非法 → 回落 http 并 WARN，**不得静默进入 db 模式**
    if raw_mode not in ("http", "db"):
        if raw_mode:
            logging.getLogger(__name__).warning(
                "RUN_MODE=%r 非法，回落到 http 模式（合法值：http / db）", raw_mode
            )
        raw_mode = "http"

    return WorkerSettings(
        run_mode=raw_mode,
        db_host=os.getenv("AI_DB_HOST", ""),
        db_port=_int_env("AI_DB_PORT", 5432),
        db_name=os.getenv("AI_DB_NAME", ""),
        db_user=os.getenv("AI_DB_USER", ""),
        db_password=os.getenv("AI_DB_PASSWORD", ""),
        item_budget_ms=_int_env("L1_ITEM_BUDGET_MS", 240000),
        claim_batch_size=_int_env("L1_CLAIM_BATCH_SIZE", 1),
        poll_interval_ms=_int_env("L1_POLL_INTERVAL_MS", 15000),
        shutdown_grace_ms=_int_env("L1_SHUTDOWN_GRACE_MS", 260000),
        worker_id=os.getenv("AI_WORKER_ID", ""),
        pool_min=_int_env("AI_DB_POOL_MIN", 1),
        pool_max=_int_env("AI_DB_POOL_MAX", 3),
        connect_timeout_ms=_int_env("AI_DB_CONNECT_TIMEOUT_MS", 1000),
        tx_timeout_ms=_int_env("AI_DB_TX_TIMEOUT_MS", 5000),
        statement_timeout_ms=_int_env("AI_DB_STATEMENT_TIMEOUT_MS", 4000),
        lock_timeout_ms=_int_env("AI_DB_LOCK_TIMEOUT_MS", 3000),
        empty_poll_warn=_int_env("L1_EMPTY_POLL_WARN", 20),
        min_segment_ms=_int_env("L1_MIN_SEGMENT_MS", 1000),
        writeback_retry=_int_env("L1_WRITEBACK_RETRY", 2),
        writeback_retry_delay_ms=_int_env("L1_WRITEBACK_RETRY_DELAY_MS", 1000),
        loop_failure_limit=_int_env("L1_LOOP_FAILURE_LIMIT", 15),
        writeback_failure_limit=_int_env("L1_WRITEBACK_FAILURE_LIMIT", 3),
        stale_timeout_ms=_int_env("AI_STALE_TIMEOUT_MS", 600000),
    )


def validate_worker_settings(s: WorkerSettings) -> WorkerSettings:
    """启动门禁：任一不满足即拒绝启动并打印算式（§2.6、AC-3.6）。"""
    errors: list[str] = []

    if not 60000 <= s.item_budget_ms <= 600000:
        errors.append(f"L1_ITEM_BUDGET_MS={s.item_budget_ms} 不在 [60000, 600000]")
    if s.claim_batch_size < 1:
        errors.append(f"L1_CLAIM_BATCH_SIZE={s.claim_batch_size} 须 ≥1")
    if not 10000 <= s.poll_interval_ms <= 30000:
        errors.append(f"L1_POLL_INTERVAL_MS={s.poll_interval_ms} 不在 [10000, 30000]")
    if s.pool_min > s.pool_max:
        errors.append(f"AI_DB_POOL_MIN={s.pool_min} > AI_DB_POOL_MAX={s.pool_max}")

    # 不变式 1：停机宽限期扣掉处理预算后，剩余须够写回（含重试）跑完
    headroom = s.shutdown_grace_ms - s.claim_batch_size * s.item_budget_ms
    if s.writeback_bound_ms > headroom:
        errors.append(
            f"写回上界 {s.writeback_bound_ms}ms > 收尾余量 {headroom}ms"
            f"（= L1_SHUTDOWN_GRACE_MS {s.shutdown_grace_ms}"
            f" − N {s.claim_batch_size} × 预算 {s.item_budget_ms}）"
        )
    if s.shutdown_grace_ms >= s.stale_timeout_ms:
        errors.append(
            f"L1_SHUTDOWN_GRACE_MS={s.shutdown_grace_ms} 须 < 卡死回收阈值 {s.stale_timeout_ms}"
        )

    # 不变式 2：单条完整链路（含 claim 与写回）须显著小于对方的卡死回收阈值
    per_item = s.item_budget_ms + s.db_op_bound_ms
    limit = int(s.stale_timeout_ms * 0.6)
    if s.claim_batch_size * per_item >= limit:
        errors.append(
            f"N {s.claim_batch_size} × (预算 {s.item_budget_ms} + DB 上界 {s.db_op_bound_ms})"
            f" = {s.claim_batch_size * per_item}ms 须 < {limit}ms（卡死阈值 {s.stale_timeout_ms} × 0.6）"
        )

    # 不变式 3：等锁应比查询慢更早触发，单语句须早于整事务——便于日志区分三者
    if not s.lock_timeout_ms < s.statement_timeout_ms < s.tx_timeout_ms:
        errors.append(
            f"须满足 lock({s.lock_timeout_ms}) < statement({s.statement_timeout_ms})"
            f" < tx({s.tx_timeout_ms})"
        )
    # 比的是**生效值**不是配置值：libpq 下限 2s，配 1000 实际按 2000 跑
    effective_connect_ms = s.effective_connect_timeout_s * 1000
    if effective_connect_ms >= s.tx_timeout_ms:
        errors.append(
            f"connect 生效值 {effective_connect_ms}ms"
            f"（配置 {s.connect_timeout_ms}，libpq 下限 2s）须 < tx({s.tx_timeout_ms})"
            f"——建连耗时计入事务预算，否则重试会全耗在建连上"
        )

    # 不变式 4：判死窗口须显著短于对方卡死回收，否则会出现「ai 已装死但未判死、
    # 条目被对方反复回收」的窗口，而不会有任何信号（CN-010 变更 3）
    loop_window_limit = int(s.stale_timeout_ms * 0.6)
    if s.loop_failure_window_ms >= loop_window_limit:
        errors.append(
            f"判死窗口 = LIMIT {s.loop_failure_limit} ×"
            f"（poll {s.poll_interval_ms} + tx {s.tx_timeout_ms}）"
            f" = {s.loop_failure_window_ms}ms 须 < {loop_window_limit}ms"
            f"（卡死阈值 {s.stale_timeout_ms} × 0.6）"
        )
    if s.loop_failure_limit < 1 or s.writeback_failure_limit < 1:
        errors.append(
            f"L1_LOOP_FAILURE_LIMIT={s.loop_failure_limit} /"
            f" L1_WRITEBACK_FAILURE_LIMIT={s.writeback_failure_limit} 须 ≥1"
        )

    if s.run_mode == "db":
        missing = [
            n for n, v in [
                ("AI_DB_HOST", s.db_host), ("AI_DB_NAME", s.db_name),
                ("AI_DB_USER", s.db_user), ("AI_DB_PASSWORD", s.db_password),
            ] if not v
        ]
        if missing:
            errors.append(f"DB 模式缺少必填配置: {', '.join(missing)}")

    if errors:
        raise ConfigInvariantError("启动门禁不通过：\n  - " + "\n  - ".join(errors))
    return s


def load_and_validate_worker_settings() -> WorkerSettings:
    return validate_worker_settings(load_worker_settings())
