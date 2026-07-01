"""health 冒烟测试。

news-l1 相关测试（含预取上下文计数口径）已迁移到 tests/test_news_l1.py，
并按 S1 新口径修正（预取上下文不计入 tool_summary）。
"""
from fastapi.testclient import TestClient

from agent_hub.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
