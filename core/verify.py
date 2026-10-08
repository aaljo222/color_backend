"""core/verify.py — 생성 그림이 팔레트를 지켰는지 숫자로 판정.

1) sRGB → CIELAB, 축소 샘플링  2) K-Means(k=4, n_init=10, random_state 고정)
3) 목표 4색 ↔ 군집 4개를 ΔE00 비용 행렬로 헝가리안 매칭  4) 역할별 ΔE00 · 면적비 오차 판정
기준값은 예시(DE_MAX=5, RATIO_MAX=0.05) — 사용자 테스트로 정할 설계 변수.
"""
from __future__ import annotations
import os
import numpy as np
from PIL import Image
from core.color import rgb2lab, lab2hex, hex2lab, delta_e_2000

DE_MAX = float(os.getenv("VERIFY_DE_MAX", "5.0"))
RATIO_MAX = float(os.getenv("VERIFY_RATIO_MAX", "0.05"))


def extract(img: Image.Image, k: int = 4, side: int = 160, seed: int = 0):
    from sklearn.cluster import KMeans
    im = img.convert("RGB")
    im.thumbnail((side, side))
    lab = rgb2lab(np.asarray(im, float) / 255.0).reshape(-1, 3)
    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(lab)
    ratios = np.bincount(km.labels_, minlength=k) / len(lab)
    return km.cluster_centers_, ratios


def verify(palette: list[dict], img: Image.Image) -> dict:
    from scipy.optimize import linear_sum_assignment
    cents, ratios = extract(img, k=len(palette))
    targets = [hex2lab(p["hex"]) for p in palette]
    cost = np.array([[delta_e_2000(t, c) for c in cents] for t in targets])
    r_idx, c_idx = linear_sum_assignment(cost)
    rows = []
    for i, j in zip(r_idx, c_idx):
        rows.append({"role": palette[i]["role"], "target": palette[i]["hex"], "got": lab2hex(cents[j]),
                     "de00": round(float(cost[i, j]), 2), "ratio_target": palette[i]["area_ratio"],
                     "ratio_got": round(float(ratios[j]), 3),
                     "dL": round(float(cents[j][0] - targets[i][0]), 2)})
    ok = all(x["de00"] <= DE_MAX and abs(x["ratio_got"] - x["ratio_target"]) <= RATIO_MAX for x in rows)
    return {"status": "PASS" if ok else "FAIL", "rows": rows,
            "max_de00": max(x["de00"] for x in rows),
            "max_ratio_err": round(max(abs(x["ratio_got"] - x["ratio_target"]) for x in rows), 3),
            "criteria": {"de00_max": DE_MAX, "ratio_err_max": RATIO_MAX}}


def feedback(result: dict) -> str:
    """FAIL 시 다음 생성 지시에 넣을 수정 문장 (evaluator → generator)."""
    msgs = []
    for r in result["rows"]:
        if r["de00"] > DE_MAX:
            msgs.append(f"{r['role']} 색을 {r['target']}에 더 가깝게(현재 {r['got']}, ΔE00 {r['de00']})")
        if abs(r["ratio_got"] - r["ratio_target"]) > RATIO_MAX:
            msgs.append(f"{r['role']} 면적을 {int(r['ratio_target']*100)}%에 맞추기(현재 {r['ratio_got']*100:.0f}%)")
    return "; ".join(msgs)
