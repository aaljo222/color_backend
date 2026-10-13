"""core/candidates.py — 그리기 전 후보 색 (eng-2.6): 그림 뒤 4색은 반드시 이 후보 HEX 중에서 나온다.

왜 (2026-10-13 팀장 요구 9번)
  eng-2.0~2.5 는 그림을 그린 뒤 픽셀에서 4색을 '쟀다'. 그래서 4색이 문장 분석에서 나온 색과 아무 관계가 없을 수 있었다
  (예: 수박 껍질 문장 → 탁한 보라 #847… 가 주조색). 문장 → 색의 근거 사슬이 그림에서 끊긴 것이다.
  eng-2.6 은 문장 분석이 '후보 색'을 먼저 정하고, 화가는 그 후보로 그리고, 그림 뒤에는 후보 중에서 4색을 고른다(core/image_first 스냅).

후보는 어디서 오나 (모두 결정론 — LLM 은 등급·라벨만 냈고, 숫자 색은 여기서 계산)
  emotion  감정 KB 기준색 (정서 보정 후) + 감정 강조색          ← 감정 가중치를 받는다
  space    장소 KB 기준색 (기본 톤으로 떨어졌으면 가중치를 낮춘다)
  time     시간 KB 기준색 (같음)
  object   사물 색 (확정 색표 → 사전 → 코퍼스 → 모델 등급)
  word     문장에 직접 쓴 색 말 ("모스 그린", "붉은", "노란") — 사람이 색을 말했으면 가장 강한 단서
  shade    위 색들의 밝은·짙은 형제색 — 작은 붓질용. 그림이 다채로워져도 4색은 여전히 후보 안에 있게 하려는 자리

감정 가중치 (2026-10-13 이재오 제안)
  감정 강도 = (|쾌−3| + |각성−3|) / 4   (0 = 담담, 1 = 아주 강함)
  감정 색 가중치 = 1 + EMO_GAIN × (0.5 + 강도)        → 감정이 강할수록 넓은 면을 받는다
  가중치 상위 LARGE_N 색 = '넓게'(면적 목표 합 LARGE_SHARE), 나머지 = '작게'(붓질·튐)
  화가가 이 배분을 따르면, 그림 뒤 면적 순서로 고른 4색이 자연히 감정 색 위주가 된다.
"""
from __future__ import annotations
import os, re
from dataclasses import dataclass, field

from core.color import lch2lab, lab2lch, delta_e_2000, lch_to_hex_clipped, hex2lab

EMO_GAIN = float(os.getenv("CAND_EMO_GAIN", "1.5"))
WORD_W = float(os.getenv("CAND_WORD_W", "1.6"))
OBJECT_W = float(os.getenv("CAND_OBJECT_W", "1.0"))
AXIS_W = float(os.getenv("CAND_AXIS_W", "1.0"))
FALLBACK_W = float(os.getenv("CAND_FALLBACK_W", "0.35"))     # 기본 톤으로 떨어진 축 — 문장 근거가 약하다
SHADE_W = float(os.getenv("CAND_SHADE_W", "0.15"))
LARGE_N = int(os.getenv("CAND_LARGE_N", "4"))          # 넓게 칠할 색 수 = 칩 수 → 화가가 따르면 4색이 자연히 이 넓은 색들로 정해진다
LARGE_SHARE = float(os.getenv("CAND_LARGE_SHARE", "0.80"))
MERGE_DE = float(os.getenv("CAND_MERGE_DE", "7"))            # 이보다 가까운 두 후보는 하나로 (가중치는 큰 쪽)
MAX_CANDS = int(os.getenv("CAND_MAX", "12"))
CAND_VERSION = "cand-1"

# 문장 속 색 말 → 등급 (색상 계열·밝기 1~9·채도 0~5). 설계값 — 코퍼스 팀 검토 대상. 긴 말 먼저 찾는다.
COLOR_TERMS = {
    "모스그린": ("초록", 4, 2), "올리브": ("연두", 4, 2), "카키": ("연두", 4, 1), "에메랄드": ("청록", 5, 4), "민트": ("청록", 8, 2),
    "청록": ("청록", 5, 3), "연두": ("연두", 7, 3), "초록": ("초록", 4, 3), "녹색": ("초록", 4, 3), "푸른": ("파랑", 4, 3),
    "파란": ("파랑", 4, 4), "파랑": ("파랑", 4, 4), "하늘색": ("하늘", 8, 2), "남색": ("남색", 2, 3), "보라": ("보라", 4, 3),
    "자주": ("자주", 3, 3), "와인": ("자주", 2, 3), "분홍": ("분홍", 7, 3), "핑크": ("분홍", 7, 3), "붉은": ("빨강", 4, 4),
    "빨간": ("빨강", 4, 5), "빨강": ("빨강", 4, 5), "주황": ("주황", 6, 4), "오렌지": ("주황", 6, 4), "살구색": ("주황", 8, 2),
    "노란": ("노랑", 7, 4), "노랑": ("노랑", 7, 4), "금빛": ("노랑", 6, 4), "황금빛": ("노랑", 6, 4), "크림색": ("노랑", 9, 1),
    "베이지": ("주황", 8, 1), "갈색": ("주황", 3, 2), "밤색": ("주황", 2, 2), "회색": ("무채", 5, 0), "잿빛": ("무채", 5, 0),
    "은빛": ("무채", 7, 0), "하얀": ("무채", 9, 0), "흰": ("무채", 9, 0), "검은": ("무채", 1, 0), "까만": ("무채", 1, 0),
}
# 색 말 바로 앞의 수식어 → (밝기 칸, 채도 칸)
TERM_MODS = (("연한", (2, -1)), ("옅은", (2, -1)), ("진한", (-1, 1)), ("짙은", (-2, 0)), ("선명한", (0, 1)),
             ("탁한", (0, -1)), ("바랜", (1, -2)), ("흐린", (1, -1)), ("어두운", (-2, 0)), ("밝은", (1, 0)))
GROUP_WORDS = {"emotion": "감정", "space": "장소", "time": "시간", "object": "사물", "word": "문장 속 색 말", "shade": "곁색"}


@dataclass
class Cand:
    cid: str
    lch: tuple
    hex: str
    origin: str            # emotion | space | time | object | word | shade
    label: str             # 화면에 보일 이름 (사물 이름은 화가 지시문에 넣지 않는다 — eng-2.5)
    descriptor: tuple      # 색 말로 바꿀 등급 (hue, L, C)
    weight: float
    tier: str = "small"
    area: float = 0.0
    merged: list = field(default_factory=list)

    @property
    def lab(self):
        return lch2lab(self.lch)

    def public(self) -> dict:
        return {"id": self.cid, "hex": self.hex, "lch": [round(float(x), 2) for x in self.lch], "origin": self.origin,
                "label": self.label, "weight": round(self.weight, 3), "tier": self.tier, "area_target": round(self.area, 3),
                **({"merged": self.merged} if self.merged else {})}


def intensity(affect) -> float:
    if affect is None:
        return 0.0
    return (abs(affect.valence - 3) + abs(affect.arousal - 3)) / 4


def find_color_terms(text: str, limit: int = 3) -> list[tuple[str, tuple]]:
    """문장에 직접 쓴 색 말. (말, 등급). 띄어쓰기 무시('모스 그린' = '모스그린'). 겹치면 긴 말."""
    from oracle import color_abstraction as ca
    s = re.sub(r"\s+", "", text or "")
    found, taken = [], []
    for w in sorted(COLOR_TERMS, key=lambda w: -len(w)):
        for m in re.finditer(re.escape(w), s):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            if w == "흰" and s[b:b + 1] not in ("색", "빛", "눈", "옷"):    # '흰'은 '흰색·흰빛·흰 눈·흰 옷'일 때만 (흰머리·흰소리 제외)
                continue
            d = dict(zip(("hue", "lightness", "chroma"), COLOR_TERMS[w]))
            before = s[max(0, a - 4):a]
            for mod, (dl, dc) in TERM_MODS:
                if before.endswith(mod):
                    d = ca.shift(d, dl, dc)
                    break
            taken.append((a, b))
            found.append((a, w, (d["hue"], d["lightness"], d["chroma"])))
    return [(w, d) for _, w, d in sorted(found)[:limit]]


def _from_descriptor(d: tuple) -> tuple:
    from core.objects import descriptor_to_lch
    return descriptor_to_lch({"hue": d[0], "lightness": d[1], "chroma": d[2]})


def _descriptor_of(lch) -> tuple:
    from core.objects import hex_to_descriptor
    hx, _ = lch_to_hex_clipped(lch)
    d = hex_to_descriptor(hx)
    return (d["hue"], d["lightness"], d["chroma"])


def build(res: dict, kb, objects: list, affect, base_palette: list, masked: str) -> list[Cand]:
    """후보 색 목록 (가중치 내림차순, tier·area 채움). base_palette = eng-1.2 계산 팔레트 (정서 보정이 들어간 축 색)."""
    by_role = {p["role"]: p for p in base_palette}
    w_emo = 1 + EMO_GAIN * (0.5 + intensity(affect))
    raw: list[Cand] = []

    def add(origin, lch, label, w, desc=None):
        hx, Cc = lch_to_hex_clipped(tuple(lch))
        lch = (float(lch[0]), float(Cc), float(lch[2]))
        raw.append(Cand(f"{origin}:{len(raw)}", lch, hx, origin, label, desc or _descriptor_of(lch), w))

    # 축 색 — 계산 팔레트에서 축 기준인 칸만 (정서 보정·조화 보정이 이미 들어 있다)
    for p in base_palette:
        b = p.get("basis") or {}
        ax = b.get("axis")
        if ax == "emotion":
            add("emotion", p["lch"], p.get("color_name", "감정"), w_emo if p["role"] == "dominant" else 0.5 * w_emo)
        elif ax in ("space", "time"):
            add(ax, p["lch"], p.get("color_name", ax), FALLBACK_W if b.get("how") == "fallback" else AXIS_W)
    emo = kb.by_id[res["emotion"].kb_id]
    if not any(c.origin == "emotion" and c.weight < w_emo for c in raw) and emo.get("accent_lch"):
        add("emotion", emo["accent_lch"], f"{emo.get('name_ko') or emo['name']} · 강조", 0.5 * w_emo)
    for i, o in enumerate(objects or []):
        add("object", o.lch, o.name, OBJECT_W * (1.1 if i == 0 else 1.0), tuple(o.descriptor))
    for w, d in find_color_terms(masked):
        add("word", _from_descriptor(d), w, WORD_W, d)
    # 같은 색 합치기 — 가중치 큰 쪽이 남고, 합쳐진 출처를 기록
    raw.sort(key=lambda c: -c.weight)
    cands: list[Cand] = []
    for c in raw:
        twin = next((k for k in cands if delta_e_2000(k.lab, c.lab) < MERGE_DE), None)
        if twin is None:
            cands.append(c)
        else:
            twin.weight += 0.5 * c.weight                   # 두 근거가 같은 색을 가리키면 그 색이 더 넓어진다
            twin.merged.append(f"{GROUP_WORDS[c.origin]}:{c.label}")
    cands.sort(key=lambda c: -c.weight)
    # 곁색 — 상위 4색의 밝은·짙은 형제 (작은 붓질의 다양함을 후보 안에 둔다)
    for c in list(cands[:4]):
        L, C, h = c.lch
        for dL, k, tag in ((14, 0.7, "밝은"), (-14, 1.1, "짙은")):
            lch = (max(12.0, min(96.0, L + dL)), C * k, h)
            lab = lch2lab(lch)
            if all(delta_e_2000(lab, x.lab) >= MERGE_DE for x in cands):
                add("shade", lch, f"{tag} {c.label}", SHADE_W)
                cands.append(raw[-1])
    cands = sorted(cands, key=lambda c: -c.weight)[:MAX_CANDS]
    for i, c in enumerate(cands):
        c.cid = f"c{i + 1}"
    large, small = cands[:LARGE_N], cands[LARGE_N:]
    lw, sw = sum(c.weight for c in large) or 1, sum(c.weight for c in small) or 1
    for c in large:
        c.tier, c.area = "large", LARGE_SHARE * c.weight / lw
    for c in small:
        c.tier, c.area = "small", (1 - LARGE_SHARE) * c.weight / sw
    if not small:
        for c in large:
            c.area = c.weight / lw
    return cands


def prompt_lines(cands: list[Cand], with_hex: bool = True) -> list[str]:
    """화가 지시문 줄. 사물 이름은 넣지 않는다 (eng-2.5 형태 누출) — 출처는 '사물의 색' 처럼 갈래만."""
    from core.image_first import color_words
    out = ["쓸 색 (이 목록 밖의 새 색은 만들지 않는다. 젖은 물감이 섞이며 생기는 중간색은 괜찮다):"]
    for c in cands:
        src = GROUP_WORDS[c.origin] if c.origin != "object" else "기억 속 사물의 색"
        hx = f" {c.hex}" if with_hex else ""
        size = f"넓게 — 화면의 약 {round(c.area * 100)}%" if c.tier == "large" else "작게 — 짧은 붓질·물감 튐으로만"
        out.append(f"- {color_words(c.descriptor)}{hx} ({src}) · {size}")
    return out
