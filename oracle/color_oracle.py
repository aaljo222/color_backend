# -*- coding: utf-8 -*-
"""color_oracle.py — 색 변환 오라클 (LLM 밖에서 도는 결정론 계산기)

LLM은 HEX를 '기억'으로 내지 않는다. 이 모듈을 도구로 호출하고, 결과만 쓴다.
  지원: HEX ↔ sRGB ↔ OKLab/OKLCH (Ottosson 2020) · CIELAB/LCH (D50, CSS Color 4와 같은 Bradford 순응)
  색역 매핑: CSS Color 4 방식 — 밝기·색상은 고정, 채도만 이분 탐색으로 줄여 sRGB 안으로 (ΔE_OK JND 0.02)

CLI:
  python color_oracle.py hex2oklch "#00b8bb"
  python color_oracle.py oklch2hex 0.7 0.12 196
  python color_oracle.py lch2hex 60 40 250
  python color_oracle.py hex2lch "#0a2242"
  python color_oracle.py scale "#00b8bb" --name teal     # 50~900 단계 (CSS 변수 + JSON)
  python color_oracle.py selfcheck                        # 기준값·왕복 검산
"""
import json, math, sys

# ---------- sRGB 감마 ----------
def _lin(c):  return c / 12.92 if abs(c) <= 0.04045 else math.copysign(((abs(c) + 0.055) / 1.055) ** 2.4, c)
def _gam(c):  return 12.92 * c if abs(c) <= 0.0031308 else math.copysign(1.055 * abs(c) ** (1 / 2.4) - 0.055, c)
def _mul(M, v): return [M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2] for i in range(3)]

# ---------- HEX ----------
def hex_to_srgb(h):
    h = h.strip().lstrip('#')
    if len(h) == 3: h = ''.join(c * 2 for c in h)
    if len(h) not in (6, 8): raise ValueError(f"HEX 형식 오류: {h}")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

def srgb_to_hex(rgb):
    return '#' + ''.join(f"{round(min(1, max(0, c)) * 255):02x}" for c in rgb)

# ---------- OKLab (Ottosson, sRGB 선형 기준 행렬) ----------
_M1 = [[0.4122214708, 0.5363325363, 0.0514459929],
       [0.2119034982, 0.6806995451, 0.1073969566],
       [0.0883024619, 0.2817188376, 0.6299787005]]
_M2 = [[0.2104542553, 0.7936177850, -0.0040720468],
       [1.9779984951, -2.4285922050, 0.4505937099],
       [0.0259040371, 0.7827717662, -0.8086757660]]
_M2i = [[1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480]]
_M1i = [[4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010]]

def srgb_to_oklab(rgb):
    l = [_lin(c) for c in rgb]
    lms = _mul(_M1, l)
    return _mul(_M2, [math.copysign(abs(x) ** (1 / 3), x) for x in lms])

def oklab_to_srgb(lab):
    lms_ = _mul(_M2i, lab)
    return [_gam(c) for c in _mul(_M1i, [x ** 3 for x in lms_])]

# ---------- CIELAB (D50) — CSS Color 4: sRGB(D65) → XYZ D65 → Bradford → XYZ D50 → Lab ----------
_RGB2XYZ = [[0.41239079926595934, 0.357584339383878, 0.1804807884018343],
            [0.21263900587151027, 0.715168678767756, 0.07219231536073371],
            [0.01933081871559182, 0.11919477979462598, 0.9505321522496607]]
_XYZ2RGB = [[3.2409699419045226, -1.537383177570094, -0.4986107602930034],
            [-0.9692436362808796, 1.8759675015077202, 0.04155505740717559],
            [0.05563007969699366, -0.20397695888897652, 1.0569715142428786]]
_D65toD50 = [[1.0479298208405488, 0.022946793341019088, -0.05019222954313557],
             [0.029627815688159344, 0.990434484573249, -0.01707382502938514],
             [-0.009243058152591178, 0.015055144896577895, 0.7518742899580008]]
_D50toD65 = [[0.9554734527042182, -0.023098536874261423, 0.0632593086610217],
             [-0.028369706963208136, 1.0099954580058226, 0.021041398966943008],
             [0.012314001688319899, -0.020507696433477912, 1.3303659366080753]]
_D50 = [0.3457 / 0.3585, 1.0, (1 - 0.3457 - 0.3585) / 0.3585]
_e, _k = 216 / 24389, 24389 / 27

def srgb_to_lab(rgb):
    xyz = _mul(_D65toD50, _mul(_RGB2XYZ, [_lin(c) for c in rgb]))
    f = [(v / w) ** (1 / 3) if v / w > _e else (_k * v / w + 16) / 116 for v, w in zip(xyz, _D50)]
    return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])]

def lab_to_srgb(lab):
    L, a, b = lab
    f1 = (L + 16) / 116; f0 = a / 500 + f1; f2 = f1 - b / 200
    x = f0 ** 3 if f0 ** 3 > _e else (116 * f0 - 16) / _k
    y = ((L + 16) / 116) ** 3 if L > _k * _e else L / _k
    z = f2 ** 3 if f2 ** 3 > _e else (116 * f2 - 16) / _k
    xyz = [x * _D50[0], y * _D50[1], z * _D50[2]]
    return [_gam(c) for c in _mul(_XYZ2RGB, _mul(_D50toD65, xyz))]

# ---------- 직교 ↔ 원통 ----------
def to_polar(lab):
    L, a, b = lab; C = math.hypot(a, b); H = math.degrees(math.atan2(b, a)) % 360
    return [L, C, H]

def to_rect(lch):
    L, C, H = lch; r = math.radians(H)
    return [L, C * math.cos(r), C * math.sin(r)]

# ---------- 색역 매핑 (CSS Color 4) ----------
def _in_gamut(rgb, eps=1e-6): return all(-eps <= c <= 1 + eps for c in rgb)
def _clip(rgb): return [min(1, max(0, c)) for c in rgb]
def _deok(a, b):
    p, q = srgb_to_oklab(a), srgb_to_oklab(b)
    return math.dist(p, q)

def oklch_to_srgb_mapped(lch):
    """밝기·색상은 고정하고 채도만 줄여 sRGB 안으로. 반환: (rgb, 매핑했는지)"""
    L, C, H = lch
    if L >= 1: return [1, 1, 1], L > 1
    if L <= 0: return [0, 0, 0], L < 0
    rgb = oklab_to_srgb(to_rect([L, C, H]))
    if _in_gamut(rgb): return rgb, False
    if _deok(_clip(rgb), rgb) < 0.02: return _clip(rgb), True
    lo, hi = 0.0, C
    while hi - lo > 1e-4:
        mid = (lo + hi) / 2
        cand = oklab_to_srgb(to_rect([L, mid, H]))
        if _in_gamut(cand): lo = mid; continue
        if _deok(_clip(cand), cand) < 0.02: lo = mid
        else: hi = mid
    return _clip(oklab_to_srgb(to_rect([L, lo, H]))), True

# ---------- 공개 API (LLM 도구로 노출할 함수) ----------
def hex2oklch(h):
    L, C, H = to_polar(srgb_to_oklab(hex_to_srgb(h)))
    return {"L": round(L, 4), "C": round(C, 4), "H": round(H, 2) if C > 1e-4 else None,
            "css": f"oklch({L:.4f} {C:.4f} {H if C > 1e-4 else 0:.2f})"}

def oklch2hex(L, C, H):
    rgb, mapped = oklch_to_srgb_mapped([L, C, H])
    return {"hex": srgb_to_hex(rgb), "gamut_mapped": mapped}

def hex2lch(h):
    L, C, H = to_polar(srgb_to_lab(hex_to_srgb(h)))
    return {"L": round(L, 2), "C": round(C, 2), "H": round(H, 2) if C > 1e-3 else None,
            "css": f"lch({L:.2f} {C:.2f} {H if C > 1e-3 else 0:.2f})"}

def lch2hex(L, C, H):
    rgb = lab_to_srgb(to_rect([L, C, H]))
    if _in_gamut(rgb): return {"hex": srgb_to_hex(rgb), "gamut_mapped": False}
    # LCH 입력도 OKLCH 공간에서 같은 방식으로 매핑 (CSS Color 4)
    ok = to_polar(srgb_to_oklab(rgb))
    rgb2, _ = oklch_to_srgb_mapped(ok)
    return {"hex": srgb_to_hex(rgb2), "gamut_mapped": True}

# 50~900 단계: 밝기는 고정 사다리, 색상은 브랜드 H 고정, 채도는 양 끝에서 줄임
STEPS = {50: .97, 100: .93, 200: .87, 300: .79, 400: .70, 500: .61, 600: .52, 700: .43, 800: .34, 900: .25}

def scale(h, name="brand"):
    base = hex2oklch(h); Lb, Cb, Hb = base["L"], base["C"], base["H"] or 0
    nearest = min(STEPS, key=lambda s: abs(STEPS[s] - Lb))
    out = {}
    for s, L in STEPS.items():
        if s == nearest:                       # 브랜드 원색은 그 단계에 그대로 둔다
            out[s] = {"hex": h.lower() if h.startswith('#') else '#' + h.lower(), "oklch": base["css"], "gamut_mapped": False, "brand": True}
            continue
        # 채도: 브랜드 채도 × (밝기 양 끝에서 0으로 줄어드는 곡선)
        w = max(0.0, 1 - ((L - Lb) / (1.0 - Lb if L > Lb else Lb - 0.12)) ** 2)
        C = Cb * (0.18 + 0.82 * w)
        r = oklch2hex(L, C, Hb)
        out[s] = {"hex": r["hex"], "oklch": f"oklch({L:.2f} {C:.4f} {Hb:.2f})", "gamut_mapped": r["gamut_mapped"], "brand": False}
    css = "\n".join(f"  --{name}-{s}: {v['hex']};  /* {v['oklch']}{' · 브랜드 원색' if v['brand'] else ''}{' · 색역 매핑' if v['gamut_mapped'] else ''} */" for s, v in out.items())
    return {"name": name, "base": h, "base_oklch": base["css"], "brand_step": nearest, "steps": out, "css": ":root {\n" + css + "\n}"}

# ---------- 자가 검산 ----------
def selfcheck():
    ok = True
    def chk(name, cond, detail):
        nonlocal ok; ok &= cond; print(("PASS " if cond else "FAIL ") + name + "  " + detail)
    # 기준값: Ottosson 원문 sRGB 빨강 · CSS Color 4 예시
    r = hex2oklch("#ff0000"); chk("OKLCH 빨강", abs(r["L"] - 0.628) < 1e-3 and abs(r["C"] - 0.2577) < 1e-3 and abs(r["H"] - 29.23) < 0.05, r["css"])
    w = hex2oklch("#ffffff"); chk("OKLCH 흰색 L=1, C=0", abs(w["L"] - 1) < 1e-4 and w["C"] < 1e-4, w["css"])
    l = hex2lch("#ff0000"); chk("LCH 빨강 (D50)", abs(l["L"] - 54.29) < 0.05 and abs(l["C"] - 106.84) < 0.1 and abs(l["H"] - 40.85) < 0.1, l["css"])
    lw = hex2lch("#ffffff"); chk("LCH 흰색 L=100", abs(lw["L"] - 100) < 0.01 and lw["C"] < 0.01, lw["css"])
    # 왕복: 4,096색 (4비트 간격) HEX → OKLCH → HEX, HEX → LCH → HEX 모두 원래 값
    bad_ok = bad_l = 0
    for R in range(0, 256, 17):
        for G in range(0, 256, 17):
            for B in range(0, 256, 17):
                h = f"#{R:02x}{G:02x}{B:02x}"
                o = to_polar(srgb_to_oklab(hex_to_srgb(h)))
                bad_ok += srgb_to_hex(oklab_to_srgb(to_rect(o))) != h
                c = to_polar(srgb_to_lab(hex_to_srgb(h)))
                bad_l += srgb_to_hex(lab_to_srgb(to_rect(c))) != h
    chk("왕복 OKLCH 4,096색", bad_ok == 0, f"불일치 {bad_ok}")
    chk("왕복 LCH 4,096색", bad_l == 0, f"불일치 {bad_l}")
    # 색역 매핑: 범위 밖 요청은 반드시 sRGB 안의 HEX로, 밝기는 유지
    g = oklch2hex(0.7, 0.4, 196); L2 = hex2oklch(g["hex"])["L"]
    chk("색역 매핑 (C=0.4 요청)", g["gamut_mapped"] and abs(L2 - 0.7) < 0.01, f"{g['hex']} → L {L2}")
    print("\n결과:", "전부 통과" if ok else "실패 있음"); return ok

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit()
    cmd = a[0]
    if cmd == "selfcheck": sys.exit(0 if selfcheck() else 1)
    elif cmd == "hex2oklch": print(json.dumps(hex2oklch(a[1]), ensure_ascii=False))
    elif cmd == "hex2lch": print(json.dumps(hex2lch(a[1]), ensure_ascii=False))
    elif cmd == "oklch2hex": print(json.dumps(oklch2hex(*map(float, a[1:4])), ensure_ascii=False))
    elif cmd == "lch2hex": print(json.dumps(lch2hex(*map(float, a[1:4])), ensure_ascii=False))
    elif cmd == "scale":
        name = a[a.index("--name") + 1] if "--name" in a else "brand"
        r = scale(a[1], name); print(r["css"])
    else: print(__doc__)
