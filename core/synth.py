"""core/synth.py — 결정론 LCh 합성 + 캐시 키.

역할별 입력 축(고정):  dominant←emotion.lch  supporting←space.lch  atmospheric←time.lch  accent←emotion.accent_lch
보정(순서대로):
  L' = L + l_pull·(Lm − L)          Lm = 네 기준색 명도 평균   (faded: 대비 압축 / vivid: 대비 확대)
  C' = c·C                                                    (faded: 채도 ↓ / vivid: 채도 ↑)
  h' = h + HARMONY·wrap(h_dom − h)  (dominant 제외)            → 4색 조화
  C'' = 색역 안 최대 채도(이분 탐색)                             → HEX
면적비는 상수. 모델에게 묻지 않는다.
"""
from __future__ import annotations
import hashlib, json, os
from core.color import lch_to_hex_clipped
from core.kb import Resolution

ROLES = (("dominant", 0.45), ("supporting", 0.30), ("atmospheric", 0.15), ("accent", 0.10))
HARMONY = float(os.getenv("HARMONY_PULL", "0.10"))
ENGINE_VERSION = "eng-1.0"


def _wrap(d: float) -> float:
    return ((d + 180) % 360) - 180


def synthesize(res: dict[str, Resolution], kb) -> dict:
    emo, spa, tim = kb.by_id[res["emotion"].kb_id], kb.by_id[res["space"].kb_id], kb.by_id[res["time"].kb_id]
    mod = kb.by_id[res["quality"].kb_id].get("modifiers", {"c": 1.0, "l_pull": 0.0})
    base = {"dominant": (emo["lch"], "emotion"), "supporting": (spa["lch"], "space"),
            "atmospheric": (tim["lch"], "time"), "accent": (emo.get("accent_lch", emo["lch"]), "emotion")}
    Lm = sum(v[0][0] for v in base.values()) / 4
    h_dom = base["dominant"][0][2]
    palette = []
    for role, w in ROLES:
        (L, C, h), axis = base[role]
        L = L + mod["l_pull"] * (Lm - L)
        C = C * mod["c"]
        if role != "dominant":
            h = (h + HARMONY * _wrap(h_dom - h)) % 360
        hx, Cc = lch_to_hex_clipped((L, C, h))
        r = res[axis]
        palette.append({
            "role": role, "hex": hx, "area_ratio": w,
            "lch": [round(L, 2), round(Cc, 2), round(h, 2)],
            "color_name": kb.by_id[r.kb_id]["name"],
            "basis": {"axis": axis, "kb_id": r.kb_id, "how": r.how, "score": r.score, "phrase": r.phrase},
        })
    return {"palette": palette, "cache_key": cache_key(res, kb.version)}


def cache_key(res: dict[str, Resolution], kb_version: str) -> str:
    """원문이 아니라 '해석된 KB id + KB 버전 + 엔진 버전' — 캐시에 개인정보가 남지 않는다."""
    ids = {a: r.kb_id for a, r in sorted(res.items())}
    blob = json.dumps([ids, kb_version, ENGINE_VERSION, HARMONY], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
