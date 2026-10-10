"""eng-2.4 화풍 — 표현적 추상(gestural) 지시문·붓질 렌더·화풍별 심사 기준·화풍 바꾸기 전 고정 표본 유지."""
import re
import pytest
from core import image_first as imf, pipeline, sentence_lock, store
from core.kb import get_resolver
from core.affect import AffectAdjust

HEX = re.compile(r"#[0-9a-fA-F]{6}")
AFF = AffectAdjust(valence=4, arousal=5, base=(4, 2), c_mult=1.6, dL=0.0, how="model")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sentence_lock._MEM.clear(); store.CACHE.clear(); imf.IMAGE_CACHE.clear()
    monkeypatch.setattr(sentence_lock, "ENABLED", True)
    yield


def _res():
    r = get_resolver()
    return {a: r.resolve(a, p) for a, p in (("emotion", "가족"), ("time", "오후"), ("space", "바닷가"), ("quality", ""))}


def test_gestural_prompt_describes_brushwork_without_names_or_numbers():
    p = imf.build_prompt("요약", _res(), get_resolver().kb, [], AFF, "", None, "gestural")
    assert "표현적 추상화" in p and "붓질" in p and "튐" in p and "아주 활기차게" in p
    assert not HEX.search(p) and "Badow" not in p and "Saatchi" not in p          # 작가·사이트 이름, 숫자 색값 없음
    q = imf.build_prompt("요약", _res(), get_resolver().kb, [], AFF, "", None, "color_field")
    assert "색면추상화" in q and "붓질의 에너지" not in q                         # 예전 화풍은 예전 지시문 그대로


def test_strokes_and_flecks_render_and_bad_values_are_dropped():
    base = {"background": "#F5E6D3", "shapes": []}
    plain = imf.render_scene(base, 1)
    painted = imf.render_scene({**base, "strokes": [
        {"points": [{"x": .1, "y": .2}, {"x": .5, "y": .3}, {"x": .8, "y": .25}], "width": .04, "color": "#E0457B", "softness": .2},
        {"points": [{"x": .2, "y": .2}], "width": .04, "color": "#E0457B", "softness": .2},          # 점 하나 → 버림
        {"points": [{"x": .2, "y": .2}, {"x": .3, "y": .3}], "width": .04, "color": "red", "softness": .2}],   # 색 형식 틀림 → 버림
        "flecks": [{"x": .5, "y": .5, "r": .01, "color": "#2E86C1"}, {"x": .5, "y": .5, "r": .01, "color": "#zzz"}]}, 1)
    a, b = plain.convert("RGB"), painted.convert("RGB")
    assert a.getpixel((360, 450)) != b.getpixel((360, 450))                       # 튐이 찍혔다
    assert b.getpixel((int(.5 * imf.W), int(.3 * imf.H)))[0] > b.getpixel((int(.5 * imf.W), int(.3 * imf.H)))[2]   # 분홍 붓질


def test_cover_threshold_depends_on_style():
    m = {"centers": imf.measure(imf.render_scene({"background": "#F5E6D3", "shapes": []}))["centers"],
         "ratios": [.4, .3, .2, .1], "coverage": 0.60, "de_p90": 9.0}
    assert imf.review(m, None, "gestural")["ok"] is True
    assert imf.review(m, None, "color_field")["ok"] is False


def test_stub_gestural_differs_from_color_field():
    pal = [{"role": r, "hex": h, "lch": l} for r, h, l in (("dominant", "#F0C3AB", [82, 22, 55]), ("supporting", "#B48865", [60, 28, 65]),
                                                         ("atmospheric", "#EDDBBB", [88, 18, 90]), ("accent", "#E47570", [62, 48, 25]))]
    a = imf.paint("p", "stub", 7, pal, "color_field"); b = imf.paint("p", "stub", 7, pal, "gestural")
    assert list(a.getdata()) != list(b.getdata())
    assert list(b.getdata()) == list(imf.paint("p", "stub", 7, pal, "gestural").getdata())   # 결정론


def test_specimen_locked_before_style_change_keeps_its_values(monkeypatch):
    S = "한여름 바닷가에서 엄마랑 수박 먹던 오후"
    monkeypatch.setattr(imf, "PAINT_STYLE", "color_field")
    a = pipeline.analyze(S, cache=store.CACHE, engine="image_first")
    store.CACHE.clear(); imf.IMAGE_CACHE.clear()
    monkeypatch.setattr(imf, "PAINT_STYLE", "gestural")
    b = pipeline.analyze(S, cache=store.CACHE, engine="image_first")
    assert b["lock_hit"] and b["lock_via"] == "legacy"
    assert b["specimen_hash"] == a["specimen_hash"] and b["palette"] == a["palette"]
    c = pipeline.analyze("겨울밤 할머니 집에서 귤 까먹던 기억", cache=store.CACHE, engine="image_first")
    assert c["verification"]["criteria"]["style"] == "gestural" and c["verification"]["criteria"]["cover_min"] == 0.55


def test_objects_go_to_painter_as_color_words_not_names():
    from core.objects import resolve_objects
    objs = resolve_objects([{"name": "수박"}, {"name": "옥수수"}], learn=False)
    p = imf.build_prompt("여름 오후의 기억", _res(), get_resolver().kb, objs, AFF, "", None, "gestural")
    line = next(l for l in p.splitlines() if l.startswith("기억 속 사물의 색"))
    assert "수박" not in line and "옥수수" not in line
    assert "선명한 빨강" in line and "선명한 아주 연한 노랑" in line          # 수박(빨강·5·4), 옥수수(노랑·8·4)
    assert imf.NO_FORMS in p and "그 안의 사람·사물을 그리지 않는다" in p
    assert not HEX.search(p)


def test_color_words_table():
    assert imf.color_words(("빨강", 5, 4)) == "선명한 빨강"
    assert imf.color_words(("무채", 9, 0)) == "흰색"
    assert imf.color_words(("남색", 2, 1)) == "탁한 짙은 남색"
    assert imf.color_words(("하늘", 8, 2)) == "부드러운 아주 연한 하늘색"
