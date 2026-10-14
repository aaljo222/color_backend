import time

import pytest
from fastapi.testclient import TestClient

from main import app

UA = {"User-Agent": "Mozilla/5.0 (pytest MaC)"}


@pytest.fixture
def client():
    return TestClient(app)


def _wait_for_status(client, job_id, status):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/chat/result/{job_id}", headers=UA)
        if response.status_code == 200 and response.json()["status"] == status:
            return response.json()
        time.sleep(0.01)
    pytest.fail(f"chat job did not reach status {status!r}")


def test_chat_job_preserves_agent_data(client, monkeypatch):
    from routers import chat_router

    expected = {
        "mode": "scene",
        "source": "paper",
        "answer": "장면 응답",
        "svg": "<svg/>",
        "palette": ["#123456"],
        "citations": [{"cite": "논문", "paper": "출처", "text": "근거", "score": 0.5}],
        "ou_preference": 0.25,
        "note": "기존 응답 필드",
    }
    monkeypatch.setattr(chat_router, "run_agent", lambda text: expected)

    response = client.post("/api/chat/ask", json={"text": "  행복한 장면  "}, headers=UA)
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    result = _wait_for_status(client, job_id, "done")
    assert result["data"] == expected
    assert result["text"] == "행복한 장면"


@pytest.mark.parametrize("text", ["", "   ", "x" * 301])
def test_chat_rejects_invalid_text(client, text):
    response = client.post("/api/chat/ask", json={"text": text}, headers=UA)
    assert response.status_code == 422


def test_chat_unknown_job_is_not_found(client):
    response = client.get("/api/chat/result/no-such-job", headers=UA)
    assert response.status_code == 404


def test_chat_job_errors_do_not_expose_exception(client, monkeypatch):
    from routers import chat_router

    def fail(_text):
        raise RuntimeError("private internal details")

    monkeypatch.setattr(chat_router, "run_agent", fail)
    response = client.post("/api/chat/ask", json={"text": "오류 확인"}, headers=UA)
    assert response.status_code == 200
    result = _wait_for_status(client, response.json()["job_id"], "error")
    assert result["error"] == "에이전트 처리 중 오류가 발생했습니다."
    assert "private internal details" not in response.text
