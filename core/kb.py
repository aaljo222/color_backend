"""core/kb.py — Color KB 로드 + 해석(키워드 → LLM 라벨 → 검색 ≥ τ → 기본 톤).

검색기(Retriever)는 교체 가능:
  - NgramRetriever      : 문자 2·3-gram TF-IDF. 외부 의존 없음. 동의어를 못 잡는다(백서 E3).
  - EmbeddingRetriever  : data/kb_embeddings.json(scripts/build_kb_embeddings.py가 생성) + Gemini 임베딩.
  - SupabaseRetriever   : pgvector RPC match_color_kb (sql/schema.sql).
환경변수 RETRIEVER = ngram | embedding | supabase  (기본 ngram)
"""
from __future__ import annotations
import json, math, os, logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger("uvicorn")
KB_PATH = Path(os.getenv("KB_PATH", Path(__file__).resolve().parent.parent / "data" / "color_kb.json"))
AXES = ("emotion", "time", "space", "quality")


@dataclass(frozen=True)
class Resolution:
    axis: str
    phrase: str
    kb_id: str
    how: str          # keyword | label | retrieval | fallback
    score: float


class KB:
    def __init__(self, path: Path = KB_PATH):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.version: str = raw["version"]
        self.defaults: dict = raw["defaults"]
        self.items: list[dict] = raw["items"]
        self.by_id = {e["id"]: e for e in self.items}
        self.by_axis = {a: [e for e in self.items if e["axis"] == a] for a in AXES}

    def text_of(self, e: dict) -> str:
        return " ".join(e.get("keywords", [])) + " " + e.get("description", "")


# ── 검색기 ────────────────────────────────────────────────────────────────
def _ngrams(s: str, ns=(2, 3)) -> list[str]:
    s = s.replace(" ", "")
    return [s[i:i + n] for n in ns for i in range(len(s) - n + 1)]


class NgramRetriever:
    name = "ngram"

    def __init__(self, kb: KB):
        self.kb = kb
        docs = [kb.text_of(e) for e in kb.items]
        tfs, vocab = [], {}
        for d in docs:
            tf: dict[str, int] = {}
            for g in _ngrams(d):
                tf[g] = tf.get(g, 0) + 1
                vocab.setdefault(g, len(vocab))
            tfs.append(tf)
        n = len(docs)
        df = {g: sum(1 for tf in tfs if g in tf) for g in vocab}
        self.idf = {g: math.log((1 + n) / (1 + df[g])) + 1 for g in vocab}
        self.vocab = vocab
        self.mat = np.array([self._vec(tf) for tf in tfs])

    def _vec(self, tf: dict) -> np.ndarray:
        v = np.zeros(len(self.vocab))
        for g, c in tf.items():
            if g in self.vocab:
                v[self.vocab[g]] = c * self.idf[g]
        nrm = np.linalg.norm(v)
        return v / nrm if nrm else v

    def search(self, phrase: str, axis: str) -> list[tuple[float, str]]:
        tf: dict[str, int] = {}
        for g in _ngrams(phrase):
            tf[g] = tf.get(g, 0) + 1
        sims = self.mat @ self._vec(tf)
        out = [(float(sims[i]), e["id"]) for i, e in enumerate(self.kb.items) if e["axis"] == axis]
        return sorted(out, reverse=True)


class EmbeddingRetriever:
    """미리 계산한 KB 임베딩(data/kb_embeddings.json) + 질의 임베딩(Gemini)."""
    name = "embedding"

    def __init__(self, kb: KB, path: Optional[Path] = None):
        from core.llm import embed_texts  # 지연 import (키 없으면 사용 안 함)
        self._embed = embed_texts
        self.kb = kb
        path = path or KB_PATH.parent / "kb_embeddings.json"
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kb_version") != kb.version:
            logger.warning(f"[KB] 임베딩 파일 버전({data.get('kb_version')}) ≠ KB 버전({kb.version}) — 재생성 필요")
        self.ids = data["ids"]
        m = np.array(data["vectors"], float)
        self.mat = m / np.linalg.norm(m, axis=1, keepdims=True)

    def search(self, phrase: str, axis: str) -> list[tuple[float, str]]:
        q = np.array(self._embed([phrase], task="RETRIEVAL_QUERY")[0], float)
        q = q / (np.linalg.norm(q) or 1)
        sims = self.mat @ q
        out = [(float(s), i) for s, i in zip(sims, self.ids) if self.kb.by_id[i]["axis"] == axis]
        return sorted(out, reverse=True)


class SupabaseRetriever:
    """pgvector: sql/schema.sql 의 match_color_kb(query_embedding, match_axis, match_count)."""
    name = "supabase"

    def __init__(self, kb: KB):
        from core.llm import embed_texts
        from utils.supabase_client import supabase_admin
        if supabase_admin is None:
            raise RuntimeError("Supabase 미설정")
        self._embed, self._sb, self.kb = embed_texts, supabase_admin, kb

    def search(self, phrase: str, axis: str) -> list[tuple[float, str]]:
        q = self._embed([phrase], task="RETRIEVAL_QUERY")[0]
        res = self._sb.rpc("match_color_kb", {"query_embedding": q, "match_axis": axis, "match_count": 5}).execute()
        return [(float(r["similarity"]), r["id"]) for r in (res.data or [])]


# ── 해석기 ────────────────────────────────────────────────────────────────
class Resolver:
    def __init__(self, kb: KB, retriever, tau: float):
        self.kb, self.retriever, self.tau = kb, retriever, tau

    def resolve(self, axis: str, phrase: str, label: Optional[str] = None) -> Resolution:
        phrase = (phrase or "").strip()
        for e in self.kb.by_axis[axis]:                       # ① 키워드 (결정론)
            if any(k in phrase for k in e.get("keywords", [])):
                return Resolution(axis, phrase, e["id"], "keyword", 1.0)
        if label and label in self.kb.by_id and self.kb.by_id[label]["axis"] == axis:   # ② LLM 닫힌 라벨
            return Resolution(axis, phrase, label, "label", 1.0)
        if phrase:                                            # ③ 검색 ≥ τ
            try:
                ranked = self.retriever.search(phrase, axis)
            except Exception as ex:                           # 검색 장애 시 기본 톤으로 안전하게
                logger.warning(f"[KB] retriever 실패 → fallback: {type(ex).__name__}")
                ranked = []
            if ranked and ranked[0][0] >= self.tau:
                return Resolution(axis, phrase, ranked[0][1], "retrieval", round(ranked[0][0], 4))
            score = round(ranked[0][0], 4) if ranked else 0.0
        else:
            score = 0.0
        return Resolution(axis, phrase, self.kb.defaults[axis], "fallback", score)   # ④ 기본 톤


def make_retriever(kb: KB, kind: Optional[str] = None):
    kind = (kind or os.getenv("RETRIEVER") or "ngram").lower()
    try:
        if kind == "embedding":
            return EmbeddingRetriever(kb)
        if kind == "supabase":
            return SupabaseRetriever(kb)
    except Exception as ex:
        logger.warning(f"[KB] {kind} retriever 사용 불가({ex}) → ngram 으로 대체")
    return NgramRetriever(kb)


# ngram 0.25: data/goldset.jsonl 기준 오연결 0 이 되는 최저값 (scripts/eval_tau.py). embedding 값은 임베딩 생성 후 같은 스크립트로 다시 정할 것.
DEFAULT_TAU = {"ngram": 0.25, "embedding": 0.60, "supabase": 0.60}


@lru_cache(maxsize=1)
def get_resolver() -> Resolver:
    kb = KB()
    r = make_retriever(kb)
    tau = float(os.getenv("RETRIEVAL_TAU") or DEFAULT_TAU.get(r.name, 0.25))
    logger.info(f"[KB] {kb.version} · retriever={r.name} · τ={tau}")
    return Resolver(kb, r, tau)
