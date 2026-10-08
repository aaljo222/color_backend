"""core/pipeline.py — 기억 문장 → 4색 표본 (마스킹 → 특징 추출 → KB 해석 → LCh 합성 → 그림 → 검증)."""
from __future__ import annotations
import os, logging
from typing import Callable, Optional
from PIL import Image
from core.kb import get_resolver
from core.llm import extract_features, llm_mode
from core.pii import mask
from core.synth import synthesize, ENGINE_VERSION
from core.render import render_color_field
from core.verify import verify, feedback

logger = logging.getLogger("uvicorn")
MAX_ATTEMPTS = int(os.getenv("VERIFY_MAX_ATTEMPTS", "3"))

# 유료 단계 이미지 생성기 자리: (palette, cache_key, feedback_text) -> PIL.Image
ImageGenerator = Callable[[list, str, str], Image.Image]


def generate_with_verification(palette: list, key: str, generator: Optional[ImageGenerator] = None):
    """generator 가 없으면 무료 기본 그림. 있으면 생성→판정→수정지시→재생성, N회 실패 시 기본 그림으로 대체."""
    if generator is None:
        img = render_color_field(palette, key)
        return img, {**verify(palette, img), "attempts": 1, "renderer": "code"}
    fb = ""
    for n in range(1, MAX_ATTEMPTS + 1):
        img = generator(palette, key, fb)
        res = verify(palette, img)
        if res["status"] == "PASS":
            return img, {**res, "attempts": n, "renderer": "model"}
        fb = feedback(res)
        logger.info(f"[verify] FAIL {n}/{MAX_ATTEMPTS}: {fb}")
    img = render_color_field(palette, key)
    return img, {**verify(palette, img), "attempts": MAX_ATTEMPTS, "renderer": "code-fallback"}


def analyze(text: str, generator: Optional[ImageGenerator] = None, cache: Optional[dict] = None) -> dict:
    resolver = get_resolver()
    kb = resolver.kb
    protect = {k for e in kb.items for k in e.get("keywords", [])}
    masked, mask_stats = mask(text, protect=protect)
    feats = extract_features(masked, kb)
    res = {
        "emotion": resolver.resolve("emotion", feats.emotion.phrase, feats.emotion.label),
        "time": resolver.resolve("time", feats.time.phrase, feats.time.label),
        "space": resolver.resolve("space", feats.space.phrase, feats.space.label),
        "quality": resolver.resolve("quality", feats.memory_quality.phrase, feats.memory_quality.label),
    }
    syn = synthesize(res, kb)
    key = syn["cache_key"]
    if cache is not None and key in cache:
        hit = dict(cache[key]); hit["cache_hit"] = True; hit["memory_summary"] = feats.memory_summary or hit.get("memory_summary", "")
        return hit
    img, ver = generate_with_verification(syn["palette"], key, generator)
    out = {
        "specimen_hash": f"MaC-{key[:12]}",
        "cache_key": key,
        "kb_version": kb.version,
        "engine_version": ENGINE_VERSION,
        "llm_mode": llm_mode(),
        "memory_summary": feats.memory_summary,
        "palette": syn["palette"],
        "verification": {k: ver[k] for k in ("status", "max_de00", "max_ratio_err", "attempts", "renderer", "criteria")},
        "pii_masked": mask_stats,
        "cache_hit": False,
        "_image": img,                        # 라우터가 저장 후 제거
        "_log": {"features": feats.model_dump(), "verify_rows": ver["rows"], "masked_text_len": len(masked)},
    }
    if cache is not None:
        cache[key] = {k: v for k, v in out.items() if not k.startswith("_")}
    return out
