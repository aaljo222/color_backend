"""core/synth.py — 결정론 LCh 합성 + 캐시 키.

역할별 입력 축 (eng-1.2):
  dominant    ← emotion.lch                          45%
  supporting  ← space.lch                            30%
  atmospheric ← 두 번째 사물 색  (OBJECT_SLOTS=2 기본. 1이면 time.lch, 단 시간 단서가 없으면 사물)  15%
  accent      ← 첫 번째 사물 색   (사물이 없으면 emotion.accent_lch)  10%
보정(순서대로):
  L' = L + l_pull·(Lm − L)          Lm = 네 기준색 명도 평균   (faded: 대비 압축 / vivid: 대비 확대)
  C' = c·C                                                    (faded: 채도 ↓ / vivid: 채도 ↑)
  정서 보정 (eng-1.2, core/affect.py, 사물 색 제외):
    C' ×= 1 + 0.20·(각성 − 감정 기준 각성)      L' += 3·(쾌 − 감정 기준 쾌)      → 색채 심리: 채도=각성, 명도=쾌
  h' = h + HARMONY·wrap(h_dom − h)  (dominant·사물 색 제외)     → 4색 조화. 사물 색은 그 사물 색 그대로 둔다
  강조색 대비: ΔE00(accent, dominant) < ACCENT_MIN_DE 이면 채도 → 명도 순으로 벌린다 (각성을 낮춘 기억은 명도 → 채도)
  C'' = 색역 안 최대 채도(이분 탐색)                             → HEX
면적비는 상수. 모델에게 묻지 않는다.

eng-1.1 → 1.2 변경
  - LLM 이 기억의 쾌·각성 등급(1~5)을 낸다. 감정 기준점과의 차이만큼 채도·명도를 정해진 표로 보정한다
    (같은 '그리움'이라도 여름 대낮의 생생한 기억은 선명하게, 비 오는 밤의 기억은 가라앉게)
  - 등급이 없으면 보정 0 → eng-1.1 과 같은 색

eng-1.0 → 1.1 변경
  - 기억 속 사물(수박·옥수수…)이 강조색으로 들어간다 (core/objects.py, 등급 → 표 → 색)
  - 사물 색에는 조화 당김을 걸지 않는다 (수박이 주조색 쪽으로 끌려가 탁해지지 않게)
  - 강조색이 주조색과 너무 비슷하면 측정(ΔE00)으로 벌린다
  - 주조색·강조색 이름 중복 수정 (사물이면 사물 이름, 아니면 '… · 강조')
"""
from __future__ import annotations
import hashlib, json, os
from core.color import lch_to_hex_clipped, lch2lab, delta_e_2000, in_gamut
from core.kb import Resolution

ROLES = (("dominant", 0.45), ("supporting", 0.30), ("atmospheric", 0.15), ("accent", 0.10))
HARMONY = float(os.getenv("HARMONY_PULL", "0.10"))
ACCENT_MIN_DE = float(os.getenv("ACCENT_MIN_DE", "20"))
OBJECT_SLOTS = int(os.getenv("OBJECT_SLOTS", "2"))      # 사물이 차지할 수 있는 역할 수: 1=강조색만, 2=강조색+분위기색
ENGINE_VERSION = "eng-1.2"


def _wrap(d: float) -> float:
    return ((d + 180) % 360) - 180


def _max_chroma(L: float, h: float, cap: float = 150.0) -> float:
    lo, hi = 0.0, cap
    for _ in range(40):
        mid = (lo + hi) / 2
        if in_gamut(lch2lab((L, mid, h))):
            lo = mid
        else:
            hi = mid
    return lo


def _separate_accent(acc: tuple, dom: tuple, calm: bool = False) -> tuple[tuple, list]:
    """강조색이 주조색과 ΔE00 ACCENT_MIN_DE 미만이면: ① 채도를 색역 끝까지 ② 명도를 주조색에서 멀어지는 쪽으로 3씩.
    calm=True(정서 보정으로 각성을 낮춘 기억, eng-1.2): 채도는 그대로 두고 명도로 먼저 벌린다 → 그래도 모자라면 채도."""
    L, C, h = acc
    steps = []
    de = lambda l, c: delta_e_2000(lch2lab((l, min(c, _max_chroma(l, h)), h)), lch2lab(dom))
    if de(L, C) >= ACCENT_MIN_DE:
        return acc, steps
    direction = -1 if (L >= dom[0] or dom[0] > 60) else 1
    if calm:
        for _ in range(10):
            if de(L, C) >= ACCENT_MIN_DE:
                return (L, C, h), steps
            L = max(15.0, min(90.0, L + 3 * direction)); steps.append("lightness")
    cmax = _max_chroma(L, h)
    if cmax > C:
        C = cmax; steps.append("chroma_up")
    direction = -1 if L >= dom[0] else 1
    if dom[0] > 60:
        direction = -1                                      # 밝은 주조색이면 강조색은 어둡게
    for _ in range(10):
        if de(L, C) >= ACCENT_MIN_DE:
            break
        L = max(15.0, min(90.0, L + 3 * direction)); C = max(C, _max_chroma(L, h) * 0.9)
        steps.append("lightness")
    return (L, C, h), steps


def synthesize(res: dict[str, Resolution], kb, objects: list | None = None, affect=None) -> dict:
    """objects: core.objects.ObjectColor 목록 (없으면 eng-1.0 과 같은 축 구성 + 이름·대비 보정만).
    affect : core.affect.AffectAdjust (없으면 정서 보정 0)."""
    objects = list(objects or [])
    emo, spa, tim = kb.by_id[res["emotion"].kb_id], kb.by_id[res["space"].kb_id], kb.by_id[res["time"].kb_id]
    mod = kb.by_id[res["quality"].kb_id].get("modifiers", {"c": 1.0, "l_pull": 0.0})
    base = {"dominant": (emo["lch"], "emotion", emo["name"]),
            "supporting": (spa["lch"], "space", spa["name"]),
            "atmospheric": (tim["lch"], "time", tim["name"]),
            "accent": (emo.get("accent_lch", emo["lch"]), "emotion", f'{emo["name"]} · 강조')}
    obj_for = {}
    if objects:
        obj_for["accent"] = objects[0]
        base["accent"] = (list(objects[0].lch), "object", objects[0].name)
        if len(objects) > 1 and (OBJECT_SLOTS >= 2 or res["time"].how == "fallback"):   # 두 번째 사물 → 분위기색
            obj_for["atmospheric"] = objects[1]
            base["atmospheric"] = (list(objects[1].lch), "object", objects[1].name)
    Lm = sum(v[0][0] for v in base.values()) / 4
    h_dom = base["dominant"][0][2]
    work = {}
    for role, _ in ROLES:
        (L, C, h), axis, name = base[role]
        L = L + mod["l_pull"] * (Lm - L)
        C = C * mod["c"]
        if affect is not None and axis != "object":           # 정서 보정: 사물 고유색은 건드리지 않는다
            C = C * affect.c_mult
            L = max(15.0, min(95.0, L + affect.dL))
        if role != "dominant" and axis != "object":
            h = (h + HARMONY * _wrap(h_dom - h)) % 360
        work[role] = [L, C, h]
    adjust = []
    calm = affect is not None and affect.c_mult < 1
    acc, adjust = _separate_accent(tuple(work["accent"]), tuple(work["dominant"]), calm)
    work["accent"] = list(acc)
    palette = []
    for role, w in ROLES:
        (_, axis, name) = base[role]
        L, C, h = work[role]
        hx, Cc = lch_to_hex_clipped((L, C, h))
        if axis == "object":
            o = obj_for[role]
            basis = {"axis": "object", "kb_id": None, "how": o.how, "score": 1.0, "phrase": o.name,
                     "grade": list(o.descriptor)}
        else:
            r = res[axis]
            basis = {"axis": axis, "kb_id": r.kb_id, "how": r.how, "score": r.score, "phrase": r.phrase}
        if role == "accent" and adjust:
            basis["adjust"] = adjust
        if affect is not None and axis != "object" and (affect.c_mult != 1 or affect.dL):
            basis["affect"] = affect.as_basis()
        palette.append({"role": role, "hex": hx, "area_ratio": w,
                        "lch": [round(L, 2), round(Cc, 2), round(h, 2)], "color_name": name, "basis": basis})
    return {"palette": palette, "cache_key": cache_key(res, kb.version, objects, affect),
            "affect": affect.as_basis() if affect is not None else None}


def cache_key(res: dict[str, Resolution], kb_version: str, objects: list | None = None, affect=None) -> str:
    """원문이 아니라 '해석된 KB id + 사물(이름·등급) + KB·엔진 버전'의 해시 — 원문은 키에 남지 않는다.
    사물 이름도 넣는다: 등급이 같아도 표본에 표시되는 이름이 다르므로."""
    ids = {a: r.kb_id for a, r in sorted(res.items())}
    obj = [[o.name, *o.descriptor] for o in (objects or [])]
    aff = [affect.valence, affect.arousal, affect.c_mult, affect.dL] if affect is not None else None
    blob = json.dumps([ids, obj, aff, kb_version, ENGINE_VERSION, HARMONY, ACCENT_MIN_DE, OBJECT_SLOTS], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
