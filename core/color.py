"""core/color.py — sRGB(D65) ↔ CIELAB ↔ LCh, CIEDE2000, 색역 클리핑.
모든 함수는 순수 함수(같은 입력 → 같은 출력).
CIEDE2000 은 Sharma·Wu·Dalal(2005) 표준 시험쌍으로 tests/test_color.py 에서 검증한다.
"""
from __future__ import annotations
import math
import numpy as np

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_WP = np.array([0.95047, 1.0, 1.08883])
_D = 6 / 29


def _lin(c): return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
def _gam(c): return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(np.clip(c, 0, None), 1 / 2.4) - 0.055)
def _f(t): return np.where(t > _D ** 3, np.cbrt(t), t / (3 * _D * _D) + 4 / 29)
def _fi(t): return np.where(t > _D, t ** 3, 3 * _D * _D * (t - 4 / 29))


def hex2rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0


def rgb2hex(rgb) -> str:
    r = np.clip(np.round(np.asarray(rgb) * 255), 0, 255).astype(int)
    return "#%02X%02X%02X" % tuple(r)


def rgb2lab(rgb) -> np.ndarray:
    rgb = np.asarray(rgb, float)
    X = (_lin(rgb) @ _M.T) / _WP
    fx, fy, fz = _f(X[..., 0]), _f(X[..., 1]), _f(X[..., 2])
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], -1)


def lab2linear(lab) -> np.ndarray:
    lab = np.asarray(lab, float)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    X = np.stack([_fi(fx), _fi(fy), _fi(fz)], -1) * _WP
    return X @ _MI.T


def lab2rgb(lab) -> np.ndarray:
    return _gam(lab2linear(lab))


def hex2lab(h: str) -> np.ndarray: return rgb2lab(hex2rgb(h))
def lab2hex(lab) -> str: return rgb2hex(np.clip(lab2rgb(lab), 0, 1))


def lab2lch(lab):
    L, a, b = [float(x) for x in lab]
    return (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360)


def lch2lab(lch) -> np.ndarray:
    L, C, h = lch
    r = math.radians(h)
    return np.array([L, C * math.cos(r), C * math.sin(r)])


def in_gamut(lab, eps: float = 1e-4) -> bool:
    lin = lab2linear(lab)
    return bool(np.all(lin >= -eps) and np.all(lin <= 1 + eps))


def lch_to_hex_clipped(lch) -> tuple[str, float]:
    """명도·색상각은 유지하고 채도만 줄여 sRGB 색역 안으로 (이분 탐색, 결정론). → (HEX, 실제 C)"""
    L, C, h = lch
    if in_gamut(lch2lab((L, C, h))):
        return lab2hex(lch2lab((L, C, h))), C
    lo, hi = 0.0, C
    for _ in range(40):
        mid = (lo + hi) / 2
        if in_gamut(lch2lab((L, mid, h))):
            lo = mid
        else:
            hi = mid
    return lab2hex(lch2lab((L, lo, h))), lo


def delta_e_2000(l1, l2, kL: float = 1, kC: float = 1, kH: float = 1) -> float:
    L1, a1, b1 = [float(x) for x in l1]
    L2, a2, b2 = [float(x) for x in l2]
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0.0
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dth = 30 * math.exp(-((hbp - 275) / 25) ** 2)
    RC = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    SL = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    SC = 1 + 0.045 * Cbp
    SH = 1 + 0.015 * Cbp * T
    RT = -math.sin(math.radians(2 * dth)) * RC
    return math.sqrt((dLp / (kL * SL)) ** 2 + (dCp / (kC * SC)) ** 2 + (dHp / (kH * SH)) ** 2
                     + RT * (dCp / (kC * SC)) * (dHp / (kH * SH)))
