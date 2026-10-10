"""eng-2.2 코퍼스 RAG — 코퍼스 검증, 해석 단계, 사물 등급, 근거 묶음, 그림 지시문, 임베딩 경로를 고정."""
import json, re
import pytest
from core import pipeline, sentence_lock, store, image_first, rag as ragmod
from core.corpus import load, validate, get_corpus
from core.kb import KB, Resolver, NgramRetriever, get_resolver
from core.objects import resolve_objects
from core.rag import CorpusRAG, get_rag, prompt_lines
from core.pii import mask

HEX = re.compile(r"#[0-9a-fA-F]{6}")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sentence_lock._MEM.clear(); store.CACHE.clear(); image_first.IMAGE_CACHE.clear()
    yield


# ── 코퍼스 ──────────────────────────────────────────────────────────────
def test_corpus_loads_and_version_is_content_hash():
    c = get_corpus()
    assert len(c.scenes) >= 80 and len(c.objects) >= 40 and len(c.research) >= 8
    assert c.version.startswith("corpus-0.1+") and c.version == load(KB()).version     # 같은 파일 = 같은 버전
    kb = KB()
    assert {s["kb_id"] for s in c.scenes} == {e["id"] for e in kb.items}                 # KB 21항목 모두 문단이 있다
    assert all(r["status"] == "confirmed" and r["url"].startswith("http") for r in c.research)


def test_bad_corpus_is_rejected(tmp_path):
    kb = KB()
    bad_scene = {"id": "x1", "axis": "emotion", "kb_id": "sea", "text": "t", "color_note": "#FF0000 빨강",
                 "source": "s", "status": "draft"}
    bad_obj = {"id": "x2", "name": "참외", "aliases": [], "hue": "금색", "lightness": 12, "chroma": 1, "text": "t",
               "source": "s", "status": "draft"}
    bad_res = {"id": "x3", "applies_to": ["a"], "evidence": "strong", "text": "t", "citation": "c", "url": "", "status": "draft"}
    errs = validate([bad_scene], [bad_obj], [bad_res], kb)
    joined = "\n".join(errs)
    assert "축 불일치" in joined and "숫자·HEX 금지" in joined and "등급 범위 밖" in joined and "url" in joined
    for f, rows in (("scenes.jsonl", [bad_scene]), ("objects.jsonl", []), ("research.jsonl", [])):
        (tmp_path / f).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    with pytest.raises(ValueError):
        load(kb, tmp_path)


# ── ① KB 해석: 코퍼스 단계 ───────────────────────────────────────────────
def test_resolver_uses_corpus_for_paraphrase():
    kb = KB(); r0 = Resolver(kb, NgramRetriever(kb), 0.25)          # eng-2.1 (코퍼스 없음)
    r1 = Resolver(kb, NgramRetriever(kb), 0.25, get_rag())          # eng-2.2
    a, b = r0.resolve("quality", "가물가물한"), r1.resolve("quality", "가물가물한")
    assert a.how == "fallback" and a.kb_id == kb.defaults["quality"]
    assert b.how == "corpus" and b.kb_id == "faded" and b.ref.startswith("sc-fd-") and b.score >= get_rag().tau


def test_unrelated_phrase_still_falls_back():
    r = get_resolver().resolve("space", "우주 정거장")
    assert r.how == "fallback"


def test_keyword_and_label_still_win_over_corpus():
    r = get_resolver()
    assert r.resolve("space", "바닷가 모래").how == "keyword"
    assert r.resolve("emotion", "처음 느낀 낯선 감정", label="calm_peace").how == "label"


# ── ② 사물 등급 ─────────────────────────────────────────────────────────
def test_corpus_object_grade_beats_llm_grade_and_lexicon_beats_corpus():
    a = resolve_objects([{"name": "참외", "hue": "파랑", "lightness": 2, "chroma": 1}], learn=False)
    b = resolve_objects([{"name": "참외"}], learn=False)
    assert a[0].how == b[0].how == "corpus" and a[0].descriptor == b[0].descriptor == ("노랑", 8, 4)
    assert a[0].lch == b[0].lch                                            # 같은 낱말 = 같은 색
    assert resolve_objects([{"name": "수박"}], learn=False)[0].how == "lexicon"
    assert resolve_objects([{"name": "감귤"}], learn=False)[0].descriptor == ("주황", 7, 4)   # 별칭


def test_corpus_object_is_not_masked_as_name():
    rag = get_rag()
    out, _ = mask("동생이랑 참외랑 솜사탕 먹던 날", protect=set(rag.corpus.object_names()))
    assert "참외" in out and "솜사탕" in out


def test_objects_in_prefers_longest_name():
    assert get_rag().objects_in("겨울밤 군고구마 먹던") == ["군고구마"]


# ── ③④ 파이프라인: 근거 묶음 ─────────────────────────────────────────────
MEM = "한겨울 밤 외할머니 집 아랫목에서 동생이랑 귤 까먹고 웃던 기억"


def test_grounding_in_response_is_deterministic_and_cited():
    a = pipeline.analyze(MEM)
    sentence_lock._MEM.clear(); store.CACHE.clear()
    b = pipeline.analyze(MEM)
    g = a["grounding"]
    assert g == b["grounding"] and a["palette"] == b["palette"]
    assert g["corpus_version"] == get_corpus().version
    used = {p["basis"].get("kb_id") for p in a["palette"]}
    assert all(s["kb_id"] in used or s["axis"] == "time" for s in g["scenes"])          # 쓰인 KB 항목의 문단만
    assert any(o["name"] == "귤" for o in g["objects"])
    rules = {x for r in g["research"] for x in r["applies_to"]}
    assert {"affect.valence_lightness", "affect.arousal_chroma", "hue.object_association"} <= rules
    assert all(r["url"].startswith("http") and r["evidence"] in ("strong", "moderate") for r in g["research"])
    assert not HEX.search(json.dumps(g, ensure_ascii=False))                             # 근거에는 숫자 색이 없다


def test_grounding_is_locked_with_the_sentence():
    a = pipeline.analyze(MEM)
    hit = pipeline.analyze(MEM)
    assert hit.get("lock_hit") and hit["grounding"] == a["grounding"]


def test_painter_prompt_gets_corpus_lines_without_color_numbers():
    res = {ax: get_resolver().resolve(ax, ph) for ax, ph in
           (("emotion", "가족"), ("time", "해 질 녘 하늘"), ("space", "바닷가"), ("quality", ""))}
    g = get_rag().ground(res, [], None)
    lines = prompt_lines(g)
    assert lines and all(not HEX.search(l) for l in lines)
    kb = get_resolver().kb
    p = image_first.build_prompt("요약", res, kb, [], None, "", g)
    assert "코퍼스 검색" in p and lines[0] in p
    assert "코퍼스" not in image_first.build_prompt("요약", res, kb, [], None)          # 근거가 없으면 예전 지시문 그대로


# ── 임베딩 경로 (가짜 제공자) ─────────────────────────────────────────────
def test_embedding_backend_used_only_when_model_and_version_match(tmp_path, monkeypatch):
    from oracle import similar
    c = get_corpus()
    vocab = sorted({ch for s in c.scenes for ch in s["text"]})
    def fake_embed(texts, kind="document"):                     # 글자 가방 임베딩 — 결정론
        return [[float(t.count(ch)) for ch in vocab] for t in texts]
    monkeypatch.setattr(similar, "model_name", lambda: "fake:bag:1")
    monkeypatch.setattr(similar, "embed_many", fake_embed)
    path = tmp_path / "emb.json"
    monkeypatch.setattr(ragmod, "EMBED_PATH", path)
    data = {"model": "fake:bag:1", "corpus_version": c.version, "ids": [s["id"] for s in c.scenes],
            "vectors": fake_embed([s["text"] for s in c.scenes])}
    path.write_text(json.dumps(data), encoding="utf-8")
    r = CorpusRAG(c)
    assert r.method == "embedding" and r.tau == ragmod.DEFAULT_TAU["embedding"]
    assert r.search("어제 일처럼 또렷하게", axis="quality", k=1)[0].passage["kb_id"] == "vivid"
    path.write_text(json.dumps({**data, "corpus_version": "corpus-0.0+old"}), encoding="utf-8")
    assert CorpusRAG(c).method == "ngram"                       # 코퍼스가 바뀌었는데 옛 벡터 → 쓰지 않는다
    path.write_text(json.dumps({**data, "model": "other:model"}), encoding="utf-8")
    assert CorpusRAG(c).method == "ngram"                       # 다른 모델 벡터 → 쓰지 않는다
