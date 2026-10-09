"""core/affect.py — 정서 등급(쾌·각성) → 명도·채도 보정 (eng-1.2).

근거 (색채 심리):
  - Wilms & Oberfeld (2018): 각성에 가장 큰 영향을 주는 것은 채도, 쾌(좋은 느낌)는 명도가 올릴수록 높아진다.
  - Valdez & Mehrabian (1994) 표준화 회귀식:  Pleasure = .69·명도 + .22·채도,  Arousal = −.31·명도 + .60·채도
  → 두 연구가 일치하는 것만 쓴다: 각성 등급 → 채도,  쾌 등급 → 명도.  색상(hue)은 건드리지 않는다.
  ※ 명도→각성은 쓰지 않는다: Valdez 는 U자(−.31), Wilms 는 고채도에서만 +, Zielinski(2016)는 효과 없음 — 연구끼리 엇갈림.
  ※ 한계: 밝은 색(L 80 이상)은 화면(sRGB)이 낼 수 있는 채도 천장이 낮아, 각성을 올려도 채도가 덜 오른다(색역 클립).

LLM 은 등급 두 개(1~5)만 낸다. 숫자 보정량은 아래 표가 정한다 (결정론).
기준점: 감정 KB 항목마다 그 기준색이 이미 담고 있는 정서 등급(affect)이 있다.
       보정은 '그 감정의 평균에서 이 기억이 얼마나 벗어났나'(차이)만 반영한다.
       예) 그리움(기준 각성 2) 인데 이 기억은 각성 4 → +2 칸 → 채도 ×1.40
"""
from __future__ import annotations
import os
from dataclasses import dataclass

AROUSAL_C_STEP = float(os.getenv("AROUSAL_C_STEP", "0.20"))   # 각성 1칸 = 채도 ±20%
VALENCE_L_STEP = float(os.getenv("VALENCE_L_STEP", "3.0"))    # 쾌 1칸 = 명도 ±3 (CIE L)
C_MULT_RANGE = (0.5, 1.8)
NEUTRAL = (3, 3)


@dataclass(frozen=True)
class AffectAdjust:
    valence: int            # 이 기억의 쾌 등급 1~5
    arousal: int            # 이 기억의 각성 등급 1~5
    base: tuple             # 감정 기준점 (쾌, 각성)
    c_mult: float           # 채도 배율
    dL: float               # 명도 변화량
    how: str                # model | stub | none

    def as_basis(self) -> dict:
        return {"valence": self.valence, "arousal": self.arousal, "base": list(self.base),
                "chroma_pct": round((self.c_mult - 1) * 100), "dL": round(self.dL, 1)}


def _grade(v, default: int) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= 5 else default          # 범위 밖이면 버린다 (검증 게이트)


def compute(affect, emotion_item: dict) -> AffectAdjust:
    """affect: {'valence','arousal','how'} 또는 None. 없으면 감정 기준점 그대로 = 보정 0 (eng-1.1 과 같은 색)."""
    base = tuple(emotion_item.get("affect") or NEUTRAL)
    if hasattr(affect, "model_dump"):
        affect = affect.model_dump()
    affect = affect or {}
    v = _grade(affect.get("valence"), base[0])
    a = _grade(affect.get("arousal"), base[1])
    how = affect.get("how") or ("model" if affect else "none")
    lo, hi = C_MULT_RANGE
    c_mult = max(lo, min(hi, 1 + AROUSAL_C_STEP * (a - base[1])))
    dL = VALENCE_L_STEP * (v - base[0])
    return AffectAdjust(valence=v, arousal=a, base=base, c_mult=round(c_mult, 3), dL=dL, how=how)


# ── 키 없이 쓰는 stub 추정 (개발·테스트용, 품질 낮음) ─────────────────────
_UP_A = ("생생", "신나", "뛰", "여름", "시원", "햇빛", "쨍", "환호", "축제", "달리", "웃음")
_DN_A = ("조용", "잔잔", "고요", "희미", "흐릿", "가만", "적막", "비 오", "빗소리")
_UP_V = ("행복", "즐거", "좋았", "웃", "따뜻", "신나")
_DN_V = ("슬프", "외로", "아프", "울", "쓸쓸", "그리워")


def stub_affect(text: str, emotion_item: dict) -> dict:
    v, a = emotion_item.get("affect") or NEUTRAL
    a += (any(w in text for w in _UP_A)) - (any(w in text for w in _DN_A))
    v += (any(w in text for w in _UP_V)) - (any(w in text for w in _DN_V))
    return {"valence": max(1, min(5, v)), "arousal": max(1, min(5, a)), "how": "stub"}
