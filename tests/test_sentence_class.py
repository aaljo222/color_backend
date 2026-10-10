"""eng-2.3 — 같은 문장급이면 같은 해시·HEX·색상·색 이름 / 해시는 문장 + 4색에서 태어난다 (팀장 기준 2026-10-10)."""
import itertools, threading, time
import pytest
from core import pipeline, sentence_lock, sentence_class, store, image_first
from core.llm import _stub_extract
from core.kb import get_resolver

A = "초여름에 엄마와 함께 수박을 먹은 기억"
A2 = "초여름 엄마랑 같이 수박 먹었던 기억."          # 조사·어미·시제·띄어쓰기·부사 동의어만 다름
B = "초여름에 아빠와 함께 수박을 먹은 기억"          # 사람이 다름 → 다른 문장
C = "초여름과 가을에 수박을 먹고 배가 불렀던 기억"     # 낱말이 다름 → 다른 문장


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sentence_lock._MEM.clear(); store.CACHE.clear(); image_first.IMAGE_CACHE.clear()
    monkeypatch.setattr(sentence_lock, "ENABLED", True)
    yield


def _wobbly_llm(monkeypatch, calls):
    """다시 읽을 때마다 감정 라벨이 바뀌는 LLM 대역 → 고정이 없으면 값이 흔들린다."""
    emos = itertools.cycle([e["id"] for e in get_resolver().kb.by_axis["emotion"]])
    def fake(masked, kb):
        calls.append(masked); time.sleep(0.02)
        f = _stub_extract(masked, kb); f.emotion.label = next(emos); f.emotion.phrase = ""
        return f
    monkeypatch.setattr(pipeline, "extract_features", fake)


def _sig(r):
    return r["specimen_hash"], [(p["hex"], p["color_name"], tuple(p["lch"])) for p in r["palette"]]


def test_content_tokens_define_same_class():
    t = sentence_class.content_tokens
    assert t(A) == t(A2)
    assert t(A) != t(B) and t(A) != t(C)
    assert t("수박을 먹은 기억") != t("수박을 먹지 않은 기억")              # 부정은 남긴다
    assert t("수박을 먹지 않은 기억") == t("수박을 안 먹은 기억")           # 부정 표현 두 가지는 같다


def test_same_class_sentence_gets_same_specimen(monkeypatch):
    calls = []; _wobbly_llm(monkeypatch, calls)
    a = pipeline.analyze(A, cache=store.CACHE)
    store.CACHE.clear()                                                    # 재시작과 같은 조건
    b = pipeline.analyze(A2, cache=store.CACHE)
    assert _sig(a) == _sig(b) and b["lock_hit"] and b["lock_via"] == "class"
    assert len(calls) == 1                                                 # 두 번째는 LLM 0회
    c = pipeline.analyze(A2, cache=store.CACHE)                            # 이제는 정확한 문장 키로 바로
    assert c["lock_via"] == "sentence" and _sig(c) == _sig(a)


def test_different_class_gets_its_own_specimen(monkeypatch):
    calls = []; _wobbly_llm(monkeypatch, calls)
    a, b = pipeline.analyze(A, cache=store.CACHE), pipeline.analyze(B, cache=store.CACHE)
    assert a["sentence_class"] != b["sentence_class"] and a["specimen_hash"] != b["specimen_hash"]
    assert len(calls) == 2


def test_hash_is_born_from_sentence_and_colors():
    r = pipeline.analyze(A, cache=store.CACHE)
    assert r["specimen_hash"] == sentence_lock.content_hash(r["hash_of"], r["palette"])
    payload = sentence_lock.get(r["sentence_class"])
    assert sentence_lock.verify_hash(payload)
    tampered = {**payload, "palette": [dict(payload["palette"][0], hex="#000000"), *payload["palette"][1:]]}
    assert not sentence_lock.verify_hash(tampered)                         # HEX 하나만 바뀌어도 해시가 맞지 않는다
    renamed = {**payload, "palette": [dict(payload["palette"][0], color_name="다른 이름"), *payload["palette"][1:]]}
    assert not sentence_lock.verify_hash(renamed)                          # 색 이름도 해시의 재료


def test_class_equal_sentences_at_the_same_time_compute_once(monkeypatch):
    calls = []; _wobbly_llm(monkeypatch, calls)
    out = []
    ts = [threading.Thread(target=lambda s=s: out.append(pipeline.analyze(s, cache=store.CACHE))) for s in (A, A2, A, A2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(calls) == 1 and len({repr(_sig(r)) for r in out}) == 1


def test_without_analyzer_exact_sentence_lock_still_works(monkeypatch):
    monkeypatch.setattr(sentence_class, "_kiwi", lambda: (None, None))
    calls = []; _wobbly_llm(monkeypatch, calls)
    a = pipeline.analyze(A, cache=store.CACHE); store.CACHE.clear()
    b = pipeline.analyze(A + " ", cache=store.CACHE)
    assert a["sentence_class"] is None and _sig(a) == _sig(b) and len(calls) == 1
    assert a["hash_of"] == a["sentence_lock"]
