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


def test_similar_suggestions_ngram(client, monkeypatch):
    """비슷한 문장 = 후보만. 결과(팔레트·키)는 바꾸지 않고, 규칙 문장은 후보에서 뺀다."""
    from oracle import palette
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SIMILAR_METHOD", "ngram")
    monkeypatch.setattr(palette, "_call_claude", lambda p, l: (_ for _ in ()).throw(AssertionError("LLM 호출되면 안 됨")))
    client.post("/api/palette", json={"prompt": "돌담길의 단풍"}, headers=UA)          # 사전 경로로 저장
    client.post("/api/palette", json={"prompt": "#2f5d50"}, headers=UA)               # 규칙 경로로 저장
    s = client.get("/api/palette/similar", params={"q": "돌담길 단풍 산책"}, headers=UA).json()
    assert s["method"] == "ngram" and s["threshold"] == 0.35
    keys = [x["key"] for x in s["items"]]
    assert "돌담길의 단풍" in keys and "#2f5d50" not in keys
    assert all(x["score"] >= 0.35 and x["thumbnail"].startswith("data:image/svg+xml") for x in s["items"])
    assert client.get("/api/palette/similar", params={"q": "커피 한 잔"}, headers=UA).json()["items"] == []
    r = client.post("/api/palette", json={"prompt": "돌담길의 단풍"}, headers=UA).json()
    assert r["cached"] is True and all(x["key"] != r["key"] for x in r["similar"]["items"])   # 자기 자신은 빠진다


def test_similar_embedding_mode_finds_paraphrase(client, monkeypatch):
    """임베딩 모드: 글자가 안 겹쳐도 뜻이 가까우면 찾는다 (가짜 임베딩으로 경로만 검증)."""
    from oracle import similar, store as st
    monkeypatch.setenv("VOYAGE_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("SIMILAR_METHOD", raising=False)
    monkeypatch.delenv("SIMILAR_PROVIDER", raising=False)
    assert similar.provider() == "voyage" and similar.model_name() == "voyage:voyage-4:1024"   # 둘 다 있으면 Voyage
    vecs = {"비 오는 창밖": [1, 0, 0], "창밖에 비가 내린다": [0.95, 0.1, 0], "커피 한 잔": [0, 0, 1]}
    monkeypatch.setattr(similar, "embed", lambda text, kind="query": vecs.get(text))
    s0 = st.get_store()
    s0.put_prompt("비 오는 창밖", "비 오는 창밖", {"source": "llm", "palette": []})
    similar.remember("비 오는 창밖", "비 오는 창밖")
    out = similar.find("창밖에 비가 내린다")
    assert out["method"] == "embedding" and [x["key"] for x in out["items"]] == ["비 오는 창밖"]
    assert similar.find("커피 한 잔")["items"] == []
    assert similar.ngram_sim("비 오는 창밖", "창밖에 비가 내린다") < 0.35       # ngram 이었다면 못 찾았을 쌍
    monkeypatch.setenv("SIMILAR_PROVIDER", "gemini")                               # 모델을 바꾸면
    assert similar.find("창밖에 비가 내린다")["items"] == []                       # 예전 모델 벡터와 섞지 않는다


def test_voyage_call_shape(monkeypatch):
    """Voyage 호출 인자: 저장=document · 검색=query · 차원 1024 (실제 SDK 시그니처로 검사)."""
    import inspect, voyageai
    from oracle import similar
    seen = []
    class Fake:
        def embed(self, texts, **kw):
            inspect.signature(voyageai.Client.embed).bind(None, texts, **kw)
            seen.append(kw)
            class R: embeddings = [[0.1] * 1024 for _ in texts]
            return R()
    monkeypatch.setenv("VOYAGE_API_KEY", "test")
    monkeypatch.setattr(similar, "_voyage", Fake())
    assert len(similar.embed_many(["돌담길"], "document")[0]) == 1024
    similar.embed_many(["돌담"], "query")
    assert [k["input_type"] for k in seen] == ["document", "query"] and seen[0]["model"] == "voyage-4" and seen[0]["output_dimension"] == 1024


def test_backfill_fills_missing_vectors(monkeypatch):
    """임베딩을 켜면 벡터 없는 저장 문장을 채운다 · 규칙 문장은 건너뛴다 · 이미 같은 모델이면 다시 안 채운다."""
    from oracle import similar, store as st
    monkeypatch.setenv("VOYAGE_API_KEY", "test"); monkeypatch.delenv("SIMILAR_METHOD", raising=False)
    monkeypatch.delenv("SIMILAR_PROVIDER", raising=False)
    s0 = st.get_store()
    s0.put_prompt("채우기 시험 문장", "채우기 시험 문장", {"source": "llm", "palette": []})
    s0.put_prompt("#123456", "#123456", {"source": "rule", "palette": []})
    monkeypatch.setattr(similar, "embed_many", lambda texts, kind="document": [[1.0, 0.0] for _ in texts])
    n = similar.backfill()
    assert n >= 1 and s0.prompts["채우기 시험 문장"]["embedding_model"] == "voyage:voyage-4:1024"
    assert "embedding" not in s0.prompts["#123456"]
    assert similar.backfill() == 0
