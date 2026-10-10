"""core/astral_palette.py — Astral 사주 4색에 보완색 4개와 무채색 4단을 붙여 8색(+무채) 팔레트를 만든다.

왜 (2026-10-10 팀 피드백, 김외진)
  · 조각보는 채도·명도 차이가 없는 색들이 뽑혔을 때 뭉쳐 놓으면 세련돼 보이지 않는다
  · 고유색 4개 + 보완색 4개 = 8색으로 그리면 풍성해진다. 칩도 고유색 4 / 보완색 4 로 따로
  · 조각 사이 선과 중간중간 조각을 무채색(흰·회·검)으로 명도를 바꿔 섞으면 색 차이가 작은 것을 상쇄한다
원칙
  · Astral 이 계산한 4색 HEX 는 바꾸지 않는다 (사주 계산값·색은 Astral 엔진이 정한다)
  · 보완색은 계산기가 정한다 (LLM 없음, 결정론): OKLCH 에서 색상 +180°, 명도는 원색에서 멀어지게, 채도는 범위 안으로
  · 8색 사이 ΔE00 이 MIN_DE 보다 작으면 보완색의 명도를 한 칸씩 더 벌린다 (원색은 그대로)
"""
from __future__ import annotations

from core.color import delta_e_2000, hex2lab
from oracle import color_oracle as co

ROLES = ("고유색", "재능색", "관계색", "균형색")
L_SHIFT_DARK, L_SHIFT_LIGHT = 0.26, 0.22      # 밝은 원색 → 보완색은 어둡게 / 어두운 원색 → 밝게
L_MIN, L_MAX = 0.30, 0.90
C_MIN, C_MAX = 0.05, 0.13
MIN_DE = 12.0                                  # 8색끼리 이보다 가까우면 보완색 명도를 더 벌린다
NEUTRALS = [                                   # 무채색 4단 (조각 사이 선 + 사이사이 조각)
    {"key": "white", "name": "지백", "hex": "#F3F0E9"},
    {"key": "light", "name": "연회색", "hex": "#CDCAC4"},
    {"key": "mid", "name": "먹회색", "hex": "#7E7B76"},
    {"key": "ink", "name": "먹색", "hex": "#2E2C2A"},
]
_HUE_NAMES = [(8, "분홍"), (27, "빨강"), (55, "주황"), (95, "노랑"), (125, "연두"), (150, "초록"), (190, "청록"),
              (230, "하늘색"), (260, "파랑"), (272, "남색"), (305, "보라"), (340, "자주")]


def _hue_name(h: float) -> str:
    return min(_HUE_NAMES, key=lambda x: min(abs(h - x[0]), 360 - abs(h - x[0])))[1]


def color_name(L: float, C: float, h: float) -> str:
    """OKLCH → 짧은 색 이름 (예: 짙은 청록, 부드러운 하늘색)."""
    if C < 0.03:
        return "흰빛 회색" if L >= 0.85 else "회색" if L >= 0.45 else "먹빛 회색"
    tone = "아주 연한 " if L >= 0.86 else "밝은 " if L >= 0.74 else "" if L >= 0.52 else "짙은 "
    sat = "부드러운 " if C < 0.08 else "" if C < 0.12 else "선명한 "
    hue = _hue_name(h)
    if tone == "짙은 " and hue == "하늘색":                       # '짙은 하늘색'은 어색하다 → 파랑 쪽 이름
        hue = "파랑"
    return f"{sat}{tone}{hue}".strip()


def _ok(hex_: str) -> tuple[float, float, float]:
    o = co.hex2oklch(hex_)
    return o["L"], o["C"], (o["H"] or 0.0)


def complement(hex_: str, extra: int = 0) -> dict:
    """보완색 1개. extra = 명도를 더 벌린 횟수 (겹침 해소용)."""
    L, C, H = _ok(hex_)
    h2 = (H + 180.0) % 360.0
    dark = L >= 0.62
    L2 = L - (L_SHIFT_DARK + 0.06 * extra) if dark else L + (L_SHIFT_LIGHT + 0.06 * extra)
    L2 = min(L_MAX, max(L_MIN, L2))
    C2 = min(C_MAX, max(C_MIN, C * 0.9))
    hx = co.oklch2hex(L2, C2, h2)["hex"].upper()
    L3, C3, h3 = _ok(hx)                                          # 색역 매핑 뒤 실제 값
    return {"hex": hx, "oklch": [round(L3, 4), round(C3, 4), round(h3, 2)], "name": color_name(L3, C3, h3)}


def build(colors: list[dict]) -> dict:
    """Astral report['colors'] (역할 4개) → {base, complement, neutrals, min_de00}. 결정론."""
    base = [c for r in ROLES for c in colors if c["role"] == r]
    labs = [hex2lab(c["hex"]) for c in base]
    comps, extras = [], [0, 0, 0, 0]
    for i, c in enumerate(base):
        for _ in range(4):
            cand = complement(c["hex"], extras[i])
            lab = hex2lab(cand["hex"])
            others = labs + [hex2lab(x["hex"]) for x in comps]
            if min(delta_e_2000(lab, o) for o in others) >= MIN_DE or extras[i] >= 3:
                break
            extras[i] += 1
        comps.append({"role": f"{c['role']} 보완", "of": c["role"], **cand})
    all_hex = [c["hex"] for c in base] + [c["hex"] for c in comps]
    min_de = min(delta_e_2000(hex2lab(a), hex2lab(b)) for i, a in enumerate(all_hex) for b in all_hex[i + 1:])
    return {"base": [{"role": c["role"], "name": c["name"], "hex": c["hex"].upper(), "basis": c.get("basis")} for c in base],
            "complement": comps, "neutrals": NEUTRALS, "min_de00": round(min_de, 1),
            "rule": "보완색 = OKLCH 색상 +180°, 명도는 원색에서 멀어지게, 채도 0.05~0.13 · 8색 ΔE00 ≥ 12 목표"}
