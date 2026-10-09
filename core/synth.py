"""core/synth.py — 결정론 LCh 합성 + 캐시 키.

역할별 입력 축 (eng-1.1):
  dominant    ← emotion.lch                          45%
  supporting  ← space.lch                            30%
  atmospheric ← 두 번째 사물 색  (OBJECT_SLOTS=2 기본. 1이면 time.lch, 단 시간 단서가 없으면 사물)  15%
  accent      ← 첫 번째 사물 색   (사물이 없으면 emotion.accent_lch)  10%
보정(순서대로):
  L' = L + l_pull·(Lm − L)          Lm = 네 기준색 명도 평균   (faded: 대비 압축 / vivid: 대비 확대)
  C' = c·C                                                    (faded: 채도 ↓ / vivid: 채도 ↑)
  h' = h + HARMONY·wrap(h_dom − h)  (dominant·사물 색 제외)     → 4색 조화. 사물 색은 그 사물 색 그대로 둔다
  강조색 대비: ΔE00(accent, dominant) < ACCENT_MIN_DE 이면 채도 → 명도 순으로 벌린다
  C'' = 색역 안 최대 채도(이분 탐색)                             → HEX
면적비는 상수. 모델에게 묻지 않는다.

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
ENGINE_VERSION = "eng-1.1"


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


def _separate_accent(acc: tuple, dom: tuple) -> tuple[tuple, list]:
    """강조색이 주조색과 ΔE00 ACCENT_MIN_DE 미만이면: ① 채도를 색역 끝까지 ② 명도를 주조색에서 멀어지는 쪽으로 3씩."""
    L, C, h = acc
    steps = []
    de = lambda l, c: delta_e_2000(lch2lab((l, min(c, _max_chroma(l, h)), h)), lch2lab(dom))
    if de(L, C) >= ACCENT_MIN_DE:
        return acc, steps
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


def synthesize(res: dict[str, Resolution], kb, objects: list | None = None) -> dict:
    """objects: core.objects.ObjectColor 목록 (없으면 eng-1.0 과 같은 축 구성 + 이름·대비 보정만)."""
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
        if role != "dominant" and axis != "object":
            h = (h + HARMONY * _wrap(h_dom - h)) % 360
        work[role] = [L, C, h]
    adjust = []
    acc, adjust = _separate_accent(tuple(work["accent"]), tuple(work["dominant"]))
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
        palette.append({"role": role, "hex": hx, "area_ratio": w,
                        "lch": [round(L, 2), round(Cc, 2), round(h, 2)], "color_name": name, "basis": basis})
    return {"palette": palette, "cache_key": cache_key(res, kb.version, objects)}


def cache_key(res: dict[str, Resolution], kb_version: str, objects: list | None = None) -> str:
    """원문이 아니라 '해석된 KB id + 사물(이름·등급) + KB·엔진 버전'의 해시 — 원문은 키에 남지 않는다.
    사물 이름도 넣는다: 등급이 같아도 표본에 표시되는 이름이 다르므로."""
    ids = {a: r.kb_id for a, r in sorted(res.items())}
    obj = [[o.name, *o.descriptor] for o in (objects or [])]
    blob = json.dumps([ids, obj, kb_version, ENGINE_VERSION, HARMONY, ACCENT_MIN_DE, OBJECT_SLOTS], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
