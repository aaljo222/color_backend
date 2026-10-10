"""core/rag.py — 코퍼스 RAG (eng-2.2): 검색(Retrieve) → 보강(Augment). 생성(색 숫자)은 여전히 계산기.

어디에 쓰나 (core/pipeline.py)
  ① KB 해석     : 축 구(phrase) → 장면 문단 검색 → 문단이 가리키는 KB 항목      (Resolver 의 'corpus' 단계)
                  키워드 → 모델 라벨 → [코퍼스 ≥ τc] → KB 설명 검색 ≥ τ → 기본 톤
  ② 사물 등급   : 어휘사전에 없는 사물 → 코퍼스 사물 문단의 등급 (같은 낱말 = 같은 색, 모델 등급보다 우선)
  ③ 그림 지시문 : 해석된 KB 항목의 장면 문단 + 색 묘사(color_note, 숫자 없음) → 화가 프롬프트 (eng-2.0)
  ④ 근거        : 응답 grounding = 쓰인 장면·사물 문단 + 이 표본에 적용된 규칙을 뒷받침하는 연구(인용·URL)

검색 방법 (CORPUS_METHOD = auto | ngram | embedding, 기본 auto)
  ngram     : 글자 2·3-gram TF-IDF 코사인. 키 없이 항상 동작. 결정론.
  embedding : data/corpus_embeddings.json (scripts/build_corpus_embeddings.py 가 생성) + 질의 임베딩.
              임베딩 제공자는 '비슷한 문장'과 같다 (oracle/similar.py: VOYAGE_API_KEY → voyage, 없으면 GEMINI).
              파일의 모델 이름·코퍼스 버전이 지금과 다르면 쓰지 않고 ngram 으로 내려간다 (좌표가 다르면 점수가 무의미).
  auto      : 위 조건이 모두 맞으면 embedding, 아니면 ngram.
  ※ 같은 문장 = 같은 값은 문장 고정(eng-2.1)이 지킨다. 임베딩 API 응답이 아주 조금 흔들려도 고정된 문장은 바뀌지 않는다.
기준선 CORPUS_TAU (비우면 ngram 0.35 · embedding 0.55)
  ngram 0.35: scripts/eval_rag.py --sweep 에서 두 골드셋 모두 오연결 0 이 되는 가장 낮은 값 (2026-10-10 실측).
              팀 골드셋 9문장 22% → 44%, 추가 골드셋 36문장 19% → 44% (KB 설명 검색만 대비).
  embedding 0.55: 잠정값 (키가 없어 아직 못 쟀다). 임베딩 파일을 만든 뒤 같은 스크립트로 다시 정할 것.
"""
from __future__ import annotations
import json, logging, math, os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

from core.corpus import Corpus, get_corpus, norm_name, CORPUS_DIR
from core.kb import _ngrams

logger = logging.getLogger("uvicorn")
ENABLED = os.getenv("CORPUS_RAG", "1") == "1"
EMBED_PATH = Path(os.getenv("CORPUS_EMBED_PATH", CORPUS_DIR.parent / "corpus_embeddings.json"))
DEFAULT_TAU = {"ngram": 0.35, "embedding": 0.55}
SCENES_PER_AXIS = 2
PROMPT_AXES = ("emotion", "time", "space")


@dataclass(frozen=True)
class Hit:
    score: float
    passage: dict


class _Ngram:
    name = "ngram"

    def __init__(self, docs: list[str]):
        tfs, vocab = [], {}
        for d in docs:
            tf: dict[str, int] = {}
            for g in _ngrams(d):
                tf[g] = tf.get(g, 0) + 1
                vocab.setdefault(g, len(vocab))
            tfs.append(tf)
        n = len(docs)
        df: dict[str, int] = {}
        for tf in tfs:
            for g in tf:
                df[g] = df.get(g, 0) + 1
        self.idf = {g: math.log((1 + n) / (1 + df[g])) + 1 for g in vocab}
        self.vocab = vocab
        self.mat = np.array([self._vec(tf) for tf in tfs]) if docs else np.zeros((0, 0))

    def _vec(self, tf: dict) -> np.ndarray:
        v = np.zeros(len(self.vocab))
        for g, c in tf.items():
            if g in self.vocab:
                v[self.vocab[g]] = c * self.idf[g]
        nrm = np.linalg.norm(v)
        return v / nrm if nrm else v

    def scores(self, query: str) -> np.ndarray:
        tf: dict[str, int] = {}
        for g in _ngrams(query):
            tf[g] = tf.get(g, 0) + 1
        return self.mat @ self._vec(tf) if len(self.mat) else np.zeros(0)


class _Embedding:
    name = "embedding"

    def __init__(self, ids: list[str], data: dict, embed):
        pos = {i: n for n, i in enumerate(data["ids"])}
        m = np.array([data["vectors"][pos[i]] for i in ids], float)
        self.mat = m / np.linalg.norm(m, axis=1, keepdims=True)
        self._embed = embed

    def scores(self, query: str) -> np.ndarray:
        q = np.array(self._embed(query), float)
        return self.mat @ (q / (np.linalg.norm(q) or 1))


def _embedding_backend(corpus: Corpus, ids: list[str]):
    """쓸 수 있으면 임베딩 검색기, 아니면 None (이유는 로그). 키·파일·모델·버전이 모두 맞아야 한다."""
    method = (os.getenv("CORPUS_METHOD") or "auto").lower()
    if method == "ngram":
        return None
    try:
        from oracle import similar
        model = similar.model_name()
        if model is None or not EMBED_PATH.exists():
            return None
        data = json.loads(EMBED_PATH.read_text(encoding="utf-8"))
        if data.get("model") != model or data.get("corpus_version") != corpus.version or not set(ids) <= set(data["ids"]):
            logger.warning(f"[RAG] 코퍼스 임베딩 파일이 지금과 다름(모델 {data.get('model')} / 버전 {data.get('corpus_version')}) "
                           f"→ ngram. scripts/build_corpus_embeddings.py 로 다시 만드세요")
            return None
        return _Embedding(ids, data, lambda t: similar.embed_many([t], "query")[0])
    except Exception as ex:
        logger.warning(f"[RAG] 임베딩 검색 사용 불가 → ngram: {type(ex).__name__}")
        return None


class CorpusRAG:
    def __init__(self, corpus: Corpus, tau: Optional[float] = None):
        self.corpus = corpus
        self.scenes = list(corpus.scenes)
        ids = [s["id"] for s in self.scenes]
        self.ngram = _Ngram([s["text"] for s in self.scenes])
        self.emb = _embedding_backend(corpus, ids)
        self.method = self.emb.name if self.emb else "ngram"
        env_tau = os.getenv("CORPUS_TAU")
        self.tau = float(tau if tau is not None else env_tau or DEFAULT_TAU[self.method])

    # ── 검색 ──
    def _scores(self, query: str) -> tuple[np.ndarray, float]:
        """(점수, 그 점수에 맞는 기준선). 질의 임베딩이 실패하면 이번 질의만 ngram 점수·ngram 기준선."""
        if self.emb is not None:
            try:
                return self.emb.scores(query), self.tau
            except Exception as ex:
                logger.warning(f"[RAG] 질의 임베딩 실패 → 이번 질의 ngram: {type(ex).__name__}")
                return self.ngram.scores(query), DEFAULT_TAU["ngram"]
        return self.ngram.scores(query), self.tau

    def _ranked(self, query: str, axis, kb_id, k) -> tuple[list[Hit], float]:
        query = (query or "").strip()
        if not query or not self.scenes:
            return [], self.tau
        sims, tau = self._scores(query)
        hits = [Hit(round(float(s), 4), p) for s, p in zip(sims, self.scenes)
                if (axis is None or p["axis"] == axis) and (kb_id is None or p["kb_id"] == kb_id)]
        hits.sort(key=lambda h: (-h.score, h.passage["id"]))  # 같은 점수면 id 순 → 순서도 결정론
        return hits[:k], tau

    def search(self, query: str, axis: Optional[str] = None, kb_id: Optional[str] = None, k: int = 5) -> list[Hit]:
        return self._ranked(query, axis, kb_id, k)[0]

    def resolve_axis(self, phrase: str, axis: str) -> Optional[Hit]:
        """구 → 가장 비슷한 장면 문단 (≥ τ). 없으면 None."""
        hits, tau = self._ranked(phrase, axis, None, 1)
        return hits[0] if hits and hits[0].score >= tau else None

    # ── 사물 ──
    def object_of(self, name: str) -> Optional[dict]:
        return self.corpus.object_by_name.get(norm_name(name))

    def objects_in(self, text: str, limit: int = 3) -> list[str]:
        """문장에 실제로 나온 코퍼스 사물 이름 (문장 속 순서, 겹치는 짧은 이름 제외). 키 없는 stub 추출용."""
        found, taken = [], []
        for n in self.corpus.object_names():
            i = text.find(n)
            if i < 0 or any(a <= i < b or a < i + len(n) <= b for a, b in taken):
                continue
            taken.append((i, i + len(n)))
            found.append((i, n))
        return [n for _, n in sorted(found)[:limit]]

    # ── 근거 묶음 ──
    def ground(self, res: dict, objects: list, affect) -> dict:
        """이 표본에 실제로 쓰인 것만 묶는다. 숫자 색은 없다(장면 color_note 는 말로 된 묘사)."""
        scenes = []
        for axis in PROMPT_AXES:
            r = res.get(axis)
            if r is None or r.how == "fallback":
                continue
            for h in self.search(r.phrase or "", axis=axis, kb_id=r.kb_id, k=SCENES_PER_AXIS) or \
                    [Hit(0.0, p) for p in self.corpus.scenes_of(axis) if p["kb_id"] == r.kb_id][:1]:
                p = h.passage
                scenes.append({"id": p["id"], "axis": axis, "kb_id": p["kb_id"], "text": p["text"],
                               "color_note": p.get("color_note", ""), "score": h.score, "status": p["status"]})
        objs = []
        for o in objects:
            if o.how == "corpus":
                p = self.object_of(o.name)
                objs.append({"id": p["id"], "name": o.name, "grade": list(o.descriptor), "status": p["status"]})
        rules = set()
        if affect is not None and getattr(affect, "how", "none") != "none":
            rules |= {"affect.valence_lightness", "affect.arousal_chroma"}
        if objects:
            rules.add("hue.object_association")
        if res.get("emotion") is not None and res["emotion"].how != "fallback":
            rules.add("hue.color_emotion_universal")
        research = [{"id": r["id"], "applies_to": sorted(set(r["applies_to"]) & rules), "evidence": r["evidence"],
                     "citation": r["citation"], "url": r["url"]}
                    for r in self.corpus.research if set(r["applies_to"]) & rules and r["evidence"] in ("strong", "moderate")]
        return {"corpus_version": self.corpus.version, "method": self.method, "tau": self.tau,
                "scenes": scenes, "objects": objs, "research": research}


def prompt_lines(grounding: Optional[dict]) -> list[str]:
    """그림 지시문에 넣을 줄 (eng-2.0 화가). 장면 문단의 말 묘사만 — 숫자 색값은 넣지 않는다."""
    if not grounding:
        return []
    seen, out = set(), []
    for s in grounding.get("scenes", []):
        if s["kb_id"] in seen:
            continue
        seen.add(s["kb_id"])
        out.append(f"- {s['axis']}: {s['text']} → {s['color_note']}" if s.get("color_note") else f"- {s['axis']}: {s['text']}")
    return out


@lru_cache(maxsize=1)
def get_rag() -> Optional[CorpusRAG]:
    if not ENABLED:
        return None
    try:
        rag = CorpusRAG(get_corpus())
        logger.info(f"[RAG] {rag.corpus.version} · 장면 {len(rag.scenes)} · 사물 {len(rag.corpus.objects)} · "
                    f"연구 {len(rag.corpus.research)} · {rag.method} · τc={rag.tau}")
        return rag
    except Exception as ex:                                   # 코퍼스가 깨져도 서비스는 KB 만으로 계속 (경고는 크게)
        logger.error(f"[RAG] 코퍼스 사용 불가 → KB 만으로 계산: {ex}")
        return None
