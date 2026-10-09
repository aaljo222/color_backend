"""문장 고정 (eng-2.1) — 팀장 기준: 같은 문장을 두 번(동시에) 뽑아도 해시·HEX·색상·색 이름이 같아야 한다."""
import itertools, threading, time, random
import pytest
from core import pipeline, sentence_lock, store, image_first
from core.llm import _stub_extract
from core.kb import get_resolver

S = "바쁜 아빠와 놀이공원에서 솜사탕 먹고 웃던 5월의 오후"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sentence_lock._MEM.clear(); store.CACHE.clear(); image_first.IMAGE_CACHE.clear()
    monkeypatch.setattr(sentence_lock, "ENABLED", True)
    yield


def _wobbly_llm(monkeypatch, calls):
    """다시 읽을 때마다 감정 라벨이 바뀌는 LLM (실제 Claude 가 흔들리는 상황의 대역)."""
    emos = itertools.cycle([e["id"] for e in get_resolver().kb.by_axis["emotion"]])
    def fake(masked, kb):
        calls.append(masked); time.sleep(0.02)
        f = _stub_extract(masked, kb); f.emotion.label = next(emos); f.emotion.phrase = ""
        return f
    monkeypatch.setattr(pipeline, "extract_features", fake)


def _sig(r):
    return r["specimen_hash"], [(p["hex"], p["color_name"], tuple(p["lch"])) for p in r["palette"]]


def test_without_lock_values_drift(monkeypatch):
    """문제 재현: 고정이 없으면 캐시가 사라진 뒤(재배포) 같은 문장이 다른 해시·HEX 가 된다."""
    monkeypatch.setattr(sentence_lock, "ENABLED", False)
    _wobbly_llm(monkeypatch, [])
    a = _sig(pipeline.analyze(S, cache=store.CACHE)); store.CACHE.clear()
    b = _sig(pipeline.analyze(S, cache=store.CACHE))
    assert a != b


def test_same_sentence_same_values_after_restart(monkeypatch):
    calls = []; _wobbly_llm(monkeypatch, calls)
    a = pipeline.analyze(S, cache=store.CACHE)
    store.CACHE.clear(); image_first.IMAGE_CACHE.clear()          # 재배포·재시작
    b = pipeline.analyze(S, cache=store.CACHE)
    assert _sig(a) == _sig(b) and b["lock_hit"] and len(calls) == 1   # 두 번째는 LLM 도 부르지 않는다


def test_spacing_and_punctuation_do_not_matter(monkeypatch):
    _wobbly_llm(monkeypatch, [])
    a = pipeline.analyze(S, cache=store.CACHE)
    b = pipeline.analyze("바쁜 아빠와  놀이공원에서 솜사탕 먹고 웃던 5월의오후.", cache=store.CACHE)
    assert _sig(a) == _sig(b)


def test_two_requests_at_the_same_time(monkeypatch):
    calls = []; _wobbly_llm(monkeypatch, calls)
    out = []
    ts = [threading.Thread(target=lambda: out.append(_sig(pipeline.analyze(S, cache=store.CACHE)))) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(set(map(repr, out))) == 1 and len(calls) == 1


def test_image_first_redraw_keeps_values(monkeypatch):
    """그림 먼저: 다시 그리면 그림·측정 HEX 가 달라지는 화가여도, 같은 문장이면 고정값."""
    real = image_first.run
    def jitter(*a, **k):
        o = real(*a, **k)
        for p in o["palette"]:
            p["hex"] = "#%06x" % random.randrange(1 << 24)
        return o
    monkeypatch.setattr(image_first, "run", jitter)
    a = pipeline.analyze(S, cache=store.CACHE, engine="image_first")
    store.CACHE.clear(); image_first.IMAGE_CACHE.clear()
    b = pipeline.analyze(S, cache=store.CACHE, engine="image_first")
    assert _sig(a) == _sig(b) and b["_image"] is not None             # 고정된 그림도 다시 돌려준다


def test_lock_keeps_no_text():
    pipeline.analyze(S, cache=store.CACHE)
    (row,) = sentence_lock._MEM.values()
    blob = repr(row["payload"])
    assert "솜사탕" not in blob and "memory_summary" not in row["payload"]


def test_different_sentence_different_lock():
    a = pipeline.analyze(S, cache=store.CACHE)
    b = pipeline.analyze("한겨울 밤 할머니 집 아랫목에서 귤 까먹던 기억", cache=store.CACHE)
    assert a["sentence_lock"] != b["sentence_lock"]
