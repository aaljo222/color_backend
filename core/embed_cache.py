"""core/embed_cache.py — 질의 임베딩 캐시 (2026-10-13).

같은 문장의 질의 임베딩을 다시 부르지 않는다. 무료 Gemini 키는 임베딩 요청이 하루 1,000번이라
채점 스크립트를 두세 번 돌리면 하루치가 끝났다 (2026-10-12 실제로 겪음).
  · 메모리 캐시: 늘 켜짐. 서버에서도 같은 구가 다시 오면 API 를 안 부른다 (MAX 개를 넘으면 비움).
  · 디스크 캐시: EMBED_CACHE=경로 일 때만. 채점 스크립트(scripts/eval_full.py)가 켠다 → 두 번째 실행부터 API 호출 0.
  · 못 찾은 문장만 모아 한 번에 보낸다 (요청 수 = 문장 수가 아니라 묶음 수).
키에 모델·차원·작업 종류를 넣으므로 모델을 바꾸면 자연히 새로 부른다.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Callable

MAX = 20000
_mem: dict[str, list[float]] = {}
_loaded = False
_dirty = False
calls = 0          # 이번 실행에서 실제로 보낸 요청 수 (묶음 단위)


def _path():
    p = os.getenv("EMBED_CACHE")
    return Path(p) if p else None


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    p = _path()
    if p and p.exists():
        try:
            _mem.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass


def cached(namespace: str, texts: list[str], fn: Callable[[list[str]], list[list[float]]], batch: int = 50) -> list[list[float]]:
    """texts 의 임베딩. 캐시에 없는 것만 batch 개씩 fn 으로 부른다."""
    global _dirty, calls
    _load()
    keys = [f"{namespace}\t{t}" for t in texts]
    miss = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in _mem))
    if len(_mem) + len(miss) > MAX:
        _mem.clear()
    for i in range(0, len(miss), batch):
        part = miss[i:i + batch]
        calls += 1
        for t, v in zip(part, fn(part)):
            _mem[f"{namespace}\t{t}"] = list(v)
            _dirty = True
    return [_mem[k] for k in keys]


def save():
    """디스크 캐시에 쓴다 (EMBED_CACHE 가 있을 때만)."""
    global _dirty
    p = _path()
    if p and _dirty:
        p.write_text(json.dumps(_mem), encoding="utf-8")
        _dirty = False


# ── OpenAI 임베딩 (선택, EMBED_PROVIDER=openai) ─────────────────────────────
OPENAI_MODEL = os.getenv("OPENAI_EMBED_MODEL") or "text-embedding-3-small"


def openai_embed(texts: list[str], dim: int) -> list[list[float]]:
    """OpenAI 임베딩 (REST, 새 패키지 없이 httpx). text-embedding-3 은 dimensions 로 차원을 줄일 수 있다.
    질의·문서 구분(task)이 없는 모델이라 둘 다 같은 방식으로 부른다."""
    import httpx
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY 가 없습니다")
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")   # 교육 플랫폼 등 OpenAI 호환 중계 주소
    post = lambda body: httpx.post(f"{base}/embeddings", timeout=60, headers={"Authorization": f"Bearer {key}"}, json=body)
    r = post({"model": OPENAI_MODEL, "input": texts, "dimensions": dim})
    if r.status_code == 400 and "dimension" in r.text.lower():      # 차원 지정을 못 받는 중계 → 모델 기본 차원으로
        r = post({"model": OPENAI_MODEL, "input": texts})
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI 임베딩 {r.status_code} ({base}): {r.text[:300]}")
    return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
