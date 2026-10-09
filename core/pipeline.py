"""core/pipeline.py — 기억 문장 → 4색 표본.

ENGINE_MODE (요청마다 engine 으로 바꿀 수 있음)
  palette     (eng-1.2) 마스킹 → 특징 추출 → KB 해석 + 사물 등급 + 정서 등급 → LCh 합성 → 그림 → 검증
  image_first (eng-2.0) 마스킹 → 특징 추출 → KB 해석(프롬프트 보강) → 그림 → 그림에서 HEX 측정 → 심사
"""
from __future__ import annotations
import os, logging
from typing import Callable, Optional
from PIL import Image
from core.kb import get_resolver
from core.llm import extract_features, llm_mode
from core.pii import mask
from core.synth import synthesize, ENGINE_VERSION
from core.objects import resolve_objects
from core.affect import compute as compute_affect
from core.render import render_color_field
from core.verify import verify, feedback
from core import image_first

logger = logging.getLogger("uvicorn")
MAX_ATTEMPTS = int(os.getenv("VERIFY_MAX_ATTEMPTS", "3"))
ENGINE_MODE = os.getenv("ENGINE_MODE", "palette")

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


def analyze(text: str, generator: Optional[ImageGenerator] = None, cache: Optional[dict] = None,
            engine: Optional[str] = None) -> dict:
    engine = engine or ENGINE_MODE
    resolver = get_resolver()
    kb = resolver.kb
    protect = {k for e in kb.items for k in e.get("keywords", [])}
    try:                                                # 사물 사전 낱말(수박·옥수수…)도 가리면 안 된다 — 사물 색이 사라진다
        from core.objects import _lexicon
        protect |= set(_lexicon())
    except Exception:
        pass
    masked, mask_stats = mask(text, protect=protect)
    feats = extract_features(masked, kb)
    res = {
        "emotion": resolver.resolve("emotion", feats.emotion.phrase, feats.emotion.label),
        "time": resolver.resolve("time", feats.time.phrase, feats.time.label),
        "space": resolver.resolve("space", feats.space.phrase, feats.space.label),
        "quality": resolver.resolve("quality", feats.memory_quality.phrase, feats.memory_quality.label),
    }
    objs = resolve_objects(feats.objects)               # 사물 → 등급 → 색 (사전 우선, 결정론)
    aff = compute_affect(feats.affect, kb.by_id[res["emotion"].kb_id])   # 쾌·각성 등급 → 채도 배율·명도 변화 (결정론)
    syn = synthesize(res, kb, objs, aff)
    version, extra = ENGINE_VERSION, {}
    if engine == "image_first":
        key = image_first.cache_key(masked, image_first.painter_name())
    else:
        key = syn["cache_key"]
    if cache is not None and key in cache:
        hit = dict(cache[key]); hit["cache_hit"] = True; hit["memory_summary"] = feats.memory_summary or hit.get("memory_summary", "")
        if key in image_first.IMAGE_CACHE:
            hit["_image"] = image_first.IMAGE_CACHE[key]          # 그림 먼저: 같은 기억 = 같은 그림
        return hit
    if engine == "image_first":
        out = image_first.run(masked, feats.memory_summary, res, kb, objs, aff, syn["palette"])
        syn = {**syn, "palette": out["palette"]}
        img, ver = out["image"], {**out["verification"], "rows": []}
        version = image_first.ENGINE_VERSION
        extra = {"image_tries": out["tries"], "painter": out["painter"]}
    else:
        img, ver = generate_with_verification(syn["palette"], key, generator)
    out = {
        "specimen_hash": f"MaC-{key[:12]}",
        "cache_key": key,
        "kb_version": kb.version,
        "engine_version": version,
        "llm_mode": llm_mode(),
        "memory_summary": feats.memory_summary,
        "palette": syn["palette"],
        "affect": syn["affect"],
        "verification": {k: ver[k] for k in ("status", "max_de00", "max_ratio_err", "attempts", "renderer", "criteria",
                                             "coverage", "review") if k in ver},
        "pii_masked": mask_stats,
        "cache_hit": False,
        "_image": img,                        # 라우터가 저장 후 제거
        "_log": {"features": {**feats.model_dump(), "resolved_objects": [[o.name, *o.descriptor, o.how] for o in objs], **extra},
                 "verify_rows": ver["rows"], "masked_text_len": len(masked)},   # 키 = generation_logs 열 이름 (새 열 추가 금지)
    }
    if cache is not None:
        cache[key] = {k: v for k, v in out.items() if not k.startswith("_")}
    return out
