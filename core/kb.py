"""core/kb.py — Color KB 로드 + 해석(키워드 → LLM 라벨 → 검색 ≥ τ → 기본 톤).

검색기(Retriever)는 교체 가능:
  - NgramRetriever      : 문자 2·3-gram TF-IDF. 외부 의존 없음. 동의어를 못 잡는다(백서 E3).
  - EmbeddingRetriever  : data/kb_embeddings.json(scripts/build_kb_embeddings.py가 생성) + Gemini 임베딩.
  - SupabaseRetriever   : pgvector RPC match_color_kb (sql/schema.sql).
환경변수 RETRIEVER = ngram | embedding | supabase  (기본 ngram)
  embedding = 테이블 mac_embeddings(core/vector_store.py, 지금 모델로 자동 생성) → 없으면 data/kb_embeddings.json
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
CUES_ON = os.getenv("CUES", "1") == "1"                  # 0 이면 kb-0.2.1 의 부분 문자열 키워드 (core/cues.py)
NEED_LEMMA = os.getenv("CORPUS_NEED_LEMMA", "1") == "1"  # 0 이면 ngram 검색 낱말 겹침 검사 끔
WEAK_FALLBACK = os.getenv("WEAK_FALLBACK", "0") == "1"   # 약한 낱말만 걸리고 문장으로도 못 정하면 그 낱말 항목으로 (기본: 기본 톤)


@dataclass(frozen=True)
class Resolution:
    axis: str
    phrase: str
    kb_id: str
    how: str          # keyword | label | corpus | retrieval | fallback
    score: float
    ref: str = ""     # how=corpus: 장면 문단 id (eng-2.2) · keyword: "kw:낱말" · fallback: "cue:막는 단서" (cues-0.1)


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
        from core.llm import embed_model_name
        if data.get("model") and data["model"] != embed_model_name():   # 다른 모델로 만든 파일이면 점수가 무의미
            raise RuntimeError(f"임베딩 파일 모델 {data['model']} ≠ 지금 {embed_model_name()} — build_kb_embeddings.py 다시")
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


class StoreRetriever:
    """KB 항목 임베딩을 테이블(mac_embeddings)에서 — 지금 서버 모델로 없으면 만들어 저장한다 (emb-1).
    질의도 같은 모델(oracle/similar.py)이라 파일 모델 불일치로 꺼지는 일이 없다."""
    name = "embedding"

    def __init__(self, kb: KB):
        from core import vector_store
        vec = vector_store.vectors("kb", [(e["id"], kb.text_of(e)) for e in kb.items])
        if vec is None:
            raise RuntimeError("임베딩 테이블 사용 불가 (키 없음·VECTOR_STORE=off·장애)")
        self.kb, self.ids, self._query = kb, [e["id"] for e in kb.items], vector_store.query
        m = np.array([vec[i] for i in self.ids], float)
        self.mat = m / np.linalg.norm(m, axis=1, keepdims=True)
        self.source = "store"

    def search(self, phrase: str, axis: str) -> list[tuple[float, str]]:
        q = np.array(self._query(phrase), float)
        sims = self.mat @ (q / (np.linalg.norm(q) or 1))
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
    """키워드 → 모델 라벨 → 코퍼스 장면 문단 ≥ τc (eng-2.2, rag 가 있을 때) → KB 설명 검색 ≥ τ → 기본 톤."""
    def __init__(self, kb: KB, retriever, tau: float, rag=None, cues="auto"):
        self.kb, self.retriever, self.tau, self.rag = kb, retriever, tau, rag
        if cues == "auto":                                    # cues-0.1: 낱말 경계·원형·약한 낱말·막는 단서 (core/cues.py)
            cues = None
            if CUES_ON:
                try:
                    from core.cues import Cues
                    cues = Cues(kb)
                except Exception as ex:
                    logger.warning(f"[KB] 단서 사전 사용 불가 → 부분 문자열 키워드: {type(ex).__name__}")
        self.cues = cues

    def _keyword(self, axis: str, phrase: str):
        """① 키워드. (결과 Resolution 또는 None, 막는 단서, 약한 낱말 후보)."""
        if self.cues is None:                                 # 예전 방식: 부분 문자열
            for e in self.kb.by_axis[axis]:
                if any(k in phrase for k in e.get("keywords", [])):
                    return Resolution(axis, phrase, e["id"], "keyword", 1.0), None, []
            return None, None, []
        from core.cues import analyze
        an = analyze(phrase)
        hits = self.cues.hits(axis, an)
        blocked = self.cues.blocked(axis, an)
        weak = list(dict.fromkeys(h.kb_id for h in hits if h.strength == "weak"))
        if blocked:
            return None, blocked, weak
        strong = [h for h in hits if h.strength != "weak"]
        ids = list(dict.fromkeys(h.kb_id for h in strong))
        if len(ids) > 1:                                      # 한 축에 여러 항목: 시간·장소를 직접 말한 낱말이 이긴다
            primary = list(dict.fromkeys(h.kb_id for h in strong if h.strength == "strong"))
            ids = primary or ids
        if len(ids) == 1:
            h = next(h for h in strong if h.kb_id == ids[0])
            return Resolution(axis, phrase, ids[0], "keyword", 1.0, f"kw:{h.keyword}"), None, weak
        if len(ids) > 1 and self.rag is not None:             # 그래도 여럿이면 문장 전체를 코퍼스에 물어 후보 중에서
            best = None
            for c in ids:
                hs = self.rag.search(phrase, axis=axis, kb_id=c, k=1)
                if hs and (best is None or hs[0].score > best[0]):
                    best = (hs[0].score, c)
            if best is not None and best[0] > 0:
                return Resolution(axis, phrase, best[1], "keyword", 1.0, "kw:" + "|".join(ids)), None, weak
        if len(ids) > 1 and axis != "emotion":
            return Resolution(axis, phrase, ids[0], "keyword", 1.0, "kw:" + "|".join(ids)), None, weak
        return None, None, weak

    def _overlaps(self, axis: str, phrase: str, doc: str) -> bool:
        """낱말 겹침 검사 (ngram 검색일 때만): 내용 형태소 원형이 하나도 안 겹치고 글자 조각('~던', '~에서')만
        비슷하면 받지 않는다. 감정 축에서는 문맥 따라 정서가 갈리는 낱말(아빠·눈물·혼자…)을 겹침으로 치지 않는다."""
        if not NEED_LEMMA or self.cues is None:
            return True
        from core.cues import content_lemmas
        emo = axis == "emotion"
        a = content_lemmas(phrase, emo, frozenset(self.cues.context))
        b = content_lemmas(doc, emo, frozenset(self.cues.context))
        if a is None or b is None:
            return True
        return bool((a & b) - self.cues.weak_lemmas(axis))       # 약한 낱말('이른' 등)만 겹친 건 겹침으로 치지 않는다

    def resolve(self, axis: str, phrase: str, label: Optional[str] = None) -> Resolution:
        phrase = (phrase or "").strip()
        kw, blocked, weak = self._keyword(axis, phrase) if phrase else (None, None, [])
        if kw is not None:                                    # ① 키워드 (결정론)
            return kw
        if label and label in self.kb.by_id and self.kb.by_id[label]["axis"] == axis:   # ② LLM 닫힌 라벨
            return Resolution(axis, phrase, label, "label", 1.0)
        if blocked:                                           # KB 에 없는 정서(불안·공포·갈등…) → 기본 톤
            return Resolution(axis, phrase, self.kb.defaults[axis], "fallback", 0.0, f"cue:{blocked}")
        if phrase and self.rag is not None:                   # ③ 코퍼스: 같은 항목을 여러 말투로 쓴 문단에서 찾는다
            try:
                hit = self.rag.resolve_axis(phrase, axis)
            except Exception as ex:
                logger.warning(f"[KB] 코퍼스 검색 실패 → KB 검색: {type(ex).__name__}")
                hit = None
            if hit is not None and getattr(self.rag, "method", "ngram") == "ngram" \
                    and not self._overlaps(axis, phrase, hit.passage["text"]):
                hit = None
            if hit is not None:
                return Resolution(axis, phrase, hit.passage["kb_id"], "corpus", hit.score, hit.passage["id"])
        if phrase:                                            # ④ KB 설명 검색 ≥ τ
            try:
                ranked = self.retriever.search(phrase, axis)
            except Exception as ex:                           # 검색 장애 시 기본 톤으로 안전하게
                logger.warning(f"[KB] retriever 실패 → fallback: {type(ex).__name__}")
                ranked = []
            if ranked and ranked[0][0] >= self.tau and (getattr(self.retriever, "name", "") != "ngram"
                                                        or self._overlaps(axis, phrase, self.kb.text_of(self.kb.by_id[ranked[0][1]]))):
                return Resolution(axis, phrase, ranked[0][1], "retrieval", round(ranked[0][0], 4))
            score = round(ranked[0][0], 4) if ranked else 0.0
        else:
            score = 0.0
        if WEAK_FALLBACK and len(weak) == 1:                  # 약한 낱말뿐이고 문장 전체로도 못 정했으면 (선택)
            return Resolution(axis, phrase, weak[0], "keyword", 0.5, "weak")
        return Resolution(axis, phrase, self.kb.defaults[axis], "fallback", score)   # ⑤ 기본 톤


def make_retriever(kb: KB, kind: Optional[str] = None):
    kind = (kind or os.getenv("RETRIEVER") or "ngram").lower()
    if kind == "embedding":                       # ① 테이블 (지금 모델로 맞춰 저장) → ② 레포 파일 → ③ ngram
        try:
            return StoreRetriever(kb)
        except Exception as ex:
            logger.warning(f"[KB] 임베딩 테이블 검색기 사용 불가({ex}) → 파일")
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


def tau_for(r) -> float:
    """RETRIEVAL_TAU 는 RETRIEVER 로 고른 검색기의 기준선이다. 그 검색기를 못 쓰고 ngram 으로 내려가면
    ngram 기본값을 쓴다 — 임베딩용 0.7 이 ngram 에 걸리면 거의 아무것도 통과 못 해 놓침만 는다 (2026-10-13)."""
    wanted = (os.getenv("RETRIEVER") or "ngram").lower()
    env = os.getenv("RETRIEVAL_TAU")
    if env and r.name == wanted:
        return float(env)
    if env:
        logger.warning(f"[KB] RETRIEVAL_TAU={env} 는 {wanted} 용 — 지금 검색기 {r.name} 기본값 {DEFAULT_TAU.get(r.name, 0.25)} 사용")
    return DEFAULT_TAU.get(r.name, 0.25)


@lru_cache(maxsize=1)
def get_resolver() -> Resolver:
    kb = KB()
    r = make_retriever(kb)
    tau = tau_for(r)
    from core.rag import get_rag                     # 지연 import (rag 가 kb 를 쓴다)
    rag = get_rag()
    logger.info(f"[KB] {kb.version} · retriever={r.name} · τ={tau} · corpus={'on' if rag else 'off'}")
    return Resolver(kb, r, tau, rag)
