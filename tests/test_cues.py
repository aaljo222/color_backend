"""cues-0.1 (2026-10-13) — 키워드 판정: 낱말 경계 · 원형 · 약한 낱말 · 막는 단서 · 한 축 여러 항목."""
import json
from pathlib import Path

import pytest

from core.kb import KB, Resolver, NgramRetriever
from core.corpus import get_corpus, load, CORPUS_DIR
from core.rag import CorpusRAG
from core.cues import Cues, analyze, find

pytest.importorskip("kiwipiepy")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def resolver():
    kb = KB()
    return Resolver(kb, NgramRetriever(kb), 0.25, CorpusRAG(get_corpus()))


def pick(resolver, axis, phrase):
    r = resolver.resolve(axis, phrase)
    return None if r.how == "fallback" else r.kb_id


# ── kb-0.2.1 의 남은 오연결 3건 ─────────────────────────────────────────
def test_short_keyword_does_not_fire_inside_another_word(resolver):
    r = resolver.resolve("space", "공항 면세점 앞에서 비행기를 기다리던")
    assert not (r.how == "keyword" and r.kb_id == "rain_window")          # '비' ⊄ '비행기'
    assert pick(resolver, "space", "비 오는 날 창가") == "rain_window"
    assert pick(resolver, "time", "눈물이 고이던") != "winter"             # '눈' ⊄ '눈물'


def test_mixed_feeling_with_unsupported_emotion_falls_back(resolver):
    r = resolver.resolve("emotion", "설렘인지 불안인지 알 수 없던")
    assert r.how == "fallback" and r.ref == "cue:불안"


def test_time_word_beats_light_word(resolver):
    assert pick(resolver, "time", "창문 사이로 아침 햇살이 스며들던") == "morning"
    assert pick(resolver, "time", "오후 햇살이 따뜻하던") == "afternoon"


# ── 원형 맞춤 · 띄어 쓴 키워드 ──────────────────────────────────────────
@pytest.mark.parametrize("kw,text", [("신나다", "신나서 웃음이 났던"), ("포근하다", "포근한 이불 속"),
                                     ("편안하다", "마음이 편안하고 느긋했던"), ("눈 오다", "눈이 펑펑 오던 밤"),
                                     ("보고 싶", "엄마가 너무 보고 싶던 밤")])     # 원형이 아닌 조각 키워드도 글자로 걸린다
def test_lemma_and_spaced_keywords_match(kw, text):
    assert find(kw, analyze(text))


def test_compounds_of_short_keywords_are_listed(resolver):
    assert pick(resolver, "time", "다들 잠든 한밤중") == "night"
    assert pick(resolver, "space", "꽃잎이 흩날리던 길") == "flower_road"
    assert pick(resolver, "space", "외할머니가 가꾸던 텃밭이 있는 집") == "grandma_house"


# ── 같은 낱말, 다른 정서 (팀장 요청) ────────────────────────────────────
@pytest.mark.parametrize("phrase", ["아빠의 발소리가 들리면 무서워서 숨을 죽이던", "가족끼리 말다툼이 커지던 밤",
                                    "불 꺼진 건물에 혼자 남아 불안하던", "실수한 나를 비웃던 웃음소리"])
def test_unsupported_emotions_are_blocked(resolver, phrase):
    r = resolver.resolve("emotion", phrase)
    assert r.how == "fallback" and r.ref.startswith("cue:")


@pytest.mark.parametrize("phrase", ["긴장이 풀리던 저녁", "하나도 무섭지 않던 밤길"])
def test_release_words_unblock(resolver, phrase):
    assert not resolver.resolve("emotion", phrase).ref.startswith("cue:")


def test_weak_word_alone_does_not_decide(resolver):
    r = resolver.resolve("emotion", "아빠가 왔다")
    assert not (r.how == "keyword" and r.kb_id == "stability_affection")
    assert pick(resolver, "emotion", "든든했던 아빠") == "stability_affection"   # 강한 낱말이 있으면 정한다


@pytest.mark.parametrize("word", ["기둥", "나무", "5월"])                # 멘토 피드백: 감정 축의 비유·시간 낱말
def test_mentor_flagged_words_do_not_decide_emotion(resolver, word):
    r = resolver.resolve("emotion", f"{word} 아래에서")
    assert r.how != "keyword"


def test_label_still_wins_over_block():
    kb = KB()
    r = Resolver(kb, NgramRetriever(kb), 0.25, None).resolve("emotion", "무서웠지만 결국 웃었던", label="joy_excitement")
    assert r.how == "label"


def test_cues_file_is_consistent():
    kb = KB()
    raw = json.loads((ROOT / "data" / "cues.json").read_text(encoding="utf-8"))
    for section in ("extra_keywords", "cue_keywords"):
        for kb_id in raw[section]:
            assert kb_id.startswith("_") or kb_id in kb.by_id, f"{section}: KB 에 없는 항목 {kb_id}"
    c = Cues(kb)
    assert c.version == raw["version"]
    for axis, words in c.weak.items():                     # 약한 낱말은 실제 그 축의 KB 키워드여야 의미가 있다
        kws = {k for e in kb.by_axis[axis] for k in e["keywords"]}
        assert words <= kws, words - kws


def test_cues_off_restores_substring_matching():
    kb = KB()
    r = Resolver(kb, NgramRetriever(kb), 0.25, None, cues=None).resolve("space", "공항 면세점 앞에서 비행기를 기다리던")
    assert r.kb_id == "rain_window" and r.how == "keyword"     # 예전 동작 그대로 (CUES=0)


# ── 함께 고친 버그 ─────────────────────────────────────────────────────
def test_corpus_version_ignores_line_endings(tmp_path):
    """Windows(CRLF)로 받은 코퍼스도 서버(LF)와 같은 버전 → 같은 임베딩 파일을 쓴다."""
    kb = KB()
    lf = load(kb).version
    for f in CORPUS_DIR.iterdir():
        if f.suffix == ".jsonl":
            (tmp_path / f.name).write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert load(kb, tmp_path).version == lf


# ── 임베딩 한도·기준선 (2026-10-13) ──────────────────────────────────────
def test_query_cache_batches_and_reuses(tmp_path, monkeypatch):
    from core import embed_cache as ec
    monkeypatch.setenv("EMBED_CACHE", str(tmp_path / "c.json"))
    monkeypatch.setattr(ec, "_mem", {}); monkeypatch.setattr(ec, "_loaded", False); monkeypatch.setattr(ec, "calls", 0)
    sent = []
    fake = lambda b: (sent.append(len(b)), [[float(len(t))] for t in b])[1]
    texts = [f"문장{i}" for i in range(120)]
    assert ec.cached("ns", texts, fake) == [[float(len(t))] for t in texts]
    assert sent == [50, 50, 20]                               # 120문장 → 요청 3번
    ec.cached("ns", texts[:10] + ["새 문장"], fake)
    assert sent[-1] == 1                                      # 캐시에 없는 것만
    ec.save()
    monkeypatch.setattr(ec, "_mem", {}); monkeypatch.setattr(ec, "_loaded", False)
    ec.cached("ns", texts, fake)
    assert len(sent) == 4                                     # 디스크 캐시 → 다음 실행은 0번


def test_tau_follows_the_retriever_actually_used(monkeypatch):
    from core.kb import tau_for, DEFAULT_TAU
    kb = KB()
    monkeypatch.setenv("RETRIEVER", "embedding")
    monkeypatch.setenv("RETRIEVAL_TAU", "0.7")
    assert tau_for(NgramRetriever(kb)) == DEFAULT_TAU["ngram"]   # 임베딩 파일이 없어 ngram 으로 내려간 경우
    monkeypatch.setenv("RETRIEVER", "ngram")
    assert tau_for(NgramRetriever(kb)) == 0.7                    # ngram 에 직접 정한 값은 그대로


def test_corpus_tau_for_embedding_is_not_used_by_ngram(monkeypatch):
    from core.rag import DEFAULT_TAU as CT
    monkeypatch.setenv("CORPUS_TAU", "0.8")
    monkeypatch.setenv("CORPUS_METHOD", "auto")
    monkeypatch.setattr("core.rag._embedding_backend", lambda c, ids: None)
    assert CorpusRAG(get_corpus()).tau == CT["ngram"]
    monkeypatch.setenv("CORPUS_METHOD", "ngram")
    assert CorpusRAG(get_corpus()).tau == 0.8


def test_openai_provider_wiring(monkeypatch):
    """EMBED_PROVIDER=openai → KB·코퍼스 임베딩 모두 OpenAI 로 (네트워크 없이 연결만 확인)."""
    import core.embed_cache as ec
    from core import llm
    from oracle import similar
    monkeypatch.setenv("EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("SIMILAR_PROVIDER", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr(ec, "_mem", {}); monkeypatch.setattr(ec, "_loaded", True)
    seen = []
    monkeypatch.setattr(ec, "openai_embed", lambda b, dim: (seen.append(dim), [[1.0] * 3 for _ in b])[1])
    assert llm.embed_texts(["가"], task="RETRIEVAL_QUERY") == [[1.0] * 3]
    assert similar.provider() == "openai" and similar.model_name().startswith("openai:")
    assert similar.embed_many(["나"], "query") == [[1.0] * 3]
    assert seen == [llm.EMBED_DIM, similar.DIM]


def test_openai_base_url_and_dimension_fallback(monkeypatch):
    """교육 플랫폼 같은 OpenAI 호환 중계 주소 + 차원 지정을 못 받는 경우."""
    import httpx
    import core.embed_cache as ec
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://edu.example/v1/")
    calls = []

    def fake_post(url, timeout, headers, json):
        calls.append((url, "dimensions" in json))
        if "dimensions" in json:
            return httpx.Response(400, text='{"error": "unsupported parameter: dimensions"}')
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2]} for i in range(len(json["input"]))]})
    monkeypatch.setattr(httpx, "post", fake_post)
    assert ec.openai_embed(["가", "나"], 768) == [[0.1, 0.2], [0.1, 0.2]]
    assert calls == [("https://edu.example/v1/embeddings", True), ("https://edu.example/v1/embeddings", False)]


# ── 골드셋 v2 함정 (2026-10-13) ──────────────────────────────────────────
@pytest.mark.parametrize("axis,phrase,wrong", [("time", "이른 봄 새싹 돋던 때", "morning"),
                                               ("quality", "따뜻한 날씨였다는 것만 남은", "cherished"),
                                               ("quality", "선명하지 않은", "vivid")])
def test_v2_traps_do_not_fire_by_keyword(resolver, axis, phrase, wrong):
    r = resolver.resolve(axis, phrase)
    assert not (r.how == "keyword" and r.kb_id == wrong)


def test_negated_keyword_does_not_fire(resolver):
    r = resolver.resolve("emotion", "하나도 안 그리웠던")
    assert not (r.how == "keyword" and r.kb_id == "longing_melancholy")
    assert pick(resolver, "time", "이른 아침 안개") == "morning"        # 강한 낱말이 있으면 그대로
    assert pick(resolver, "quality", "선명한 기억") == "vivid"


def test_vivid_only_for_memory(resolver):
    """'선명'은 색·소리·목표에도 쓰여 혼자 정하지 않고, 기억과 붙을 때만 생생한."""
    assert pick(resolver, "quality", "어린 시절의 그날을 아직도 선명하게 기억한다") == "vivid"
    r = resolver.resolve("quality", "스피커 소리가 선명하다")
    assert not (r.how == "keyword" and r.kb_id == "vivid")


# ── 사물 추출 (키 없는 모드) ────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [("그 사람과 이별하던 날", []), ("특별한 선물을 받은 생일", []),
                                           ("한 달 내내 비가 내렸다", []), ("운동장을 달리던 여름", []),
                                           ("포도주를 처음 마셔 본 날", []), ("구름사다리에 매달려 놀던", []),
                                           ("달빛 아래 귤을 까먹던 겨울밤", ["달빛", "귤"]), ("딸기밭에서 놀던", ["딸기"]),
                                           ("컴퓨터 하드가 고장 나서 사진을 다 날렸던 날", []), ("동생이랑 하드를 나눠 먹던", ["하드"])])
def test_stub_objects_are_whole_nouns(text, expected):
    from core.llm import _stub_extract
    got = [o["name"] if isinstance(o, dict) else o.name for o in _stub_extract(text, KB()).objects]
    assert got == expected


def test_stub_axis_pick_uses_context():
    from core.llm import _stub_extract
    f = _stub_extract("비행기 창가 자리에서", KB())
    assert f.space.label != "rain_window"
    f = _stub_extract("밤을 구워 먹던 할머니 댁", KB())
    assert f.time.label != "night"


@pytest.mark.parametrize("axis,phrase,wrong", [("time", "낮은 담장 너머로 보이던", "afternoon"),
                                               ("emotion", "의지가 강해서 끝까지 버티던", "stability_affection"),
                                               ("time", "밤을 구워 먹던 겨울", "night")])
def test_short_word_other_senses(resolver, axis, phrase, wrong):
    r = resolver.resolve(axis, phrase)
    assert not (r.how == "keyword" and r.kb_id == wrong)
    assert pick(resolver, "time", "낮에 놀던 놀이터") == "afternoon"
