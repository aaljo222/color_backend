# -*- coding: utf-8 -*-
"""oracle/similar.py — 색 문장 '비슷한 문장 추천'. 찾기만 하고, 결과는 절대 바꾸지 않는다.

원칙 (해시 vs 임베딩)
  같은 문장   = 정규화 키(문자열)로 찾는다 → palette.answer 의 1단계 캐시
  비슷한 문장 = 이 모듈. 점수가 기준선을 넘는 저장 문장을 '후보'로 보여 줄 뿐이다.
               사용자가 후보를 누르면 그 문장의 키로 저장 결과를 불러온다 (LLM 0회).

방법 (SIMILAR_METHOD = auto | ngram | embedding, 기본 auto)
  ngram     : 글자 2·3-gram 코사인. 키 없이 항상 동작. 글자가 겹쳐야 찾는다.
  embedding : 문장 임베딩 코사인. Supabase 면 color_prompts.embedding + RPC match_color_prompts (pgvector).
  auto      : 임베딩 제공자 키가 있으면 embedding, 아니면 ngram.
임베딩 제공자 (Anthropic 은 자체 임베딩 모델이 없다 — 공식 문서가 Voyage AI 를 안내)
  voyage : VOYAGE_API_KEY · 모델 VOYAGE_MODEL(기본 voyage-4) · input_type document/query 구분
  gemini : GEMINI_API_KEY · gemini-embedding-001
  둘 다 있으면 voyage. SIMILAR_PROVIDER 로 강제할 수 있다.
  차원 SIMILAR_DIM (기본 1024) = DB 컬럼 vector(1024) 와 같아야 한다.
  ★ 벡터마다 만든 모델 이름(embedding_model)을 같이 저장하고, 같은 모델끼리만 비교한다.
    모델을 바꾸면 좌표가 전부 바뀌므로 섞어 비교하면 점수가 무의미하다 → scripts/embed_prompts.py 로 다시 채운다.
기준선 SIMILAR_MIN (기본 ngram 0.35 · embedding 0.80)
  ngram 0.35: 예시 13쌍에서 "커피 한 잔↔녹차 한 잔"(0.20)은 막고 "덕수궁 돌담길↔돌담길 산책"(0.38)은 통과.
  "비 오는 창밖↔창밖에 비가 내린다"(0.10)처럼 어순·어미가 바뀌면 ngram 은 못 찾는다 → 임베딩이 필요한 이유.
  embedding 0.80 은 아직 실측 전 기본값 — 임베딩을 켜면 사용 데이터로 다시 맞출 것.
규칙(HEX·OKLCH 숫자·브랜드 단계)으로 풀린 문장은 후보에서 뺀다: 계산이 즉시라 추천할 이유가 없고,
'#2f5d50'과 '#2f5d51'처럼 글자는 비슷해도 다른 색이라 혼란만 준다.
"""
from __future__ import annotations
import logging, math, os, time
from collections import Counter

from oracle import color_abstraction as ca
from oracle.store import get_store

logger = logging.getLogger("uvicorn")
DEFAULT_MIN = {"ngram": 0.35, "embedding": 0.80}
MAX_CANDIDATES = 500          # ngram 은 서버에서 직접 비교 — 최근·인기 문장 이만큼만 본다


DIM = int(os.getenv("SIMILAR_DIM", "1024"))


def provider() -> str | None:
    p = (os.getenv("SIMILAR_PROVIDER") or "").lower()
    if p in ("voyage", "gemini"):
        return p if os.getenv(f"{p.upper()}_API_KEY") else None
    if os.getenv("VOYAGE_API_KEY"):
        return "voyage"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None


def model_name() -> str | None:
    p = provider()
    if p == "voyage":
        return f"voyage:{os.getenv('VOYAGE_MODEL', 'voyage-4')}:{DIM}"
    if p == "gemini":
        return f"gemini:{os.getenv('GEMINI_EMBED_MODEL', 'gemini-embedding-001')}:{DIM}"
    return None


def method() -> str:
    m = (os.getenv("SIMILAR_METHOD") or "auto").lower()
    if m == "ngram":
        return "ngram"
    return "embedding" if provider() else "ngram"


def threshold(m: str) -> float:
    v = os.getenv("SIMILAR_MIN")
    return float(v) if v else DEFAULT_MIN[m]


# ── ngram ────────────────────────────────────────────────────────────────
def _grams(s: str) -> Counter:
    s = ca.normalize(s).replace(" ", "")
    return Counter(s[i:i + n] for n in (2, 3) for i in range(len(s) - n + 1))


def ngram_sim(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    dot = sum(c * gb[g] for g, c in ga.items() if g in gb)
    return dot / (math.sqrt(sum(c * c for c in ga.values())) * math.sqrt(sum(c * c for c in gb.values())))


# ── embedding ────────────────────────────────────────────────────────────
_voyage = None


def _embed_voyage(texts: list[str], kind: str) -> list[list[float]]:
    global _voyage
    if _voyage is None:
        import voyageai
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"], max_retries=2, timeout=20)
    r = _voyage.embed(texts, model=os.getenv("VOYAGE_MODEL", "voyage-4"),
                      input_type=kind, output_dimension=DIM)          # kind = "query" | "document"
    return [list(v) for v in r.embeddings]


def _embed_gemini(texts: list[str], kind: str) -> list[list[float]]:
    from google import genai
    from google.genai import types
    task = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
    r = genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.embed_content(
        model=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"), contents=texts,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM))
    return [list(e.values) for e in r.embeddings]


def embed_many(texts: list[str], kind: str = "document") -> list[list[float]]:
    """여러 문장 임베딩 (예외를 그대로 올린다 — 채우기 스크립트용)."""
    p = provider()
    if p == "voyage":
        return _embed_voyage(texts, kind)
    if p == "gemini":
        return _embed_gemini(texts, kind)
    raise RuntimeError("임베딩 제공자 키가 없습니다 (VOYAGE_API_KEY 또는 GEMINI_API_KEY)")


def embed(text: str, kind: str = "query") -> list[float] | None:
    """임베딩 1개. 제공자가 없거나 실패하면 None (호출한 쪽은 ngram 으로 내려간다)."""
    if method() != "embedding":
        return None
    try:
        return embed_many([text], kind)[0]
    except Exception as ex:
        logger.warning(f"[similar] 임베딩 실패 → ngram: {type(ex).__name__}")
        return None


def _cos(a, b) -> float:
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


# ── 후보 ─────────────────────────────────────────────────────────────────
_cand, _cand_t = None, 0.0


def _candidates(store) -> list[dict]:
    """비교 대상 저장 문장 (규칙 문장 제외). Supabase 는 60초 캐시."""
    global _cand, _cand_t
    if store.name == "memory":
        return [r for r in store.rows() if r.get("source") != "rule"]
    if _cand is not None and time.time() - _cand_t < 60:
        return _cand
    _cand, _cand_t = store.rows(limit=MAX_CANDIDATES, exclude_source="rule"), time.time()
    return _cand


def invalidate():
    global _cand
    _cand = None


def find(text: str, k: int = 3, exclude_key: str | None = None) -> dict:
    """text 와 비슷한 저장 문장 상위 k개 (점수 ≥ 기준선). 결과 형식은 방법과 무관하게 같다."""
    text = (text or "").strip()
    store = get_store()
    exclude_key = exclude_key or ca.normalize(text)
    m = method()
    items: list[dict] = []
    if len(text) >= 2:
        q = embed(text) if m == "embedding" else None
        if q is None:
            m = "ngram"
        tau = threshold(m)
        if m == "embedding" and store.name == "supabase":
            items = store.match_embedding(q, k + 1, tau, model_name())
        else:
            for r in _candidates(store):
                if m == "embedding":
                    v = r.get("embedding")
                    if not v or r.get("embedding_model") != model_name():
                        continue                                   # 다른 모델이 만든 벡터는 비교하지 않는다
                    s = _cos(q, v)
                else:
                    s = ngram_sim(text, r["prompt"])
                if s >= tau:
                    items.append({**r, "score": s})
        items = [x for x in items if x["key"] != exclude_key]
        items.sort(key=lambda x: (-x["score"], x["key"]))          # 같은 점수면 키 순 → 순서도 결정론
        items = items[:k]
    else:
        tau = threshold(m)
    return {"method": m, "threshold": tau, "model": model_name() if m == "embedding" else None,
            "items": [{"key": x["key"], "prompt": x["prompt"], "source": x.get("source"),
                       "score": round(float(x["score"]), 3), "palette": x.get("palette") or []} for x in items]}


def remember(key: str, prompt: str) -> None:
    """새 문장을 저장할 때 임베딩도 남긴다 (임베딩을 쓸 때만). 실패해도 저장은 그대로."""
    invalidate()
    v = embed(prompt, kind="document")
    if v is not None:
        get_store().set_embedding(key, v, model_name())
