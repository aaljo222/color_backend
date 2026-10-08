"""Color Oracle 라우터 테스트 — 메모리 저장소, LLM 은 가짜 함수로 대체 (외부 키 없이)."""
import pytest
from fastapi.testclient import TestClient

UA = {"User-Agent": "Mozilla/5.0 (pytest oracle)"}


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


def test_selfcheck(client):
    r = client.get("/api/oracle", params={"op": "selfcheck"}, headers=UA)
    assert r.status_code == 200 and r.json()["ok"] is True and len(r.json()["items"]) == 7


def test_oklch2hex(client):
    r = client.get("/api/oracle", params={"op": "oklch2hex", "L": 0.52, "C": 0.11, "H": 196.85}, headers=UA)
    assert r.json() == {"hex": "#007b7e", "gamut_mapped": True}
    assert client.get("/api/oracle", params={"op": "hex2oklch", "hex": "zz"}, headers=UA).status_code == 400


def test_palette_rule_and_lexicon_no_llm(client, monkeypatch):
    from oracle import palette
    monkeypatch.setattr(palette, "_call_claude", lambda p, l: (_ for _ in ()).throw(AssertionError("LLM 호출되면 안 됨")))
    r = client.post("/api/palette", json={"prompt": "teal 900보다 두 단계 진하게"}, headers=UA).json()
    assert r["source"] == "rule" and r["palette"][0]["hex"] == "#002a2b" and r["palette"][0]["clamped"] is True
    r = client.post("/api/palette", json={"prompt": "돌담 아주 진하게"}, headers=UA).json()
    assert r["source"] == "lexicon" and r["palette"][0]["hex"] == "#90837b" and r["llm_used"] is False


def test_palette_llm_once_then_cached_and_lexicon_wins(client, monkeypatch):
    from oracle import palette
    calls = []
    def fake(p, l):
        calls.append(p)
        return {"colors": [{"label": "돌담", "concept": "돌담", "hue": "주황", "lightness": 6, "chroma": 2},
                           {"label": "단청", "concept": "단청", "hue": "초록", "lightness": 5, "chroma": 3},
                           {"label": "x", "concept": "x", "hue": "#ff0000", "lightness": 12, "chroma": 9}]}
    monkeypatch.setattr(palette, "_call_claude", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    r1 = client.post("/api/palette", json={"prompt": "경복궁 담장"}, headers=UA).json()
    hexes = {p["label"]: p["hex"] for p in r1["palette"]}
    assert r1["source"] == "llm" and hexes["돌담"] == "#c2b4ac" and len(r1["palette"]) == 2 and r1["new_concepts"] == ["단청"]
    r2 = client.post("/api/palette", json={"prompt": "경복궁  담장!"}, headers=UA).json()
    assert r2["cached"] is True and r2["palette"] == r1["palette"] and len(calls) == 1
    r3 = client.post("/api/palette", json={"prompt": "단청 처럼"}, headers=UA).json()
    assert r3["source"] == "lexicon" and r3["palette"][0]["hex"] == hexes["단청"] and len(calls) == 1
    g = client.get("/api/palette/gallery", headers=UA).json()["items"]
    assert any(x["prompt"] == "경복궁 담장" for x in g)
    t = client.get("/api/palette/thumb", params={"prompt": "경복궁 담장"}, headers=UA)
    assert t.status_code == 200 and t.headers["content-type"].startswith("image/svg+xml")


def test_palette_needs_key_for_new_scene(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/palette", json={"prompt": "처음 보는 우주 정거장 복도"}, headers=UA)
    assert r.status_code == 502


def test_oracle_bot_blocked(client):
    assert client.get("/api/oracle", params={"op": "selfcheck"}, headers={"User-Agent": "curl/8.0"}).status_code == 403
