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
COVER_MIN = float(os.getenv("IMAGE_COVER_MIN", "0.80"))
MAX_ATTEMPTS = int(os.getenv("IMAGE_MAX_ATTEMPTS", "2"))
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
ROLES = ("dominant", "supporting", "atmospheric", "accent")
NAME_DE = float(os.getenv("IMAGE_NAME_DE", "15"))   # 가장 가까운 기준색이 이보다 멀면 '새 색'으로 표시

# 정서 등급별 허용 범위 (면적 가중 평균, CIE LCh). demo 값 — 사용자 평가로 확정할 것.
AROUSAL_C = {1: (0, 26), 2: (6, 36), 3: (12, 50), 4: (22, 70), 5: (32, 110)}
VALENCE_L = {1: (15, 58), 2: (22, 68), 3: (32, 82), 4: (42, 92), 5: (52, 98)}

IMAGE_CACHE: dict = {}        # cache_key → PIL.Image (프로세스 캐시: 같은 기억 = 같은 그림)


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


def paint_with_fallback(prompt: str, painter: str, seed: int, base_palette: list) -> tuple:
    """화가 호출이 실패하면(키·패키지·네트워크) 다음 화가로: gemini → claude_scene → stub. 실제로 그린 화가를 돌려준다."""
    order = ["gemini", "claude_scene", "stub"]
    chain = order[order.index(painter):]
    for i, name in enumerate(chain):
        if name == "claude_scene" and not os.getenv("ANTHROPIC_API_KEY") and i > 0:
            continue
        try:
            return paint(prompt, name, seed, base_palette), name
        except Exception as ex:
            logger.warning(f"[image_first] 화가 {name} 실패 → 다음 화가: {type(ex).__name__}: {str(ex)[:120]}")
    raise RuntimeError("모든 화가가 실패했습니다")


def cache_key(masked_text: str, painter: str) -> str:
    """원문이 아니라 해시만 남는다. 그림이 문장 자체에 달려 있으므로 마스킹된 문장을 키에 쓴다."""
    norm = " ".join(masked_text.split())
    model = GEMINI_IMAGE_MODEL if painter == "gemini" else painter
    blob = json.dumps([norm, painter, model, ENGINE_VERSION, K_CLUSTERS], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ── ① 프롬프트 (RAG 보강) ────────────────────────────────────────────────
def _words(affect) -> str:
    if affect is None:
        return ""
    a = {1: "아주 고요하고 가라앉은", 2: "차분한", 3: "보통의", 4: "생기 있는", 5: "아주 들뜨고 선명한"}[affect.arousal]
    v = {1: "슬프고 어두운", 2: "쓸쓸한", 3: "담담한", 4: "따뜻하고 밝은", 5: "아주 행복하고 환한"}[affect.valence]
    return f"정서: {v} · {a} (쾌 {affect.valence}/5, 각성 {affect.arousal}/5)"


def build_prompt(summary: str, res: dict, kb, objects: list, affect, feedback: str = "") -> str:
    hints = []
    for axis in ("emotion", "time", "space"):
        e = kb.by_id[res[axis].kb_id]
        if res[axis].how != "fallback":
            hints.append(f"- {axis}: {e.get('description', e['name'])}")
    objs = ", ".join(o.name for o in objects) or "없음"
    lines = [
        "색면추상화(color field painting) 한 점을 그린다. 세로 4:5.",
        "부드러운 가장자리의 큰 색면 3~6개가 겹치거나 번지는 구성. 글자·사람·사물의 형태·로고는 그리지 않는다.",
        f"기억: {summary}",
        "기억의 분위기 (색 지식 KB 에서 검색):", *hints,
        f"기억 속 사물(형태 없이 색으로만 암시): {objs}",
        _words(affect),
    ]
    if feedback:
        lines.append(f"수정 지시: {feedback}")
    return "\n".join(x for x in lines if x)


# ── ② 그리기 ─────────────────────────────────────────────────────────────
def _paint_gemini(prompt: str) -> Image.Image:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:                                                            # 새 Interactions API (2026 문서 기준)
        it = client.interactions.create(model=GEMINI_IMAGE_MODEL, input=prompt,
                                        response_format={"type": "image", "mime_type": "image/png",
                                                         "aspect_ratio": "4:5", "image_size": "1K"})
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
        "required": ["kind", "x", "y", "w", "h", "color", "softness"]}}},
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
    rng = np.random.default_rng(seed)
    arr = np.asarray(canvas, float) + rng.normal(0, 2.5, (H, W, 3))            # 캔버스 결
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))


def _paint_claude(prompt: str, seed: int) -> Image.Image:
    from core.llm import structured
    system = ("당신은 색면추상 화가입니다. 그림을 직접 그리는 대신 색면 구성을 JSON 으로 냅니다. "
              "좌표 x,y,w,h 는 화면 비율(0~1), 색은 #RRGGBB. 큰 면 3~6개, 서로 겹치고 번지게. "
              "기억의 분위기와 정서 등급에 맞는 색을 직접 고르십시오. 비슷한 색만 반복하지 마십시오.")
    scene = structured(system, prompt, _SCENE_SCHEMA, max_tokens=900)
    return render_scene(scene, seed)


def _paint_stub(prompt: str, seed: int, base_palette: list) -> Image.Image:
    """키 없이 도는 테스트 대역: eng-1.x 팔레트를 색상 ±30°, 채도 ×0.7~1.6 으로 흔들어 색면을 배치."""
    rng = np.random.default_rng(seed)
    shapes = []
    for p in base_palette:
        L, C, h = p["lch"]
        hx, _ = lch_to_hex_clipped((L + rng.uniform(-8, 8), C * rng.uniform(0.7, 1.6), h + rng.uniform(-30, 30)))
        shapes.append({"kind": "rect" if rng.random() < 0.7 else "ellipse", "x": rng.uniform(0, .3), "y": rng.uniform(0, .75),
                       "w": rng.uniform(.6, 1), "h": rng.uniform(.18, .45) * (1.6 if p["role"] == "dominant" else 1),
                       "color": hx, "softness": rng.uniform(.2, .8)})
    return render_scene({"background": base_palette[0]["hex"], "shapes": shapes}, seed)


def paint(prompt: str, painter: str, seed: int, base_palette: list) -> Image.Image:
    if painter == "gemini":
        return _paint_gemini(prompt)
    if painter == "claude_scene":
        return _paint_claude(prompt, seed)
    return _paint_stub(prompt, seed, base_palette)


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
def review(m: dict, affect) -> dict:
    lch = [lab2lch(c) for c in m["centers"]]
    Cw = float(sum(r * c[1] for r, c in zip(m["ratios"], lch)))
    Lw = float(sum(r * c[0] for r, c in zip(m["ratios"], lch)))
    fails = []
    if m["coverage"] < COVER_MIN:
        fails.append(f"색면을 더 단순하게(4색이 그림의 {m['coverage']*100:.0f}%만 대표, 목표 {COVER_MIN*100:.0f}%)")
    if affect is not None:
        lo, hi = AROUSAL_C[affect.arousal]
        if not lo <= Cw <= hi:
            fails.append(f"{'더 선명하게' if Cw < lo else '더 차분하게'}(평균 채도 {Cw:.0f}, 범위 {lo}~{hi})")
        lo, hi = VALENCE_L[affect.valence]
        if not lo <= Lw <= hi:
            fails.append(f"{'더 밝게' if Lw < lo else '더 어둡게'}(평균 명도 {Lw:.0f}, 범위 {lo}~{hi})")
    return {"ok": not fails, "fails": fails, "chroma_w": round(Cw, 1), "light_w": round(Lw, 1)}


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
def run(masked: str, summary: str, res: dict, kb, objects: list, affect, base_palette: list) -> dict:
    painter = painter_name()
    key = cache_key(masked, painter)
    seed = int(key[:8], 16)
    fb, tries, best = "", [], None
    for n in range(1, MAX_ATTEMPTS + 1):
        prompt = build_prompt(summary or masked[:40], res, kb, objects, affect, fb)
        img, used = paint_with_fallback(prompt, painter, seed + n - 1, base_palette)
        m = measure(img)
        rv = review(m, affect)
        tries.append({"attempt": n, "painter": used, **{k: rv[k] for k in ("ok", "fails", "chroma_w", "light_w")},
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
                    "criteria": {"cover_de00": COVER_DE, "cover_min": COVER_MIN,
                                 "arousal_c": AROUSAL_C.get(affect.arousal) if affect else None,
                                 "valence_l": VALENCE_L.get(affect.valence) if affect else None}}
    return {"palette": palette, "cache_key": key, "image": img, "verification": verification,
            "tries": tries, "painter": painter}
