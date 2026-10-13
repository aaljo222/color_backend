"""eng-2.6 — 그리기 전 후보 색 · 그림 뒤 4색 ⊂ 후보 · 감정 가중 면적 · 감정-정서 대조 · 칩별 색-감정 근거 · 변형 번호."""
import numpy as np
import pytest
from PIL import Image

from core import image_first as imf
from core import candidates as cd
from core import sentence_lock
from core.affect import AffectAdjust
from core.kb import KB, Resolution
from core.pipeline import analyze, reconcile_emotion
from core.rag import get_rag, hue_family
from core.store import CACHE

pytestmark = pytest.mark.skipif(not imf.SNAP, reason="PALETTE_SNAP=0")

SENTENCES = [
    "유년의 여름날, 베어 물면 붉은 과즙보다 먼저 혀끝을 적시던 얼룩덜룩한 모스 그린 수박 껍질",
    "비 오는 밤 창가에서 떠나간 사람을 생각하던 쓸쓸한 기억",
    "초여름 오후, 아빠 손을 잡고 놀이공원 회전목마 앞에서 설레던 기억",
    "첫눈 오던 겨울 아침 골목에서 친구와 눈사람을 만들던 날",
    "할머니 댁 툇마루에서 노란 참외를 깎아 먹던 한낮",
    "노을 지는 바닷가를 엄마와 말없이 걷던 저녁",
]


def _aff(v, a, base=(3, 3)):
    return AffectAdjust(valence=v, arousal=a, base=base, c_mult=1.0, dL=0.0, how="model")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("PAINTER", "stub")
    sentence_lock._MEM.clear(); CACHE.clear()
    yield


@pytest.mark.parametrize("text", SENTENCES)
def test_chips_are_always_candidates(text):                    # 9번 요구: 그림 뒤 4색 HEX ⊂ 그리기 전 HEX
    a = analyze(text, engine="image_first")
    cands = {c["hex"] for c in a["candidates"]}
    assert len(a["palette"]) == 4 and {p["hex"] for p in a["palette"]} <= cands
    assert sum(1 for c in a["candidates"] if c["chosen"]) == 4
    assert abs(sum(p["area_ratio"] for p in a["palette"]) - 1) < 0.01


def test_snap_holds_even_when_painter_ignores_hex():           # 화가가 엉뚱한 색으로 칠해도 칩은 후보에서 나온다 (대신 심사에서 떨어진다)
    kb = KB()
    res = {"emotion": Resolution("emotion", "", "joy_excitement", "label", 1.0),
           "time": Resolution("time", "", "afternoon", "label", 1.0),
           "space": Resolution("space", "", "amusement_park", "label", 1.0),
           "quality": Resolution("quality", "", "vivid", "label", 1.0)}
    from core.synth import synthesize
    pal = synthesize(res, kb, [], _aff(5, 5, (5, 5)))["palette"]
    cands = cd.build(res, kb, [], _aff(5, 5, (5, 5)), pal, "")
    img = Image.new("RGB", (imf.W, imf.H), "#1E6B2C")             # 초록 한 색 — 후보(노랑·분홍·흰노랑)와 무관
    m = imf.measure_snapped(img, cands)
    assert {cands[i].hex for i in m["picked"]} <= {c.hex for c in cands}
    rv = imf.review(m, None, "gestural", cands)
    assert not rv["ok"] and any("더 분명하고 넓게" in f for f in rv["fails"])


def test_emotion_weight_grows_with_intensity():                # 감정이 강할수록 감정 색이 넓은 면을 받는다
    kb = KB()
    res = {"emotion": Resolution("emotion", "", "longing_melancholy", "label", 1.0),
           "time": Resolution("time", "", "night", "label", 1.0),
           "space": Resolution("space", "", "rain_window", "label", 1.0),
           "quality": Resolution("quality", "", "faded", "label", 1.0)}
    from core.synth import synthesize
    def emo_area(aff):
        pal = synthesize(res, kb, [], aff)["palette"]
        cs = cd.build(res, kb, [], aff, pal, "")
        return sum(c.area for c in cs if c.origin == "emotion" and c.tier == "large")
    assert emo_area(_aff(1, 1, (2, 2))) > emo_area(_aff(3, 3, (2, 2)))
    cs = cd.build(res, kb, [], _aff(1, 1, (2, 2)), synthesize(res, kb, [], _aff(1, 1, (2, 2)))["palette"], "")
    assert cs[0].origin == "emotion" and cs[0].tier == "large"
    assert abs(sum(c.area for c in cs) - 1) < 1e-6


def test_color_words_in_sentence_become_candidates():
    words = [w for w, _ in cd.find_color_terms("얼룩덜룩한 모스 그린 수박 껍질과 붉은 과즙")]
    assert words == ["모스그린", "붉은"]
    assert dict(cd.find_color_terms("아주 연한 하늘색 원피스"))["하늘색"][1] >= 8     # '연한' → 더 밝게
    assert cd.find_color_terms("흰머리가 난 할아버지") == []                            # '흰머리'는 색 말이 아니다
    a = analyze(SENTENCES[0], engine="image_first")
    assert any(c["origin"] == "word" and c["label"] == "모스그린" for c in a["candidates"])


def test_prompt_lists_candidates_without_object_names():
    a = analyze(SENTENCES[0], engine="image_first")
    prompt = a["_log"]["features"]["image_tries"][0]["prompt"]
    assert "쓸 색" in prompt and "넓게 — 화면의 약" in prompt
    assert all(c["hex"] in prompt for c in a["candidates"]) == imf.PAINT_HEX
    assert "수박" not in prompt.split("쓸 색")[1]                 # eng-2.5 원칙: 화가에게 사물 이름을 주지 않는다


def test_emotion_label_is_rechecked_against_affect():          # 쾌 4 인데 '그리움'(기준 쾌 2) → 정서에 맞는 감정으로
    kb = KB()
    r = Resolution("emotion", "유년의 여름날", "longing_melancholy", "label", 1.0)
    new = reconcile_emotion(r, {"valence": 4, "arousal": 3}, kb, get_rag(), SENTENCES[0])
    assert new.kb_id != "longing_melancholy" and new.how == "affect_check" and abs(kb.by_id[new.kb_id]["affect"][0] - 4) <= 1
    same = reconcile_emotion(r, {"valence": 2, "arousal": 2}, kb, get_rag(), SENTENCES[0])
    assert same is r                                             # 어긋나지 않으면 그대로
    kw = Resolution("emotion", "쓸쓸한 저녁", "longing_melancholy", "keyword", 1.0, "kw:쓸쓸")
    assert reconcile_emotion(kw, {"valence": 5, "arousal": 5}, kb, get_rag(), "혼자 걷던 쓸쓸한 저녁") is kw   # 문장에 직접 쓴 감정 낱말은 믿는다
    # 모델이 쓴 구에만 있는 낱말(문장엔 없음)로 풀린 키워드는 믿지 않는다 (2026-10-13 운영: 수박 문장 → '그리움')
    kw2 = Resolution("emotion", "유년의 그리움", "longing_melancholy", "keyword", 1.0, "kw:그리움")
    new2 = reconcile_emotion(kw2, {"valence": 4, "arousal": 3}, kb, get_rag(), SENTENCES[0])
    assert new2.kb_id != "longing_melancholy" and new2.how == "affect_check"


def test_color_links_follow_each_chip():                       # 근거 링크가 늘 같던 문제: 칩 색에 따라 달라진다
    a = analyze(SENTENCES[1], engine="image_first")
    b = analyze(SENTENCES[2], engine="image_first")
    la = {r["id"] for l in a["grounding"]["color_links"] for r in l["refs"]}
    lb = {r["id"] for l in b["grounding"]["color_links"] for r in l["refs"]}
    assert la and lb and la != lb
    assert [l["role"] for l in a["grounding"]["color_links"]] == [p["role"] for p in a["palette"]]
    assert hue_family([92, 2, 0]) == "흰색" and hue_family([50, 3, 0]) == "회색" and hue_family([15, 2, 0]) == "검정"


def test_missing_axes_are_reported_not_dropped():
    a = analyze(SENTENCES[0], engine="image_first")
    shown = {s["axis"] for s in a["grounding"]["scenes"]} | {m["axis"] for m in a["grounding"]["missing"]}
    assert {"time", "space"} <= shown


def test_variant_gives_another_painting_but_stays_locked():   # 변형 번호: 같은 문장 다른 그림, 같은 번호면 같은 값
    a0 = analyze(SENTENCES[3], engine="image_first")
    a1 = analyze(SENTENCES[3], engine="image_first", variant=1)
    a1b = analyze(SENTENCES[3], engine="image_first", variant=1)
    assert a0["specimen_hash"] != a1["specimen_hash"]
    assert a1b["specimen_hash"] == a1["specimen_hash"] and a1b["palette"] == a1["palette"]
    assert a1["variant"] == 1 and {p["hex"] for p in a1["palette"]} <= {c["hex"] for c in a1["candidates"]}
    p0 = analyze(SENTENCES[3], engine="palette", variant=3)     # 팔레트 엔진에서는 변형 번호가 뜻이 없다 → 무시
    assert "variant" not in p0


def test_shades_count_with_their_parent_and_one_chip_per_family():   # 2026-10-13 운영: 칩 3개가 '목표 1%' 곁색, 한 계열이 두 칸
    kb = KB()
    res = {"emotion": Resolution("emotion", "", "longing_melancholy", "label", 1.0),
           "time": Resolution("time", "", "afternoon", "label", 1.0),
           "space": Resolution("space", "", "sea", "label", 1.0),
           "quality": Resolution("quality", "", "vivid", "label", 1.0)}
    from core.synth import synthesize
    aff = _aff(4, 3, (2, 2))
    pal = synthesize(res, kb, [], aff)["palette"]
    cands = cd.build(res, kb, [], aff, pal, "모스 그린 껍질과 붉은 과즙")
    shades = [c for c in cands if c.origin == "shade"]
    assert shades and all(c.family == c.parent.cid for c in shades)
    # 그림을 곁색 세 개로만 칠한다 (부모 색은 거의 없음)
    from core.color import lch2lab, lab2rgb
    img = Image.new("RGB", (imf.W, imf.H))
    px = img.load()
    cols = [tuple(int(v * 255) for v in np.clip(lab2rgb(c.lab), 0, 1)) for c in shades]
    for y in range(imf.H):
        for x in range(imf.W):
            px[x, y] = cols[(x * len(cols)) // imf.W]
    m = imf.measure_snapped(img, cands)
    fams = [cands[i].family for i in m["picked"]]
    assert len(fams) == len(set(fams))                           # 한 묶음에서 칩 하나
    assert {cands[i].hex for i in m["picked"]} <= {c.hex for c in cands}
