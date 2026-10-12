"""코퍼스 팀 키워드-색 표(MaC_color_keywords_v1) 반영 — KB kb-0.2 + 사물 색 표."""
import json
from pathlib import Path

from core.kb import KB, Resolver, NgramRetriever
from core.objects import resolve_objects, object_table
from core.color import hex2lab, lab2lch

ROOT = Path(__file__).resolve().parent.parent
SRC = json.loads((ROOT / "data/corpus_team/MaC_color_keywords_v1.json").read_text(encoding="utf-8"))


def test_kb_v02_keeps_old_keywords_and_quality_axis():
    kb = KB()
    assert kb.version == "kb-0.2"
    kw = {k for e in kb.items for k in e["keywords"]}
    for old in ("가족", "아빠", "하늘", "비", "눈", "꽃", "할머니"):          # kb-0.1 키워드는 지우지 않았다
        assert old in kw
    assert len(kb.by_axis["quality"]) == 3


def test_every_table_keyword_lands_somewhere():
    kb_kw = {k for e in KB().items for k in e["keywords"]}
    objs = set(json.loads((ROOT / "data/object_colors.json").read_text(encoding="utf-8"))["objects"])
    # 이미 있는 짧은 키워드가 부분 문자열로 잡는 활용형(보고 싶다 ⊃ 보고 싶)은 일부러 안 넣는다 → 그것도 '들어간 것'으로 본다
    missing = [r["keyword"] for r in SRC
               if r["keyword"] not in kb_kw | objs and not any(k in r["keyword"] for k in kb_kw)]
    assert missing == []


def test_redundant_variants_do_not_cause_wrong_links():
    """kb-0.2 첫 판에서 '보고 싶다'·'쓸쓸하다'가 n-gram 점수를 부풀려 생긴 오연결 2건 (팀 골드셋)"""
    kb = KB()
    r = Resolver(kb, NgramRetriever(kb), 0.25)
    assert r.resolve("emotion", "기대고 싶을 만큼 듬직한").kb_id != "longing_melancholy"
    assert r.resolve("emotion", "사람들 틈에서 벗어나 홀로 있고 싶던").kb_id != "longing_melancholy"


def test_new_keywords_resolve_by_keyword_not_fallback():
    kb = KB()
    r = Resolver(kb, NgramRetriever(kb), 0.25)
    assert r.resolve("space", "소나기 오던 날").kb_id == "rain_window"
    assert r.resolve("time", "눈싸움 하던 날").kb_id == "winter"
    assert r.resolve("emotion", "신나다").kb_id == "joy_excitement"
    assert r.resolve("emotion", "신나다").how == "keyword"


def test_object_table_uses_exact_hex():
    table = object_table()
    out = resolve_objects(["홍시", "칠판"], lexicon={}, learn=False)
    assert [o.how for o in out] == ["table", "table"]
    for o in out:
        hx = table[o.name]["hex"]
        assert o.lch == tuple(round(v, 2) for v in lab2lch(hex2lab(hx)))
