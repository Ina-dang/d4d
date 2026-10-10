import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.storage import Store
from app.legacy.demo import DEMO_QUESTION
from app.main import create_app


def test_database_connection_closed_after_context(tmp_path):
    """저장소 작업이 끝나면 트랜잭션뿐 아니라 연결도 닫아야 한다."""
    store = Store(tmp_path / "connection.sqlite3")
    with store.connect() as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_database_connection_rolls_back_and_closes_on_error(tmp_path):
    """중간 오류가 나면 변경을 롤백하고 실패한 연결도 닫는다."""
    store = Store(tmp_path / "rollback.sqlite3")
    with pytest.raises(RuntimeError):
        with store.connect() as connection:
            connection.execute("INSERT INTO reports VALUES (?, ?)", ("temporary", "{}"))
            raise RuntimeError("테스트용 저장 중단")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with store.connect() as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM reports").fetchone() == (0,)


@pytest.fixture
def client(tmp_path):
    settings = Settings(openai_key="", tavily_key="", database=tmp_path / "test.sqlite3")
    with TestClient(create_app(settings)) as client:
        yield client


def demo(client):
    response = client.post("/api/runs", json={"question": DEMO_QUESTION, "mode": "demo"})
    assert response.status_code == 202
    rid = response.json()["id"]
    for _ in range(100):
        report = client.get(f"/api/runs/{rid}").json()
        if report["status"] != "running":
            break
        time.sleep(0.01)
    assert report["status"] == "draft"
    return report


def test_demo_end_to_end(client):
    report = demo(client)
    assert len(report["sources"]) == 4 and len(report["claims"]) == 12
    assert report["model_calls"] == 0 and report["input_tokens"] == 0
    assert [f["status"] for f in report["findings"]] == [
        "aligned",
        "conflict",
        "insufficient",
        "not_comparable",
    ]
    assert all(s["is_demo"] and s["url"] is None for s in report["sources"])
    assert client.get("/api/runs").json()[0]["id"] == report["id"]


def test_live_requires_keys_not_fake_fallback(client):
    response = client.post(
        "/api/runs", json={"question": "실제 사건을 분석해 주세요", "mode": "live"}
    )
    assert response.status_code == 503
    assert client.get("/api/runs").json() == []


def test_demo_rejects_custom_question(client):
    response = client.post(
        "/api/runs", json={"question": "임의 질문에 답하지 말 것", "mode": "demo"}
    )
    assert response.status_code == 422


def test_review_audit_stale_version_and_reapproval(client):
    r = demo(client)
    url = f"/api/runs/{r['id']}"
    body = {
        "expected_version": 1,
        "reviewer": "검토자",
        "action": "approve",
        "note": "원문과 한계 확인",
    }
    response = client.post(url + "/review", json=body)
    assert response.status_code == 200
    approved = response.json()
    assert approved["status"] == "approved" and approved["version"] == 2
    assert client.post(url + "/review", json=body).status_code == 409
    edited = client.patch(
        url + "/findings/F1",
        json={
            "expected_version": 2,
            "reviewer": "검토자",
            "confidence": "high",
            "note": "가상 원문의 시간대 직접 대조",
        },
    ).json()
    assert edited["status"] == "draft" and edited["version"] == 3
    assert len(edited["audit"]) == 2
    assert edited["findings"][0]["confidence"] == "high"
    exported = client.get(url + "/export")
    assert exported.status_code == 200
    assert "gyeopnun-" in exported.headers["content-disposition"]
    assert "가상 데이터 데모" in exported.text and "北京时间" in exported.text
    assert "v3" in exported.text and "사람 지정" in exported.text


def test_cross_origin_write_blocked(client):
    response = client.post(
        "/api/runs",
        headers={"Origin": "https://attacker.example"},
        json={"question": DEMO_QUESTION},
    )
    assert response.status_code == 403


def test_same_origin_and_host_validation(client):
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 400
    response = client.post(
        "/api/runs", headers={"Origin": "http://testserver"}, json={"question": DEMO_QUESTION}
    )
    assert response.status_code == 202


def test_no_secret_in_config(client):
    data = client.get("/api/config").json()
    assert "openai_key" not in data and "tavily_key" not in data
    assert data["live_ready"] is False


def test_static_and_csp(client):
    response = client.get("/app")
    assert response.status_code == 200 and "겹눈" in response.text
    assert "SKYTRACE" not in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "겹눈"
    for name in ("logo-gyeopnun.png", "favicon-gyeopnun.png"):
        image = client.get(f"/static/{name}")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/png")


def test_blank_review_disallowed(client):
    r = demo(client)
    response = client.post(
        f"/api/runs/{r['id']}/review",
        json={"expected_version": 1, "reviewer": " ", "note": "   ", "action": "approve"},
    )
    assert response.status_code == 422


def test_persistence_across_restart(tmp_path):
    settings = Settings(openai_key="", tavily_key="", database=tmp_path / "persist.sqlite3")
    with TestClient(create_app(settings)) as client:
        report = demo(client)
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/runs/{report['id']}").json()["status"] == "draft"
