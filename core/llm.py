"""core/llm.py — 특징 추출(LLM) + 임베딩(선택).

LLM_MODE = claude | stub   (ANTHROPIC_API_KEY 없으면 자동 stub)
  - claude: Anthropic Messages API, temperature 0, 도구 하나(report_features)를 강제 호출해
            입력 스키마(= Features 의 JSON 스키마)로 형식을 고정한다. 색 값은 묻지 않는다.
  - stub  : KB 키워드 스캔 기반 결정론 추출 — 키 없이 개발·테스트용 (품질은 낮음)

임베딩(RETRIEVER=embedding|supabase)은 Claude API 에 임베딩 엔드포인트가 없어 별도 제공자를 쓴다.
  지금은 GEMINI_API_KEY 가 있을 때만 Gemini 임베딩을 쓰고, 없으면 kb.make_retriever 가 ngram 으로 대체한다.
"""
from __future__ import annotations
import os, logging
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger("uvicorn")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
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
    if m == "stub":
        return "stub"
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else "stub"


_client = None
def _claude():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=40.0, max_retries=1)
    return _client


def _tool(labels: dict) -> dict:
    """Features 스키마를 도구 입력 스키마로. label 은 축별 닫힌 목록(+빈 문자열)으로 제한."""
    def axis(ids):
        return {"type": "object", "properties": {
            "phrase": {"type": "string", "description": "문장에 근거한 짧은 구"},
            "label": {"type": "string", "enum": list(ids) + [""]}}, "required": ["phrase", "label"]}
    return {
        "name": "report_features",
        "description": "기억 문장의 네 축 특징을 보고한다. 색 이름·HEX·숫자 색값은 넣지 않는다.",
        "input_schema": {"type": "object", "properties": {
            "emotion": axis(labels["emotion"]), "time": axis(labels["time"]), "space": axis(labels["space"]),
            "memory_quality": axis(labels["memory_quality"]),
            "objects": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "memory_summary": {"type": "string"}},
            "required": ["emotion", "time", "space", "memory_quality", "objects", "memory_summary"]},
    }


def extract_features(masked_text: str, kb) -> Features:
    if llm_mode() == "stub":
        return _stub_extract(masked_text, kb)
    from prompts.feature_prompt import build_feature_prompt
    labels = {a: [e["id"] for e in kb.by_axis[a]] for a in ("emotion", "time", "space", "quality")}
    labels["memory_quality"] = labels.pop("quality")
    tool = _tool(labels)
    last = None
    for _ in range(2):                                   # 기획서 기준: 1회 재시도
        try:
            r = _claude().messages.create(
                model=CLAUDE_MODEL, max_tokens=800, temperature=0,
                system=build_feature_prompt(labels), tools=[tool],
                tool_choice={"type": "tool", "name": "report_features"},
                messages=[{"role": "user", "content": f'기억 문장: "{masked_text}"'}])
            block = next(b for b in r.content if b.type == "tool_use")
            return Features.model_validate(block.input)
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
    """선택 기능: 임베딩 검색용. GEMINI_API_KEY 와 google-genai 가 있어야 한다."""
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("임베딩 제공자 미설정 (GEMINI_API_KEY 필요) — RETRIEVER=ngram 을 쓰세요")
    from google import genai
    from google.genai import types
    r = genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.embed_content(
        model=EMBED_MODEL, contents=texts,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=EMBED_DIM))
    return [e.values for e in r.embeddings]
