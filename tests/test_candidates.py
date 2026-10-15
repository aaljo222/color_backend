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


def test_emotion_weight_grows_with_intensity(monkeypatch):     # legacy(eng-2.6): 감정이 강할수록 감정 색이 넓은 면을 받는다
    monkeypatch.setattr(cd, "WEIGHT_MODE", "legacy")
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


def test_candidate_rule_version_is_in_the_lock_key(monkeypatch):   # 후보 규칙을 바꾸면 같은 문장도 새로 계산된다
    a = analyze(SENTENCES[4], engine="image_first")
    monkeypatch.setattr(cd, "CAND_VERSION", "cand-test")
    b = analyze(SENTENCES[4], engine="image_first")
    assert a["sentence_lock"] != b["sentence_lock"] and not b.get("lock_hit")


def test_dark_muted_warm_colors_are_brown():                    # 2026-10-13 운영: 마루나무색 칩에 주황(기쁨·재미) 근거가 붙었다
    from core.color import hex2lab, lab2lch
    fam = lambda h: hue_family(lab2lch(hex2lab(h)))
    assert fam("#A77C5E") == "갈색" and fam("#5C4033") == "갈색"     # 마루나무색 · 밤색
    assert fam("#E8A15A") == "주황" and fam("#D4A28D") == "주황"     # 밝은 주황 · 살구
    assert fam("#871118") == "빨강" and fam("#8B3A3A") == "빨강"     # 짙은 빨강·버건디는 갈색이 아니다
    refs = [r for r in get_rag().corpus.research if "갈색" in (r.get("hues") or [])]
    assert refs and refs[0]["emotions"] == []                      # 갈색은 강한 감정 짝이 없다 (없는 근거를 만들지 않는다)


def test_candidate_labels_are_short_names():                     # 2026-10-14 10문장: '밝은 밝은 노랑 (회전목마금빛) · 강조' 같은 이름
    for t in SENTENCES:
        a = analyze(t, engine="image_first")
        for c in a["candidates"]:
            assert "(" not in c["label"] and "밝은 밝은" not in c["label"] and "짙은 짙은" not in c["label"], c["label"]


def test_shade_chip_reports_its_family(monkeypatch):            # 2026-10-14 운영: '곁색 c7 · 목표 2%' 가 48% 주조색
    for t in SENTENCES:
        a = analyze(t, engine="image_first")
        by = {c["id"]: c for c in a["candidates"]}
        for p in a["palette"]:
            b = p["basis"]
            if b.get("shade_of"):
                fam = by[b["candidate"]]["family"]
                assert b["axis"] != "shade"
                assert abs(b["area_target"] - sum(c["area_target"] for c in a["candidates"] if c["family"] == fam)) < 0.01


def test_brown_verdict_is_none():
    a = analyze(SENTENCES[4], engine="image_first")
    for l in a["grounding"]["color_links"]:
        if l["family"] == "갈색":
            assert l["verdict"] == "none"


def test_time_and_space_colors_survive_when_objects_take_slots():   # 2026-10-14 운영: 비 오는 밤 → 밤색 후보 없음, 칩 3개
    from core.objects import resolve_objects
    from core.affect import compute
    from core.synth import synthesize
    kb = KB()
    res = {"emotion": Resolution("emotion", "쓸쓸", "longing_melancholy", "keyword", 1.0, "kw:쓸쓸"),
           "time": Resolution("time", "밤", "night", "keyword", 1.0),
           "space": Resolution("space", "창가", "rain_window", "keyword", 1.0),
           "quality": Resolution("quality", "", "cherished", "fallback", 0.0)}
    objs = resolve_objects([{"name": "비"}, {"name": "창"}], learn=False)
    aff = compute({"valence": 2, "arousal": 1}, kb.by_id["longing_melancholy"])
    pal = synthesize(res, kb, objs, aff)["palette"]
    cands = cd.build(res, kb, objs, aff, pal, "비 오는 밤 창가")
    assert any(c.origin == "time" for c in cands) and any(c.origin == "space" for c in cands)


def test_always_four_chips_even_with_three_families():
    a = analyze(SENTENCES[1], engine="image_first")
    assert len(a["palette"]) == 4
    cands = [cd.Cand(f"c{i+1}", lch, "#000000", "emotion", f"x{i}", ("파랑", 5, 2), 1.0) for i, lch in
             enumerate([(60, 15, 260), (45, 25, 250), (70, 8, 230)])]
    for c in cands:
        from core.color import lch_to_hex_clipped
        c.hex = lch_to_hex_clipped(c.lch)[0]
    img = Image.new("RGB", (imf.W, imf.H), cands[0].hex)
    m = imf.measure_snapped(img, cands)
    assert len(m["picked"]) == 3                                   # 후보가 3개뿐이면 3개 (더 만들지 않는다)


def _res4():
    return {"emotion": Resolution("emotion", "", "joy_excitement", "label", 1.0),
            "time": Resolution("time", "", "afternoon", "label", 1.0),
            "space": Resolution("space", "", "amusement_park", "label", 1.0),
            "quality": Resolution("quality", "", "cherished", "label", 1.0)}


def test_team_weights_are_color_mapping_priority():            # cand-4: 팀 color_association.py v1.0 값 그대로
    assert cd.WEIGHT_MODE == "team" and cd.CAND_VERSION == "cand-4"
    assert cd.COLOR_MAPPING_PRIORITY == {"emotion": 0.30, "memory_quality": 0.20, "time": 0.15, "space": 0.15,
                                         "temperature": 0.10, "light": 0.05, "sensory": 0.05}
    assert abs(sum(cd.COLOR_MAPPING_PRIORITY.values()) - 1.0) < 1e-9
    from core.synth import synthesize
    kb, res = KB(), _res4()
    cs = cd.build(res, kb, [], None, synthesize(res, kb, [], None)["palette"], "")
    w = {c.category: c.weight for c in cs if c.origin != "shade"}
    assert w["emotion"] == 0.30 and w["time"] == 0.15 and w["space"] == 0.15 and w["accent"] == 0.10
    # 감정 강도와 상관없이 같은 비중 (가중치는 팀 표가 정한다)
    a1 = cd.build(res, kb, [], _aff(5, 5, (3, 3)), synthesize(res, kb, [], _aff(5, 5, (3, 3)))["palette"], "")
    assert [c.weight for c in a1 if c.origin == "emotion"] == [c.weight for c in cs if c.origin == "emotion"]
    # 넓게 칠할 4색의 면적 목표 비 = 가중치 비 (감정 : 시간 = 2 : 1)
    t = {c.category: c.area for c in cs if c.tier == "large"}
    assert abs(t["emotion"] / t["time"] - 2.0) < 1e-6


def test_weight_fit_compares_targets_with_chips():             # 가중치로 정한 HEX 비중 ↔ 그림 뒤 4색 칩 비중
    r = analyze("초여름 오후, 아빠 손을 잡고 놀이공원 회전목마 앞에서 설레던 기억", cache=CACHE, engine="image_first")
    wf = r["verification"]["weight_fit"]
    assert wf["source"].startswith("COLOR_MAPPING_PRIORITY") and len(wf["chips"]) == 4
    assert {c["hex"] for c in wf["chips"]} == {p["hex"] for p in r["palette"]}
    assert abs(sum(c["target"] for c in wf["chips"]) - 1) < 0.01 and abs(sum(c["painted"] for c in wf["chips"]) - 1) < 0.01
    assert wf["applied"]["temperature"] == "미구현"
