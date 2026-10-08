"""API 테스트 — 메모리 저장소 + stub LLM (외부 키 없이)."""
import time, jwt, pytest
from fastapi.testclient import TestClient

UA = {"User-Agent": "Mozilla/5.0 (pytest MaC)"}


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


def token(uid="11111111-1111-1111-1111-111111111111", provider="email"):
    return jwt.encode({"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 600,
                       "app_metadata": {"provider": provider, "providers": [provider]}},
                      "test-secret-for-pytest-only-0123456789", algorithm="HS256")


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["llm_mode"] == "stub"


def test_bot_blocked(client):
    assert client.post("/api/analyze", json={"memory": "x" * 20}, headers={"User-Agent": "python-requests/2.31"}).status_code == 403


def test_guest_analyze_and_quota(client):
    body = {"memory": "초여름 오후 놀이공원에서 설렘 가득했던 소중한 기억", "include_image": False}
    r1 = client.post("/api/analyze", json=body, headers={**UA, "x-forwarded-for": "10.0.0.9"})
    assert r1.status_code == 200, r1.text
    d = r1.json()
    assert len(d["palette"]) == 4 and d["verification"]["status"] == "PASS" and "specimen_id" not in d
    r2 = client.post("/api/analyze", json=body, headers={**UA, "x-forwarded-for": "10.0.0.9"})
    assert r2.json()["cache_hit"] is True and r2.json()["palette"] == d["palette"]
    r3 = client.post("/api/analyze", json=body, headers={**UA, "x-forwarded-for": "10.0.0.9"})
    assert r3.status_code == 429


def test_validation(client):
    assert client.post("/api/analyze", json={"memory": "짧음"}, headers=UA).status_code == 422


def test_credit_flow(client):
    uid = "22222222-2222-2222-2222-222222222222"
    h_email = {**UA, "Authorization": f"Bearer {token(uid, 'email')}"}
    body = {"memory": "해질녘 바닷가에서 그리움이 밀려오던 아련한 저녁", "keep_text": True, "include_image": False}
    assert client.post("/api/analyze", json=body, headers=h_email).status_code == 402          # 크레딧 0
    assert client.post("/api/me/credits/claim", headers=h_email).json()["granted"] is False   # 이메일 가입만으론 불가
    h_kakao = {**UA, "Authorization": f"Bearer {token(uid, 'kakao')}"}
    c = client.post("/api/me/credits/claim", headers=h_kakao).json()
    assert c["granted"] is True and c["credits"] == 3
    r = client.post("/api/analyze", json=body, headers=h_kakao)
    assert r.status_code == 200, r.text
    sid = r.json()["specimen_id"]
    assert client.get("/api/me/credits", headers=h_kakao).json()["credits"] == 2
    again = client.post("/api/analyze", json=body, headers=h_kakao).json()
    assert again["already_owned"] is True and again["specimen_id"] == sid
    assert client.get("/api/me/credits", headers=h_kakao).json()["credits"] == 2          # 같은 기억 재입력은 차감 없음
    lst = client.get("/api/specimens", headers=h_kakao).json()["items"]
    assert lst[0]["id"] == sid
    other = {**UA, "Authorization": f"Bearer {token('33333333-3333-3333-3333-333333333333', 'kakao')}"}
    assert client.get(f"/api/specimens/{sid}", headers=other).status_code == 404               # 남의 표본 접근 불가
    from core import store
    assert "그리움" not in store._MEM["texts"][sid]["text_enc"]                                   # 원문 암호화 저장


def test_concierge(client):
    r = client.post("/api/concierge", headers=UA, json={"client_name": "홍", "contact": "010-0000-0000",
                                                        "request_type": "bespoke", "message": "맞춤 조색 문의"})
    assert r.status_code == 200
    from core import store
    assert store._MEM["concierge"][-1]["contact"] is None                                       # 연락처 암호화
