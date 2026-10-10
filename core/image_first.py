"""core/image_first.py — 그림 먼저 (eng-2.0): 기억 → 색면추상화 그림 → 그림에서 HEX 측정.

eng-1.x 는 '팔레트 계산 → 그림' 순서라, 색이 KB 21항목의 조합 안에 갇혀 다양하지 않았다.
eng-2.0 은 순서를 뒤집는다. 그림을 먼저 그리고, 팔레트는 그 그림에서 '잰다'.

  ① 프롬프트 : 기억 요약 + KB 검색 결과(감정·시간·장소 설명) + 사물 + 정서 등급 → 그림 지시문   (← RAG 의 '보강')
  ② 그리기   : PAINTER = gemini | claude_scene | stub
                 gemini       — Gemini 이미지 모델이 직접 그림 (GEMINI_API_KEY)
                 claude_scene — Claude 가 '색면 구성(JSON: 배경·면·색)'을 내고 서버가 PIL 로 그림 (ANTHROPIC_API_KEY)
                 stub         — 키 없이 도는 결정론 테스트 대역 (품질 평가용 아님)
  ③ 측정     : Lab K-Means(k=6) → 면적 큰 3색 + 주조색과 가장 대비되는 1색 → 전체 픽셀 재배정 → 면적비
               색 값은 군집의 '핵심 픽셀'(중심에 가까운 40%) 평균. 번진 경계는 두 색이 섞인 픽셀이라 빼야 탁해지지 않는다
  ④ 심사     : (a) 대표도 — 픽셀 중 4색 중 하나와 ΔE00 ≤ COVER_DE 인 비율 ≥ COVER_MIN
               (b) 정서   — 면적 가중 평균 채도·명도가 쾌·각성 등급의 허용 범위 안   (Wilms 2018, Valdez 1994)
               실패하면 '무엇을 고칠지' 문장을 붙여 다시 그림 (IMAGE_MAX_ATTEMPTS)
  ⑤ 설명     : 측정한 색마다 KB·사물 사전에서 가장 가까운 색 이름과 ΔE00 (사후 설명)

숫자 HEX 는 언제나 그림의 픽셀에서 잰 값이다. 모델이 쓴 숫자를 그대로 믿지 않는다.
"""
from __future__ import annotations
import base64, hashlib, io, json, logging, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from core.color import rgb2lab, lab2hex, lab2lch, lch2lab, hex2lab, delta_e_2000, lch_to_hex_clipped

logger = logging.getLogger("uvicorn")
ENGINE_VERSION = "eng-2.0"
W, H = 720, 900
K_CLUSTERS = int(os.getenv("IMAGE_K", "6"))
COVER_DE = float(os.getenv("IMAGE_COVER_DE", "10"))
CORE_FRAC = float(os.getenv("IMAGE_CORE_FRAC", "0.4"))   # 군집마다 중심에 가까운 픽셀 이 비율만으로 색을 잰다 (번진 경계 = 섞인 색 제외)
# 화풍 (eng-2.4): color_field = 큰 색면이 번지는 색면추상(eng-2.0) / gestural = 붓질이 보이는 표현적 추상 (2026-10-10 레퍼런스)
PAINT_STYLE = os.getenv("PAINT_STYLE", "gestural").lower()
STYLES = ("color_field", "gestural")
# 4색 대표도 기준은 화풍마다 다르다. gestural 0.55 = 레퍼런스 14점을 이 심사기로 잰 값에서 12/14 가 통과하는 선
#   (실측 중앙값 66%, 최소 42%, 80% 이상은 4/14 — 붓질 그림은 섞인 중간색이 많아 4색이 덜 대표한다)
COVER_MIN_BY_STYLE = {"color_field": float(os.getenv("IMAGE_COVER_MIN", "0.80")),
                      "gestural": float(os.getenv("IMAGE_COVER_MIN_GESTURAL", "0.55"))}
COVER_MIN = COVER_MIN_BY_STYLE["color_field"]
MAX_ATTEMPTS = int(os.getenv("IMAGE_MAX_ATTEMPTS", "2"))
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
ROLES = ("dominant", "supporting", "atmospheric", "accent")
NAME_DE = float(os.getenv("IMAGE_NAME_DE", "10"))
# 정서 범위를 심사에 어떻게 쓰나: hard = 범위 밖이면 탈락·재생성(기본) / soft = 참고 표시만 (대표도만 합격 기준)
AFFECT_GATE = os.getenv("IMAGE_AFFECT_GATE", "hard").lower()   # 가장 가까운 기준색이 이보다 멀면 '새 색'으로 표시

# 정서 등급별 허용 범위 (면적 가중 평균, CIE LCh). demo 값 — 사용자 평가로 확정할 것.
AROUSAL_C = {1: (0, 26), 2: (6, 36), 3: (12, 50), 4: (22, 70), 5: (32, 110)}
VALENCE_L = {1: (15, 58), 2: (22, 68), 3: (32, 82), 4: (42, 92), 5: (52, 98)}

IMAGE_CACHE: dict = {}        # cache_key → PIL.Image (프로세스 캐시: 같은 기억 = 같은 그림)


def style_name() -> str:
    return PAINT_STYLE if PAINT_STYLE in STYLES else "gestural"


def painter_tag(painter: str, style: str | None = None) -> str:
    """키에 들어가는 화가 이름. color_field 는 예전 키 그대로(이미 고정된 표본을 그대로 찾게), 다른 화풍은 '+화풍'."""
    style = style or style_name()
    return painter if style == "color_field" else f"{painter}+{style}"


def painter_name() -> str:
    p = os.getenv("PAINTER", "").lower()
    if p in ("gemini", "claude_scene", "stub"):
        return p
    if os.getenv("GEMINI_API_KEY") and _has_genai():
        return "gemini"
    return "claude_scene" if os.getenv("ANTHROPIC_API_KEY") else "stub"


def _has_genai() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        return False


def paint_with_fallback(prompt: str, painter: str, seed: int, base_palette: list, style: str = "color_field") -> tuple:
    """화가 호출이 실패하면(키·패키지·네트워크) 다음 화가로: gemini → claude_scene → stub. 실제로 그린 화가를 돌려준다."""
    order = ["gemini", "claude_scene", "stub"]
    chain = order[order.index(painter):]
    for i, name in enumerate(chain):
        if name == "claude_scene" and not os.getenv("ANTHROPIC_API_KEY") and i > 0:
            continue
        try:
            return paint(prompt, name, seed, base_palette, style), name
        except Exception as ex:
            logger.warning(f"[image_first] 화가 {name} 실패 → 다음 화가: {type(ex).__name__}: {str(ex)[:120]}")
    raise RuntimeError("모든 화가가 실패했습니다")


def cache_key(masked_text: str, painter: str, style: str | None = None) -> str:
    """원문이 아니라 해시만 남는다. 그림이 문장 자체에 달려 있으므로 마스킹된 문장을 키에 쓴다."""
    norm = " ".join(masked_text.split())
    model = painter_tag(GEMINI_IMAGE_MODEL if painter == "gemini" else painter, style)
    blob = json.dumps([norm, painter, model, ENGINE_VERSION, K_CLUSTERS], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ── ① 프롬프트 (RAG 보강) ────────────────────────────────────────────────
def _words(affect) -> str:
    if affect is None:
        return ""
    a = {1: "아주 고요하고 가라앉은", 2: "차분한", 3: "보통의", 4: "생기 있는", 5: "아주 들뜨고 선명한"}[affect.arousal]
    v = {1: "슬프고 어두운", 2: "쓸쓸한", 3: "담담한", 4: "따뜻하고 밝은", 5: "아주 행복하고 환한"}[affect.valence]
    return f"정서: {v} · {a} (쾌 {affect.valence}/5, 각성 {affect.arousal}/5)"


# 화풍 설명 — 작가 이름·작품 제목은 넣지 않는다 (특징만 말로). 숫자 색값도 넣지 않는다
STYLE_LINES = {
    "color_field": [
        "색면추상화(color field painting) 한 점을 그린다. 세로 4:5.",
        "부드러운 가장자리의 큰 색면 3~6개가 겹치거나 번지는 구성. 글자·사람·사물의 형태·로고는 그리지 않는다.",
    ],
    "gestural": [
        "표현적 추상화(expressive abstract painting) 한 점을 그린다. 캔버스에 아크릴, 세로 4:5.",
        "빠르고 굵은 붓질 자국이 보이는 질감. 젖은 물감이 서로 섞이며 번지고, 붓질의 방향이 화면에 리듬을 만든다.",
        "중심 하나에 모이지 않고 화면 전체에 색이 흩어진 구성. 작은 물감 튐·점과 짧은 붓질 악센트를 몇 군데 둔다.",
        "글자·사람·사물의 형태·로고는 그리지 않는다. 사물은 색과 붓질로만 암시한다.",
    ],
}
ENERGY = {1: "붓질은 적고 느리게, 넓은 면 위주", 2: "붓질은 부드럽고 차분하게", 3: "붓질은 보통 빠르기로",
          4: "붓질은 경쾌하고 빠르게, 튐을 조금", 5: "붓질은 아주 활기차게, 튐과 악센트를 많이"}


# eng-2.5: 화가에게 사물 '이름'을 주면 그 사물을 그린다 (2026-10-10 운영: 수박 기억 → 수박 조각·얼굴처럼 보이는 배치·마루 원근선).
#          사물은 이름 대신 등급을 색 말로 바꿔 넘기고, 새기 쉬운 형태를 구체적으로 금지한다.
HUE_WORDS = {"빨강": "빨강", "주황": "주황", "노랑": "노랑", "연두": "연두", "초록": "초록", "청록": "청록", "하늘": "하늘색",
             "파랑": "파랑", "남색": "남색", "보라": "보라", "자주": "자주", "분홍": "분홍"}
NO_FORMS = ("금지: 사물의 조각·단면·윤곽, 얼굴이나 눈·코·입처럼 읽히는 배치, 사람·동물의 실루엣, "
            "바닥·벽·지평선의 원근선, 마루결·창틀 같은 곧은 구조물. 모든 것은 붓질과 색 얼룩으로만.")


def color_words(descriptor) -> str:
    """사물 등급(색상 계열·밝기 1~9·채도 0~5) → 색 말. 예) (빨강, 5, 4) → '선명한 빨강', (무채, 9, 0) → '흰색'.
    숫자 색값은 쓰지 않는다 (화가에게도 계산기 숫자를 넘기지 않는 원칙 그대로)."""
    hue, L, C = descriptor
    if hue == "무채" or C == 0:
        return "흰색" if L >= 8 else "밝은 회색" if L >= 6 else "회색" if L >= 4 else "짙은 회색" if L >= 3 else "검정에 가까운 색"
    tone = "아주 연한 " if L >= 8 else "밝은 " if L >= 7 else "" if L >= 4 else "짙은 "
    sat = "탁한 " if C <= 1 else "부드러운 " if C == 2 else "" if C == 3 else "선명한 "
    return f"{sat}{tone}{HUE_WORDS.get(hue, hue)}".strip()


def build_prompt(summary: str, res: dict, kb, objects: list, affect, feedback: str = "", grounding: dict | None = None,
                 style: str | None = None) -> str:
    style = style or style_name()
    hints = []
    for axis in ("emotion", "time", "space"):
        e = kb.by_id[res[axis].kb_id]
        if res[axis].how != "fallback":
            hints.append(f"- {axis}: {e.get('description', e['name'])}")
    obj_colors = list(dict.fromkeys(color_words(o.descriptor) for o in objects))   # 같은 색 말은 한 번만
    lines = [
        *STYLE_LINES[style],
        "화면 끝까지 채운다(full bleed). 액자·캔버스 테두리·흰 여백·벽·그림자를 그리지 않는다.",
        NO_FORMS,
        f"기억 (분위기만 참고한다 — 그 안의 사람·사물을 그리지 않는다): {summary}",
        "기억의 분위기 (색 지식 KB 에서 검색):", *hints,
        *(["비슷한 장면과 그 색 (코퍼스 검색, eng-2.2):", *rag_lines] if (rag_lines := _rag_lines(grounding)) else []),
        f"기억 속 사물의 색 (이름·모양 없이 색 얼룩으로만): {', '.join(obj_colors)}" if obj_colors else "",
        _words(affect),
        f"붓질의 에너지: {ENERGY[affect.arousal]}" if (style == "gestural" and affect is not None) else "",
    ]
    if feedback:
        lines.append(f"수정 지시: {feedback}")
    return "\n".join(x for x in lines if x)


def _rag_lines(grounding):
    from core.rag import prompt_lines
    return prompt_lines(grounding)


# ── ② 그리기 ─────────────────────────────────────────────────────────────
def _paint_gemini(prompt: str) -> Image.Image:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:                                                            # 새 Interactions API (2026 문서 기준)
        it = client.interactions.create(model=GEMINI_IMAGE_MODEL, input=prompt,
                                        response_format={"type": "image", "mime_type": "image/jpeg",
                                                         "aspect_ratio": "4:5", "image_size": "1K"})
        if getattr(it, "output_image", None) is None or not it.output_image.data:
            raise RuntimeError("Gemini 응답에 이미지가 없습니다")
        data = it.output_image.data
        raw = base64.b64decode(data) if isinstance(data, str) else data
    except AttributeError:                                          # 예전 SDK: generate_content
        from google.genai import types
        r = client.models.generate_content(model=GEMINI_IMAGE_MODEL, contents=prompt,
                                           config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
        raw = next(p.inline_data.data for p in r.candidates[0].content.parts if getattr(p, "inline_data", None))
    return Image.open(io.BytesIO(raw)).convert("RGB").resize((W, H))


_SCENE_SCHEMA = {"type": "object", "properties": {
    "background": {"type": "string", "description": "배경색 #RRGGBB"},
    "shapes": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["rect", "ellipse"]},
        "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"},
        "color": {"type": "string", "description": "#RRGGBB"},
        "softness": {"type": "number", "description": "가장자리 번짐 0(선명)~1(아주 번짐)"}},
        "required": ["kind", "x", "y", "w", "h", "color", "softness"]}},
    # eng-2.4 gestural: 붓질(꺾은선 굵은 획)과 물감 튐. color_field 에서는 비워도 된다
    "strokes": {"type": "array", "maxItems": 40, "items": {"type": "object", "properties": {
        "points": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["x", "y"]}},
        "width": {"type": "number", "description": "붓 폭, 화면 폭 대비 0.005~0.08"},
        "color": {"type": "string", "description": "#RRGGBB"},
        "softness": {"type": "number", "description": "0(선명)~1(번짐)"}},
        "required": ["points", "width", "color", "softness"]}},
    "flecks": {"type": "array", "maxItems": 40, "items": {"type": "object", "properties": {
        "x": {"type": "number"}, "y": {"type": "number"}, "r": {"type": "number", "description": "반지름, 화면 폭 대비 0.003~0.02"},
        "color": {"type": "string", "description": "#RRGGBB"}}, "required": ["x", "y", "r", "color"]}}},
    "required": ["background", "shapes"]}


def _hex_ok(h) -> bool:
    return isinstance(h, str) and len(h) == 7 and h[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in h[1:])


def render_scene(scene: dict, seed: int = 0) -> Image.Image:
    """색면 구성(JSON) → 그림. 좌표는 0~1 비율. 잘못된 값은 버린다(검증 게이트)."""
    bg = scene.get("background") if _hex_ok(scene.get("background")) else "#808080"
    canvas = Image.new("RGB", (W, H), bg)
    for s in (scene.get("shapes") or [])[:8]:
        if not _hex_ok(s.get("color")):
            continue
        x, y, w, h = (max(0.0, min(1.0, float(s.get(k, 0)))) for k in ("x", "y", "w", "h"))
        if w <= 0.01 or h <= 0.01:
            continue
        mask = Image.new("L", (W, H), 0)
        box = [x * W, y * H, min(1, x + w) * W, min(1, y + h) * H]
        d = ImageDraw.Draw(mask)
        (d.ellipse if s.get("kind") == "ellipse" else d.rectangle)(box, fill=235)
        soft = max(0.0, min(1.0, float(s.get("softness", 0.3))))
        mask = mask.filter(ImageFilter.GaussianBlur(4 + soft * 40))
        canvas = Image.composite(Image.new("RGB", (W, H), s["color"]), canvas, mask)
    if scene.get("strokes"):                                                    # gestural: 바탕도 붓으로 문지른 결
        canvas = _underpaint(canvas, seed)
    canvas = _strokes(canvas, scene.get("strokes") or [], scene.get("flecks") or [], seed)
    rng = np.random.default_rng(seed)
    arr = np.asarray(canvas, float) + rng.normal(0, 2.5, (H, W, 3))            # 캔버스 결
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))


def _clip01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _spline(pts: list, step: float = 2.0) -> np.ndarray:
    """꺾은점 → 부드러운 곡선 (Catmull-Rom). 붓은 꺾이지 않고 휘어 지나간다."""
    p = np.array([pts[0], *pts, pts[-1]], float)
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        n = max(2, int(np.linalg.norm(p2 - p1) / step))
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(p[-2][None, :])
    return np.vstack(out)


def _hex_rgb(h: str) -> np.ndarray:
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)


def _underpaint(canvas: Image.Image, seed: int, n: int = 140) -> Image.Image:
    """바탕 문지르기: 넓은 붓 n번을 바탕 위에 끌고 간다. 붓에 묻는 색 = 시작점의 바탕색(±명암) → 젖은 물감이 끌려가며 섞이는 결.
    색은 바탕에서 집어 오므로 화면 구성(색면 배치)은 그대로, 매끈한 그라데이션만 붓 자국이 된다. 결정론."""
    rng = np.random.default_rng(seed + 104729)
    src = np.asarray(canvas.convert("RGB"), float)
    strokes = []
    for _ in range(n):
        x0, y0 = rng.uniform(-0.05, 1.05), rng.uniform(-0.05, 1.05)
        ang, length = rng.uniform(0, np.pi), rng.uniform(0.12, 0.35)
        bend = rng.uniform(-0.25, 0.25)
        pts = [{"x": x0 + np.cos(ang + bend * k) * length * k / 3, "y": y0 + np.sin(ang + bend * k) * length * k / 3 * 0.8}
               for k in range(4)]
        px = int(np.clip(x0, 0, 0.999) * W); py = int(np.clip(y0, 0, 0.999) * H)
        c = np.clip(src[py, px] + rng.uniform(-14, 12), 0, 255).astype(int)
        strokes.append({"points": pts, "width": rng.uniform(0.04, 0.08), "color": "#%02X%02X%02X" % tuple(c),
                        "softness": rng.uniform(0.45, 0.8)})
    return _strokes(canvas, strokes, [], seed + 1, limit=n)


def _strokes(canvas: Image.Image, strokes: list, flecks: list, seed: int = 0, limit: int = 40) -> Image.Image:
    """붓질 = 곡선을 따라 지나가는 붓털 여러 가닥. 가닥마다 밝기·투명도가 조금씩 다르고, 끝으로 갈수록 가늘어지며,
    물감이 마르는 곳에서 끊긴다(드라이 브러시). 물감 튐은 작은 얼룩. 시드가 같으면 같은 그림(결정론).
    잘못된 값은 버린다(검증 게이트)."""
    rng = np.random.default_rng(seed + 7919)
    layer = canvas.convert("RGBA"); layer.putalpha(0)       # 투명 칸의 색 = 바탕색 → 흐림 처리 때 검은 테두리가 생기지 않는다
    d = ImageDraw.Draw(layer)
    for s in strokes[:limit]:
        pts = [(_clip01(p.get("x")) * W, _clip01(p.get("y")) * H) for p in (s.get("points") or [])[:6] if isinstance(p, dict)]
        if len(pts) < 2 or not _hex_ok(s.get("color")):
            continue
        wpx = max(3.0, max(0.005, min(0.08, float(s.get("width") or 0.02))) * W)
        path = _spline(pts)
        if len(path) < 3:
            continue
        tang = np.gradient(path, axis=0)
        tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
        normal = np.stack([-tang[:, 1], tang[:, 0]], 1)
        u = np.linspace(0, 1, len(path))
        taper = np.clip(1.0 - 0.45 * u ** 2, 0.55, 1)                             # 끝으로 갈수록 조금 가늘게 (나뭇잎 모양이 되지 않게 약하게)
        base = _hex_rgb(s["color"])
        soft = _clip01(s.get("softness", 0.3))
        n_br = int(np.clip(wpx / 2.2, 5, 22))
        for b in range(n_br):
            off = (b / (n_br - 1) - 0.5) * wpx
            shade = rng.normal(0, 7)                                              # 가닥마다 아주 조금 다른 명암 (테두리처럼 보이지 않게 작게)
            col = tuple(int(c) for c in np.clip(base + shade, 0, 255))
            alpha = int(rng.uniform(120, 215) * (1 - 0.35 * soft))
            bw = max(2, int(wpx / n_br * rng.uniform(2.0, 3.2)))                  # 가닥이 겹쳐 면이 되게
            line = path + normal * (off * taper[:, None]) + rng.normal(0, 0.6, path.shape)
            dry = rng.uniform(0.75, 1.0)                                          # 이 가닥이 끝까지 가는 비율
            keep = u <= dry                                                       # 끝에서만 마른다 (중간 점 끊김 없음)
            seg = []
            for ok, q in zip(keep, line):
                if ok:
                    seg.append(tuple(q))
                elif len(seg) > 1:
                    d.line(seg, fill=col + (alpha,), width=bw, joint="curve"); seg = []
                else:
                    seg = []
            if len(seg) > 1:
                d.line(seg, fill=col + (alpha,), width=bw, joint="curve")
    for f in flecks[:40]:
        if not _hex_ok(f.get("color")):
            continue
        x, y = _clip01(f.get("x")) * W, _clip01(f.get("y")) * H
        r = max(1.5, max(0.003, min(0.02, float(f.get("r") or 0.008))) * W)
        col = tuple(int(c) for c in _hex_rgb(f["color"]))
        for _ in range(3):                                                        # 한 방울 = 겹친 얼룩 몇 개
            dx, dy, rr = rng.normal(0, r * 0.35), rng.normal(0, r * 0.35), r * rng.uniform(0.5, 1.0)
            d.ellipse([x + dx - rr, y + dy - rr * 0.8, x + dx + rr, y + dy + rr * 0.8], fill=col + (int(rng.uniform(180, 240)),))
    layer = layer.filter(ImageFilter.GaussianBlur(1.1))
    return Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")


_SYSTEM = {
    "color_field": ("당신은 색면추상 화가입니다. 그림을 직접 그리는 대신 색면 구성을 JSON 으로 냅니다. "
                    "좌표 x,y,w,h 는 화면 비율(0~1), 색은 #RRGGBB. 큰 면 3~6개, 서로 겹치고 번지게. "
                    "기억의 분위기와 정서 등급에 맞는 색을 직접 고르십시오. 비슷한 색만 반복하지 마십시오."),
    "gestural": ("당신은 표현적 추상화를 그리는 화가입니다. 그림을 직접 그리는 대신 구성을 JSON 으로 냅니다. "
                 "좌표는 화면 비율(0~1), 색은 #RRGGBB. 먼저 shapes 로 화면 전체를 덮는 부드러운 바탕 색면 3~5개(softness 0.6 이상), "
                 "그 위에 strokes 로 빠르고 굵은 붓질 15~30개(점 3~5개 꺾은선, 방향을 섞어 리듬을 만들 것), "
                 "flecks 로 작은 물감 튐 5~20개. 중심 하나에 모으지 말고 화면 전체에 흩어지게. "
                 "기억의 분위기와 정서 등급에 맞는 색을 직접 고르고, 바탕보다 진한 색 하나를 악센트로 몇 군데만 쓰십시오."),
}


def _paint_claude(prompt: str, seed: int, style: str = "color_field") -> Image.Image:
    from core.llm import structured
    scene = structured(_SYSTEM.get(style, _SYSTEM["color_field"]), prompt, _SCENE_SCHEMA,
                       max_tokens=2600 if style == "gestural" else 900)
    return render_scene(scene, seed)


def _paint_stub(prompt: str, seed: int, base_palette: list, style: str = "color_field") -> Image.Image:
    """키 없이 도는 테스트 대역: eng-1.x 팔레트를 색상 ±30°, 채도 ×0.7~1.6 으로 흔들어 색면을 배치.
    gestural 이면 그 위에 같은 팔레트로 붓질 18개·튐 10개를 얹는다 (결정론, 품질 평가용 아님)."""
    rng = np.random.default_rng(seed)
    shapes = []
    for p in base_palette:
        L, C, h = p["lch"]
        hx, _ = lch_to_hex_clipped((L + rng.uniform(-8, 8), C * rng.uniform(0.7, 1.6), h + rng.uniform(-30, 30)))
        shapes.append({"kind": "rect" if rng.random() < 0.7 else "ellipse", "x": rng.uniform(0, .3), "y": rng.uniform(0, .75),
                       "w": rng.uniform(.6, 1), "h": rng.uniform(.18, .45) * (1.6 if p["role"] == "dominant" else 1),
                       "color": hx, "softness": rng.uniform(.2, .8)})
    scene = {"background": base_palette[0]["hex"], "shapes": shapes}
    if style == "gestural":
        hexes = [lch_to_hex_clipped((p["lch"][0], p["lch"][1] * 1.2, p["lch"][2]))[0] for p in base_palette]
        scene["strokes"] = [{"points": [{"x": x, "y": y} for x, y in zip(np.cumsum(rng.uniform(-.12, .12, 4)) + rng.uniform(.1, .9),
                                                                    np.cumsum(rng.uniform(-.08, .08, 4)) + rng.uniform(.1, .9))],
                             "width": rng.uniform(.012, .05), "color": hexes[int(rng.integers(len(hexes)))],
                             "softness": rng.uniform(.1, .5)} for _ in range(18)]
        scene["flecks"] = [{"x": rng.uniform(0, 1), "y": rng.uniform(0, 1), "r": rng.uniform(.003, .012),
                            "color": hexes[-1]} for _ in range(10)]
    return render_scene(scene, seed)


def paint(prompt: str, painter: str, seed: int, base_palette: list, style: str = "color_field") -> Image.Image:
    if painter == "gemini":
        return _paint_gemini(prompt)
    if painter == "claude_scene":
        return _paint_claude(prompt, seed, style)
    return _paint_stub(prompt, seed, base_palette, style)


# ── ③ 측정 ───────────────────────────────────────────────────────────────
def _pixels(img: Image.Image, side: int = 160) -> np.ndarray:
    im = img.convert("RGB"); im.thumbnail((side, side))
    return rgb2lab(np.asarray(im, float) / 255.0).reshape(-1, 3)


def measure(img: Image.Image, seed: int = 0) -> dict:
    """그림 → 4색 + 면적비 + 대표도. 결정론(random_state 고정)."""
    from sklearn.cluster import KMeans
    lab = _pixels(img)
    km = KMeans(n_clusters=K_CLUSTERS, n_init=10, random_state=seed).fit(lab)
    share = np.bincount(km.labels_, minlength=K_CLUSTERS) / len(lab)
    order = list(np.argsort(-share))
    picked = order[:3]
    dom = km.cluster_centers_[picked[0]]
    rest = order[3:] or order[1:]
    def contrast(i):                                             # 강조색: 주조색과 가장 다르고 너무 작지 않은 색
        return delta_e_2000(km.cluster_centers_[i], dom) * (1 if share[i] >= 0.01 else 0.3)
    picked.append(max(rest, key=contrast))
    cents = km.cluster_centers_[picked]
    d2 = ((lab[:, None, :] - cents[None, :, :]) ** 2).sum(-1)    # 전체 픽셀을 4색 중 가장 가까운 색에 다시 배정
    lbl = d2.argmin(1)
    cents = np.array([lab[lbl == j].mean(0) if (lbl == j).any() else cents[j] for j in range(4)])
    ratios = np.bincount(lbl, minlength=4) / len(lab)
    order3 = sorted(range(3), key=lambda j: -ratios[j])          # 재배정 뒤 면적이 바뀌므로 주조·보조·분위기를 다시 면적 순으로
    perm = order3 + [3]
    cents, ratios = cents[perm], ratios[perm]
    lbl = np.array(perm).argsort()[lbl]
    if CORE_FRAC < 1:                                            # 핵심 픽셀만으로 색 값 다시 재기 (면적비는 그대로)
        core = []
        for j in range(4):
            pts = lab[lbl == j]
            if len(pts) < 5:
                core.append(cents[j]); continue
            dist = ((pts - cents[j]) ** 2).sum(1)
            core.append(pts[dist <= np.quantile(dist, CORE_FRAC)].mean(0))
        cents = np.array(core)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(lab), size=min(1500, len(lab)), replace=False)
    des = np.array([delta_e_2000(lab[i], cents[lbl[i]]) for i in idx])
    return {"centers": cents, "ratios": ratios, "coverage": float((des <= COVER_DE).mean()),
            "de_p90": float(np.percentile(des, 90))}


# ── ④ 심사 ───────────────────────────────────────────────────────────────
def review(m: dict, affect, style: str = "color_field") -> dict:
    cover_min = COVER_MIN_BY_STYLE.get(style, COVER_MIN)
    lch = [lab2lch(c) for c in m["centers"]]
    Cw = float(sum(r * c[1] for r, c in zip(m["ratios"], lch)))
    Lw = float(sum(r * c[0] for r, c in zip(m["ratios"], lch)))
    fails, notes = [], []
    if m["coverage"] < cover_min:
        fails.append(f"색면을 더 단순하게(4색이 그림의 {m['coverage']*100:.1f}%만 대표, 목표 {cover_min*100:.0f}%)")   # .0f 면 79.9% 가 '80%만 대표, 목표 80%' 로 보였다
    if affect is not None:
        out = fails if AFFECT_GATE == "hard" else notes
        lo, hi = AROUSAL_C[affect.arousal]
        if not lo <= Cw <= hi:
            out.append(f"{'더 선명하게' if Cw < lo else '더 차분하게'}(평균 채도 {Cw:.0f}, 범위 {lo}~{hi})")
        lo, hi = VALENCE_L[affect.valence]
        if not lo <= Lw <= hi:
            out.append(f"{'더 밝게' if Lw < lo else '더 어둡게'}(평균 명도 {Lw:.0f}, 범위 {lo}~{hi})")
    return {"ok": not fails, "fails": fails, "notes": notes, "chroma_w": round(Cw, 1), "light_w": round(Lw, 1)}


# ── ⑤ 설명 (사후 검색) ───────────────────────────────────────────────────
def _references(kb) -> list[tuple[str, str, np.ndarray]]:
    refs = []
    for e in kb.items:
        for key in ("lch", "accent_lch"):
            if e.get(key):
                refs.append((e["name"], f"kb:{e['id']}", lch2lab(tuple(e[key]))))
    try:
        from core.objects import _lexicon, descriptor_to_lch
        for name, d in _lexicon().items():
            refs.append((name, f"lexicon:{name}", lch2lab(descriptor_to_lch(d))))
    except Exception:
        pass
    return refs


def nearest(lab, refs) -> dict:
    best = min(refs, key=lambda r: delta_e_2000(lab, r[2]))
    return {"name": best[0], "ref": best[1], "de00": round(float(delta_e_2000(lab, best[2])), 1)}


# ── 전체 ─────────────────────────────────────────────────────────────────
def run(masked: str, summary: str, res: dict, kb, objects: list, affect, base_palette: list, grounding: dict | None = None) -> dict:
    painter, style = painter_name(), style_name()
    key = cache_key(masked, painter, style)
    seed = int(key[:8], 16)
    fb, tries, best = "", [], None
    for n in range(1, MAX_ATTEMPTS + 1):
        prompt = build_prompt(summary or masked[:40], res, kb, objects, affect, fb, grounding, style)
        img, used = paint_with_fallback(prompt, painter, seed + n - 1, base_palette, style)
        m = measure(img)
        rv = review(m, affect, style)
        # 지시문도 로그에 남긴다 (코퍼스 보강·화풍이 실제로 들어갔는지 확인용, 마스킹된 요약만 포함)
        tries.append({"attempt": n, "painter": used, "style": style, "prompt": prompt,
                      **{k: rv[k] for k in ("ok", "fails", "notes", "chroma_w", "light_w")},
                      "coverage": round(m["coverage"], 3)})
        if best is None or (rv["ok"], m["coverage"]) > (best[2]["ok"], best[1]["coverage"]):
            best = (img, m, rv)
        if rv["ok"]:
            break
        fb = "; ".join(rv["fails"])
        logger.info(f"[image_first] 심사 FAIL {n}/{MAX_ATTEMPTS}: {fb}")
    img, m, rv = best
    refs = _references(kb)
    palette = []
    for role, c, r in zip(ROLES, m["centers"], m["ratios"]):
        near = nearest(c, refs)
        L, C, h = lab2lch(c)
        palette.append({"role": role, "hex": lab2hex(c), "area_ratio": round(float(r), 3),
                        "lch": [round(float(L), 2), round(float(C), 2), round(float(h), 2)],
                        "color_name": f"{near['name']} 근처" if near["de00"] <= NAME_DE else "새 색", "basis": {
                            "axis": "image", "how": "measured", "phrase": f"그림에서 {r*100:.0f}%",
                            "nearest": near}})
    IMAGE_CACHE[key] = img
    verification = {"status": "PASS" if rv["ok"] else "FAIL", "max_de00": round(m["de_p90"], 2),
                    "max_ratio_err": 0.0, "attempts": len(tries), "renderer": f"image:{tries[-1]['painter']}",
                    "coverage": round(m["coverage"], 3), "review": rv,
                    "criteria": {"cover_de00": COVER_DE, "cover_min": COVER_MIN_BY_STYLE[style], "style": style,
                                 "arousal_c": AROUSAL_C.get(affect.arousal) if affect else None,
                                 "valence_l": VALENCE_L.get(affect.valence) if affect else None}}
    return {"palette": palette, "cache_key": key, "image": img, "verification": verification,
            "tries": tries, "painter": painter, "style": style}
