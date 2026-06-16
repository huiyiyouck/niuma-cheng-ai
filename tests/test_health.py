"""骨架冒烟测试：health + news-l1 占位流水线可跑通。"""
from fastapi.testclient import TestClient

from agent_hub.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_news_l1_stub_pipeline():
    payload = {
        "source_identity": "demo",
        "domain_tags": ["test"],
        "raw_text": "示例新闻文本",
        "kb_results": [{"title": "a", "summary": "b"}],
        "link_content": "some content",
        "search_summary": None,
    }
    r = client.post("/v1/runs/news-l1", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["tool_summary"]["kb_search"] == 1
    assert body["tool_summary"]["link_read"] == 1
    assert body["tool_summary"]["web_search"] == 0
    assert body["output"]["tags"]["processing"] == ["engine:agent_hub", "stub"]
