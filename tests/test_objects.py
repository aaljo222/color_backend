"""eng-1.1 사물 색 — 사물이 강조·분위기색으로 들어가는지, 결정론·대비·이름 규칙을 고정."""
from core.kb import KB, Resolution
from core.synth import synthesize, ACCENT_MIN_DE
from core.objects import resolve_objects
from core.color import hex2lab, delta_e_2000
from core.llm import Features, AxisFeature

R = lambda a, i, ph="", how="label": Resolution(a, ph, i, how, 1.0)
RES = {"emotion": R("emotion", "warm_nostalgia"), "space": R("space", "grandma_house"),
       "time": R("time", "afternoon"), "quality": R("quality", "cherished")}


def test_no_objects_keeps_eng10_colors_but_fixes_name():
    p = synthesize(RES, KB())["palette"]
    assert [x["hex"] for x in p] == ["#F0C3AB", "#B48865", "#EDDBBB", "#E47570"]   # 스크린샷 eng-1.0 과 같은 색
    assert p[0]["color_name"] != p[3]["color_name"]                                # 'Peach Cream' 중복 해소


def test_objects_take_accent_and_atmospheric():
    objs = resolve_objects([{"name": "수박"}, {"name": "옥수수"}], learn=False)
    assert [o.how for o in objs] == ["lexicon", "lexicon"]
    p = synthesize(RES, KB(), objs)["palette"]
    assert p[3]["color_name"] == "수박" and p[3]["basis"]["axis"] == "object"
    assert p[2]["color_name"] == "옥수수"
    assert [x["area_ratio"] for x in p] == [0.45, 0.30, 0.15, 0.10]


def test_lexicon_wins_over_llm_grade():                       # 같은 낱말 = 같은 색 (LLM 이 흔들려도)
    a = resolve_objects([{"name": "수박", "hue": "파랑", "lightness": 2, "chroma": 1}], learn=False)
    b = resolve_objects([{"name": "수박"}], learn=False)
    assert a[0].lch == b[0].lch and a[0].how == "lexicon"


def test_unknown_object_needs_valid_grade():                 # 검증 게이트: 사전에도 없고 등급도 틀리면 버림
    assert resolve_objects([{"name": "외계과일", "hue": "형광", "lightness": 12, "chroma": 9}], lexicon={}, learn=False) == []
    ok = resolve_objects([{"name": "외계과일", "hue": "보라", "lightness": 4, "chroma": 4}], lexicon={}, learn=False)
    assert ok and ok[0].how == "grade"


def test_deterministic_and_cache_key_changes_with_objects():
    kb = KB()
    o = resolve_objects([{"name": "수박"}], learn=False)
    keys = {synthesize(RES, kb, o)["cache_key"] for _ in range(20)}
    assert len(keys) == 1
    assert synthesize(RES, kb)["cache_key"] not in keys


def test_accent_contrast_rule():                             # 주조색과 비슷한 사물이면 ΔE00 로 벌린다
    kb = KB()
    o = resolve_objects([{"name": "복숭아", "hue": "주황", "lightness": 8, "chroma": 2}], lexicon={}, learn=False)
    p = synthesize(RES, kb, o)["palette"]
    de = delta_e_2000(hex2lab(p[0]["hex"]), hex2lab(p[3]["hex"]))
    assert de >= ACCENT_MIN_DE - 0.5 and "adjust" in p[3]["basis"]


def test_legacy_string_objects_accepted():
    f = Features(emotion=AxisFeature(), time=AxisFeature(), space=AxisFeature(), memory_quality=AxisFeature(),
                 objects=["수박", "옥수수"])
    assert [o.name for o in f.objects] == ["수박", "옥수수"]


def test_log_keys_match_generation_logs_columns():          # eng-1.1 배포 때 'objects' 키로 저장 실패한 회귀 방지
    import re, pathlib
    from core.pipeline import analyze
    from core.store import LOG_COLUMNS
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath("sql", "schema.sql").read_text(encoding="utf-8")
    body = re.search(r"create table if not exists public\.generation_logs \((.*?)\);", sql, re.S).group(1)
    cols = {ln.split()[0] for part in body.split("\n") for ln in part.split(",") if ln.strip() and not ln.strip().startswith("--")}
    assert LOG_COLUMNS <= cols | {"id"}
    r = analyze("여름방학 할머니 댁 평상에서 먹던 수박과 옥수수의 기억")
    keys = {"specimen_id", "kb_version", "created_at"} | set(r["_log"].keys())
    assert keys <= LOG_COLUMNS, keys - LOG_COLUMNS
