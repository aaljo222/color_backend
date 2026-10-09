"""eng-1.2 정서 보정 — 쾌→명도, 각성→채도. 색상·사물 고유색은 그대로, 같은 등급이면 같은 색."""
from core.kb import KB, Resolution
from core.synth import synthesize
from core.objects import resolve_objects
from core.affect import compute, stub_affect
from core.llm import Features

R = lambda a, i: Resolution(a, "", i, "label", 1.0)
RES = {"emotion": R("emotion", "warm_nostalgia"), "space": R("space", "grandma_house"),
       "time": R("time", "afternoon"), "quality": R("quality", "cherished")}
KB0 = KB()
EMO = KB0.by_id["warm_nostalgia"]                      # 기준점 쾌 4 · 각성 2


def _hex(aff=None, objs=None):
    return [x["hex"] for x in synthesize(RES, KB0, objs, aff)["palette"]]


def test_no_grade_or_anchor_grade_means_no_change():     # 등급 없음 / 기준점과 같음 → eng-1.1 과 같은 색
    base = _hex()
    assert _hex(compute(None, EMO)) == base
    assert _hex(compute({"valence": 4, "arousal": 2}, EMO)) == base


def test_arousal_raises_chroma_keeps_hue():
    lo = synthesize(RES, KB0, None, compute({"valence": 4, "arousal": 2}, EMO))["palette"][0]["lch"]
    hi = synthesize(RES, KB0, None, compute({"valence": 4, "arousal": 4}, EMO))["palette"][0]["lch"]
    assert hi[1] > lo[1] * 1.3                           # +2칸 = 채도 ×1.4 (색역 안)
    assert abs(hi[2] - lo[2]) < 1.0 and abs(hi[0] - lo[0]) < 1.0


def test_valence_moves_lightness():
    lo = synthesize(RES, KB0, None, compute({"valence": 2, "arousal": 2}, EMO))["palette"][0]["lch"]
    hi = synthesize(RES, KB0, None, compute({"valence": 5, "arousal": 2}, EMO))["palette"][0]["lch"]
    assert hi[0] - lo[0] > 6


def test_object_colors_untouched():
    objs = resolve_objects([{"name": "수박"}, {"name": "옥수수"}], learn=False)
    a = synthesize(RES, KB0, objs, None)["palette"]
    b = synthesize(RES, KB0, objs, compute({"valence": 5, "arousal": 5}, EMO))["palette"]
    assert a[2]["hex"] == b[2]["hex"]                    # 옥수수(분위기색)는 사물 고유색 그대로
    assert "affect" in b[0]["basis"] and "affect" not in b[2]["basis"]


def test_out_of_range_grade_is_ignored():               # 검증 게이트: 범위 밖 등급은 기준점으로
    adj = compute({"valence": 9, "arousal": -3}, EMO)
    assert (adj.valence, adj.arousal) == (4, 2) and adj.c_mult == 1 and adj.dL == 0


def test_deterministic_and_cache_key():
    a1 = synthesize(RES, KB0, None, compute({"valence": 4, "arousal": 4}, EMO))
    a2 = synthesize(RES, KB0, None, compute({"valence": 4, "arousal": 4}, EMO))
    b = synthesize(RES, KB0, None, compute({"valence": 4, "arousal": 1}, EMO))
    assert a1 == a2 and a1["cache_key"] != b["cache_key"]


def test_stub_affect_and_legacy_features():
    assert stub_affect("한여름 시원한 수박", EMO)["arousal"] == 3
    assert stub_affect("비 오는 밤 조용한 창가", EMO)["arousal"] == 1
    f = Features.model_validate({k: {"phrase": "", "label": ""} for k in ("emotion", "time", "space", "memory_quality")})
    assert f.affect is None                              # 예전 응답(affect 없음)도 받는다


def test_calm_memory_accent_not_pushed_to_full_chroma():   # 고요한 기억에 쨍한 강조색이 튀지 않게 (eng-1.2)
    res = {"emotion": R("emotion", "warm_nostalgia"), "space": R("space", "rain_window"),
           "time": R("time", "night"), "quality": R("quality", "faded")}
    base = synthesize(res, KB0, None, None)["palette"][3]
    calm = synthesize(res, KB0, None, compute({"valence": 3, "arousal": 1}, EMO))["palette"][3]
    assert calm["lch"][1] < base["lch"][1] * 0.7
    assert calm["basis"]["adjust"][0] == "lightness"
