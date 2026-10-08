"""core/llm.py — 특징 추출(LLM) + 임베딩.

LLM_MODE = gemini | stub   (GEMINI_API_KEY 없으면 자동 stub)
  - gemini: google-genai, temperature 0, response_schema(pydantic)로 형식 강제
  - stub  : KB 키워드 스캔 기반 결정론 추출 — 키 없이 개발·테스트용 (품질은 낮음)
"""
from __future__ import annotations
import os, logging
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger("uvicorn")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))


class AxisFeature(BaseModel):
    phrase: str = Field(default="", description="문장 근거의 짧은 구")
    label: str = Field(default="", description="KB 라벨 id 또는 빈 문자열")


class Features(BaseModel):
    emotion: AxisFeature
    time: AxisFeature
    space: AxisFeature
    memory_quality: AxisFeature
    objects: List[str] = Field(default_factory=list)
    memory_summary: str = ""


def llm_mode() -> str:
    m = os.getenv("LLM_MODE", "").lower()
    if m in ("gemini", "stub"):
        return m if (m == "stub" or os.getenv("GEMINI_API_KEY")) else "stub"
    return "gemini" if os.getenv("GEMINI_API_KEY") else "stub"


_client = None
def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def extract_features(masked_text: str, kb) -> Features:
    if llm_mode() == "stub":
        return _stub_extract(masked_text, kb)
    from google.genai import types
    from prompts.feature_prompt import build_feature_prompt
    labels = {a: [e["id"] for e in kb.by_axis[a]] for a in ("emotion", "time", "space", "quality")}
    labels["memory_quality"] = labels.pop("quality")
    cfg = types.GenerateContentConfig(
        system_instruction=build_feature_prompt(labels),
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=Features,
    )
    last = None
    for _ in range(2):                                   # 기획서 기준: 1회 재시도
        try:
            r = _gemini().models.generate_content(model=GEMINI_MODEL, contents=f'기억 문장: "{masked_text}"', config=cfg)
            if getattr(r, "parsed", None) is not None:
                return r.parsed if isinstance(r.parsed, Features) else Features.model_validate(r.parsed)
            return Features.model_validate_json(r.text)
        except Exception as ex:
            last = ex
            logger.warning(f"[LLM] 추출 실패 재시도: {type(ex).__name__}")
    raise RuntimeError(f"특징 추출 실패: {last}")


def _stub_extract(text: str, kb) -> Features:
    """키 없이 동작하는 결정론 추출: 축별로 KB 키워드가 처음 등장하는 위치 주변을 phrase 로."""
    def pick(axis):
        best = None
        for e in kb.by_axis[axis]:
            for k in e.get("keywords", []):
                i = text.find(k)
                if i >= 0 and (best is None or i < best[0]):
                    best = (i, k, e["id"])
        if best:
            return AxisFeature(phrase=best[1], label=best[2])
        return AxisFeature(phrase=text[:20], label="")
    return Features(emotion=pick("emotion"), time=pick("time"), space=pick("space"),
                    memory_quality=pick("quality"), objects=[], memory_summary=text[:30])


def embed_texts(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    from google.genai import types
    r = _gemini().models.embed_content(
        model=EMBED_MODEL, contents=texts,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=EMBED_DIM))
    return [e.values for e in r.embeddings]
