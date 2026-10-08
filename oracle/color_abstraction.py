# -*- coding: utf-8 -*-
"""색채 추상화 계층 — 파이썬이 결정론으로 처리하는 부분 전부.

LLM은 숫자를 내지 않는다. LLM이 내는 것은 '등급'뿐이다:
    hue(색상 계열 13개) · lightness(밝기 1~9) · chroma(채도 0~5)
등급 → OKLCH 변환은 아래 고정 표로 한다. 그래서
  - 같은 등급이면 항상 같은 OKLCH·HEX
  - LLM이 미세하게 흔들려도 등급이 같으면 결과는 같다 (연속값 격자보다 훨씬 굵은 칸)

이 파일이 하는 일
  normalize()        문장 정규화 (재활용 키)
  parse_rules()      규칙으로 풀리는 문장: HEX, OKLCH 수치, 브랜드 단계(teal 600, 한 단계 진하게, hover)
  parse_modifiers()  수식어: 진하게·연하게·선명하게·탁하게 (등급을 한 칸씩 이동)
  match_lexicon()    어휘사전(사물→등급)에 있는 단어로만 이루어진 문장은 LLM 없이 처리
  descriptor_to_oklch()  등급 → OKLCH 표
  thumbnail_svg()    팔레트 썸네일 (SVG)
"""
import re, html

# ── 등급 표 (설계값, 바꾸면 모든 결과가 바뀌므로 버전으로 관리) ──────────────
TABLE_VERSION = "v1"
HUES = {  # OKLCH 색상각(도). 무채는 채도 0으로 강제
    "빨강": 27, "주황": 55, "노랑": 95, "연두": 125, "초록": 150, "청록": 190,
    "하늘": 230, "파랑": 260, "남색": 272, "보라": 305, "자주": 340, "분홍": 8, "무채": 0,
}
LIGHTNESS = {1: 0.22, 2: 0.32, 3: 0.42, 4: 0.52, 5: 0.62, 6: 0.70, 7: 0.78, 8: 0.86, 9: 0.94}
CHROMA = {0: 0.0, 1: 0.02, 2: 0.05, 3: 0.09, 4: 0.14, 5: 0.19}

BRANDS = {"teal": "#00b8bb", "navy": "#0a2242"}
BRAND_WORDS = {"teal": ["kriteq teal", "teal", "틸", "청록 브랜드"], "navy": ["kriteq navy", "navy", "네이비"]}
STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
COUNT = {"한": 1, "두": 2, "세": 3, "네": 4, "1": 1, "2": 2, "3": 3, "4": 4}

# 수식어 → (밝기 등급 이동, 채도 등급 이동)
MODIFIERS = [
    ("아주 진하게", (-2, 0)), ("아주 어둡게", (-2, 0)), ("아주 연하게", (2, 0)), ("아주 밝게", (2, 0)),
    ("진하게", (-1, 0)), ("어둡게", (-1, 0)), ("연하게", (1, 0)), ("밝게", (1, 0)),
    ("선명하게", (0, 1)), ("쨍하게", (0, 1)), ("탁하게", (0, -1)), ("차분하게", (0, -1)), ("흐리게", (0, -1)),
]
# 어휘사전 판정 때 무시하는 말: 단어 전체가 이것이거나(장식어), 단어가 조사뿐일 때만 무시한다.
FILLERS = {"그리고", "같은", "처럼", "느낌", "분위기", "색", "색깔", "색감", "컬러", "톤", "팔레트", "풍경", "길"}
PARTICLES = ["에서", "으로", "이랑", "처럼", "같은", "의", "에", "와", "과", "랑", "을", "를", "은", "는", "이", "가", "로", "도"]


def _is_filler(tok):
    """조사만 남은 토큰, 또는 장식어(+조사)면 True. '가을'처럼 조사로 시작하는 실제 단어는 지우지 않는다."""
    if tok in FILLERS or tok in PARTICLES:
        return True
    for p in PARTICLES:
        if tok.endswith(p) and tok[: -len(p)] in FILLERS:
            return True
    return False


def normalize(prompt):
    """재활용 키: 소문자, 문장부호 제거, 공백 하나로."""
    s = prompt.lower()
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)            # 소수점은 남기고 마침표만 지운다
    s = re.sub(r"[\"'“”‘’,!?~·…()\[\]{}]", " ", s)
    return " ".join(s.split())


def descriptor_to_oklch(d):
    """등급 → OKLCH 설계값 (L, C, H). 무채는 C=0."""
    h = d["hue"]
    C = 0.0 if h == "무채" else CHROMA[d["chroma"]]
    return LIGHTNESS[d["lightness"]], C, float(HUES[h])


def validate_descriptor(d):
    """LLM이 낸 등급을 검사. 틀리면 None (숫자·범위 밖 값은 받지 않는다)."""
    try:
        hue, L, C = d["hue"], int(d["lightness"]), int(d["chroma"])
    except (KeyError, TypeError, ValueError):
        return None
    if hue not in HUES or L not in LIGHTNESS or C not in CHROMA:
        return None
    return {"hue": hue, "lightness": L, "chroma": 0 if hue == "무채" else C}


def shift(d, dl, dc):
    out = dict(d)
    out["lightness"] = min(9, max(1, d["lightness"] + dl))
    if d["hue"] != "무채":
        out["chroma"] = min(5, max(0, d["chroma"] + dc))
    return out


def parse_modifiers(text):
    """문장 속 수식어의 합. 긴 표현을 먼저 지워 '아주 진하게'가 두 번 세지지 않게 한다."""
    dl = dc = 0
    rest = text
    for word, (a, b) in MODIFIERS:
        n = rest.count(word)
        if n:
            dl += a * n; dc += b * n
            rest = rest.replace(word, " ")
    return dl, dc, rest


def parse_rules(text):
    """규칙으로 끝나는 요청이면 {"kind": ...} 반환, 아니면 None."""
    m = re.search(r"#([0-9a-f]{6}|[0-9a-f]{3})(?![0-9a-f])", text)
    if m:
        return {"kind": "hex", "hex": "#" + m.group(1)}

    m = re.search(r"oklch\s*\(?\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)", text)
    if m:
        return {"kind": "oklch", "L": float(m.group(1)), "C": float(m.group(2)), "H": float(m.group(3))}
    nums = {}
    for key, pat in (("L", r"밝기\s*([\d.]+)"), ("C", r"채도\s*([\d.]+)"), ("H", r"색상각?\s*([\d.]+)")):
        mm = re.search(pat, text)
        if mm:
            nums[key] = float(mm.group(1))
    if len(nums) == 3:
        return {"kind": "oklch", **nums}

    brand = None
    for b, words in BRAND_WORDS.items():
        if any(w in text for w in words):
            brand = b; break
    if brand:
        base = None
        mm = re.search(r"(?<!\d)(50|[1-9]00)(?!\d)", text)
        if mm:
            base = int(mm.group(1))
        delta = 0
        for mm in re.finditer(r"(한|두|세|네|[1-4])\s*단계\s*(?:더\s*)?(진하게|어둡게|연하게|밝게)", text):
            n = COUNT[mm.group(1)] * 100
            delta += n if mm.group(2) in ("진하게", "어둡게") else -n
        if "hover" in text or "호버" in text:
            delta += 100          # 규칙: hover = 기준보다 한 단계 진하게
        if "pressed" in text or "눌림" in text:
            delta += 200          # 규칙: pressed = 두 단계 진하게
        return {"kind": "brand", "brand": brand, "base": base, "delta": delta}
    return None


def match_lexicon(text, lexicon):
    """문장이 어휘사전 단어(+수식어·조사)만으로 이루어졌으면 [(concept, descriptor)] 반환, 아니면 None."""
    _, _, rest = parse_modifiers(text)
    found = []
    for concept in sorted(lexicon, key=len, reverse=True):      # 긴 단어 먼저 ("은행잎" > "잎")
        if concept in rest:
            found.append(concept)
            rest = rest.replace(concept, " ")
    if not found:
        return None
    for tok in rest.split():
        if not _is_filler(tok):
            return None      # 사전에 없는 말이 남았다 → LLM 필요
    order = sorted(found, key=lambda c: text.find(c))
    return [(c, lexicon[c]) for c in order]


# ── 썸네일 ────────────────────────────────────────────────────────────────
def _ink(L):
    return "#111" if L >= 0.62 else "#fff"


def thumbnail_svg(prompt, palette, w=320, h=180):
    """팔레트를 세로 띠로, 아래에 문장. 결정론(같은 팔레트 → 같은 SVG)."""
    n = max(1, len(palette))
    band_h = h - 36
    bw = w / n
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
             f'font-family="Pretendard, system-ui, sans-serif">',
             f'<rect width="{w}" height="{h}" fill="#ffffff"/>']
    for i, p in enumerate(palette):
        x = round(i * bw, 2)
        parts.append(f'<rect x="{x}" y="0" width="{round(bw + 0.5, 2)}" height="{band_h}" fill="{p["hex"]}"/>')
        ink = _ink(p.get("L", 0.5))
        label = html.escape((p.get("label") or "")[:8])
        parts.append(f'<text x="{round(x + 8, 2)}" y="{band_h - 22}" font-size="12" font-weight="600" fill="{ink}">{label}</text>')
        parts.append(f'<text x="{round(x + 8, 2)}" y="{band_h - 8}" font-size="10" fill="{ink}" opacity="0.85">{p["hex"]}</text>')
    title = prompt if len(prompt) <= 22 else prompt[:21] + "…"
    parts.append(f'<text x="10" y="{h - 13}" font-size="13" font-weight="600" fill="#0a2242">{html.escape(title)}</text>')
    parts.append("</svg>")
    return "".join(parts)
