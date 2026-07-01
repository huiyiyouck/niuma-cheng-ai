"""news-l1 S1 骨架真实化测试。

覆盖设计 §8 测试清单中 S1 范围：
1. endpoint 仍兼容原契约；2. 内部 registry 注册 news-l1、未知 task 不暴露新 HTTP 路由；
3. 预取上下文被消费但不计入 tool_summary；7. 全 provider 失败返回 failed + output=null；
8.（部分）llm 成功时 tags.processing 含真实引擎标识、不再是 stub。

真实工具（link/web）与 provider fallback 分别留 S3 / S2，本片用 fake client 注入。
"""
import pytest
from fastapi.testclient import TestClient

from agent_hub.llm.client import LLMResult, get_ai_client
from agent_hub.main import app
from agent_hub.tasks import UnknownTaskError, get_task, run_task


def make_parsed(**over):
    base = {
        "title": "示例标题",
        "summary": "这是一条真实摘要。",
        "translation": {"zh": "中文译文"},
        "analysis": "简要分析。",
        "needs_context": False,
        "scores": {
            "timeliness": {"score": 4, "reason": "时效理由"},
            "impact": {"score": 3, "reason": "影响理由"},
            "confidence": {"score": 3, "reason": "可信理由"},
            "clarity": {"score": 4, "reason": "清晰理由"},
        },
        "tags": {
            "domain": ["科技"],
            "entity": ["某公司"],
            "event": ["发布"],
            "content_type": ["news"],
        },
        "context": [],
    }
    base.update(over)
    return base


class FakeClient:
    """测试用 LLM client：可返回固定结果或抛异常模拟全 provider 失败。"""

    def __init__(self, parsed=None, exc=None, provider="fake-provider"):
        self._parsed = parsed if parsed is not None else make_parsed()
        self._exc = exc
        self._provider = provider

    def complete_json(self, messages, timeout_ms):
        if self._exc is not None:
            raise self._exc
        return LLMResult(provider_name=self._provider, parsed=self._parsed, raw="{}")


def make_client(fake):
    app.dependency_overrides[get_ai_client] = lambda: fake
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _payload(**over):
    base = {
        "source_identity": "demo",
        "domain_tags": ["test"],
        "raw_text": "示例新闻文本，内容较短。",
        "raw_content": {},
        "kb_results": [],
        "link_content": None,
        "search_summary": None,
    }
    base.update(over)
    return base


# --- 测试 1：endpoint 仍兼容原契约 ---
def test_endpoint_contract_compatible():
    c = make_client(FakeClient())
    r = c.post("/v1/runs/news-l1", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("run_")
    assert body["status"] == "succeeded"
    assert body["elapsed_ms"] >= 0
    assert body["output"] is not None
    assert body["error"] is None
    out = body["output"]
    # L1Output 契约字段齐全
    assert set(out["score_dimensions"].keys()) == {
        "timeliness",
        "impact",
        "confidence",
        "clarity",
    }
    assert out["summary"]
    assert set(out["tags"].keys()) == {
        "domain",
        "entity",
        "event",
        "content_type",
        "processing",
    }


# --- 测试 2：内部 registry 存在、未知 task 不暴露新 HTTP 路由 ---
def test_registry_registers_news_l1():
    spec = get_task("news-l1")
    assert spec.task_type == "news-l1"


def test_unknown_task_raises_internal_error():
    with pytest.raises(UnknownTaskError):
        get_task("does-not-exist")


def test_no_generic_task_route_exposed():
    c = make_client(FakeClient())
    # 通用路由未暴露：任意 task_type 路径应 404，而非命中处理
    r = c.post("/v1/runs/some-other-task", json=_payload())
    assert r.status_code == 404


# --- 测试 3：预取上下文被消费但不计入 tool_summary（旧口径修正）---
def test_prefetch_context_not_counted_in_tool_summary():
    c = make_client(FakeClient())
    r = c.post(
        "/v1/runs/news-l1",
        json=_payload(
            kb_results=[{"title": "a", "summary": "b"}],
            link_content="预取正文内容",
            search_summary="预取搜索摘要",
        ),
    )
    assert r.status_code == 200
    ts = r.json()["tool_summary"]
    assert ts["kb_search"] == 0
    assert ts["link_read"] == 0
    assert ts["web_search"] == 0


# --- 测试 7：全 provider 失败返回 failed + output=null ---
def test_all_providers_fail_returns_failed():
    c = make_client(FakeClient(exc=RuntimeError("all providers failed")))
    r = c.post("/v1/runs/news-l1", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["output"] is None
    assert body["error"]


# --- 测试 8（部分）：llm 成功时 processing 含真实引擎标识、不再是 stub ---
def test_processing_tags_carry_real_engine():
    c = make_client(FakeClient())
    r = c.post("/v1/runs/news-l1", json=_payload())
    processing = r.json()["output"]["tags"]["processing"]
    assert "engine:agent_hub" in processing
    assert "llm:fake-provider" in processing
    assert "stub" not in processing


# --- run_task 直连（不经 HTTP）：dispatch 正确 ---
def test_run_task_dispatch_succeeded():
    from agent_hub.schemas import L1Input

    result = run_task(
        "news-l1",
        "run_test",
        L1Input(**_payload()),
        client=FakeClient(),
    )
    assert result.output is not None
    assert result.error is None


# --- 测试 9（S2）：越界 score 被 normalize 到 0-5 ---
def test_out_of_range_scores_clamped():
    parsed = make_parsed(
        scores={
            "timeliness": {"score": 9, "reason": "过高"},
            "impact": {"score": -2, "reason": "过低"},
            "confidence": {"score": 3, "reason": "正常"},
            "clarity": {"score": 5, "reason": "上界"},
        }
    )
    c = make_client(FakeClient(parsed=parsed))
    dims = c.post("/v1/runs/news-l1", json=_payload()).json()["output"]["score_dimensions"]
    assert dims["timeliness"]["score"] == 5
    assert dims["impact"]["score"] == 0
    assert dims["confidence"]["score"] == 3
    assert dims["clarity"]["score"] == 5


# --- 测试 10（S2）：context URL 只保留证据中真实出现的来源 ---
def test_context_url_filtered_to_evidence():
    parsed = make_parsed(
        context=[
            {"url": "https://real.example/a", "title": "真实来源"},
            {"url": "https://hallucinated.example/x", "title": "编造来源"},
        ]
    )
    # 预取 link 提供真实证据 URL（来自 raw_content.url）
    c = make_client(FakeClient(parsed=parsed))
    body = c.post(
        "/v1/runs/news-l1",
        json=_payload(
            raw_content={"url": "https://real.example/a"},
            link_content="真实来源正文",
        ),
    ).json()
    urls = [item.get("url") for item in body["output"]["context"]]
    assert "https://real.example/a" in urls
    assert "https://hallucinated.example/x" not in urls
