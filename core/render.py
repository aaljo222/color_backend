"""core/render.py — 무료 단계 '기본 그림': 팔레트를 면적비 그대로 색면 띠로 그린다.
결정론(시드 = cache_key) · 외부 모델 없음 · 비용 0 · 정의상 팔레트와 일치(ΔE00 ≈ 0).
"""
from __future__ import annotations
import hashlib
import numpy as np
from PIL import Image, ImageFilter
from core.color import hex2lab, lab2rgb, lab2lch, lch2lab


def _seed(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def render_color_field(palette: list[dict], key: str, w: int = 720, h: int = 900, drift=None) -> Image.Image:
    """drift=(dL, C배율, dh°): 이미지 모델의 색 틀어짐을 흉내 내는 테스트용 옵션."""
    rng = np.random.default_rng(_seed(key))
    labs = []
    for p in palette:
        lab = hex2lab(p["hex"])
        if drift:
            L, C, hh = lab2lch(lab)
            lab = lch2lab((L + drift[0], C * drift[1], hh + drift[2]))
        labs.append(lab)
    bounds = np.cumsum([0] + [p["area_ratio"] for p in palette]) * h
    phase = rng.uniform(0, 2 * np.pi)
    rows = np.arange(h)[:, None] + (h * 0.012) * np.sin(np.arange(w)[None, :] / (w / 18) + phase)
    lab_img = np.empty((h, w, 3))
    lab_img[:] = labs[-1]
    for i, lab in enumerate(labs):
        lab_img[(rows >= bounds[i]) & (rows < bounds[i + 1])] = lab
    lab_img[rows < 0] = labs[0]
    lab_img += rng.normal(0, 1.2, lab_img.shape)               # 붓결 질감
    rgb = (np.clip(lab2rgb(lab_img), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(rgb).filter(ImageFilter.GaussianBlur(2.0))
