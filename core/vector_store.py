"""core/vector_store.py — KB·코퍼스 임베딩을 Supabase 테이블(mac_embeddings)에 저장하고 꺼내 쓴다 (emb-1).

왜 (2026-10-15 운영 확인)
  · 검색 벡터가 레포 JSON(data/corpus_embeddings.json · kb_embeddings.json)에만 있었다. 파일은 Gemini 로 만들어졌는데
    서버에 VOYAGE_API_KEY 가 있으면 질의는 Voyage 로 만들어져 모델이 달라지고 → 안전장치가 임베딩을 끄고 ngram 으로 내려갔다.
    파일을 다시 만들려면 PC 에서 스크립트를 돌리고 커밋해야 했다.
  · 이 모듈은 지금 서버의 임베딩 모델로 벡터를 테이블에서 찾고, 없거나 문장이 바뀐 항목만 그 자리에서 만들어 저장한다.
    그래서 키를 바꾸거나 코퍼스가 바뀌어도 다음 기동 때 저절로 맞춰진다.

규칙
  · 제공자·모델·차원은 oracle/similar.py 하나로 정한다 (EMBED_PROVIDER / SIMILAR_PROVIDER, 없으면 VOYAGE 키 → voyage, GEMINI 키 → gemini).
    색 문장 추천(color_prompts)과 기억 문장 검색(KB·코퍼스)이 같은 모델을 쓴다.
  · 행 키 = (kind, item_id, embedding_model). 다른 모델의 벡터와는 섞지 않는다.
  · content_hash = 임베딩한 문장의 sha256 앞 16자. 문장이 바뀌면 그 항목만 다시 만든다.
  · Supabase 가 없으면(로컬·테스트) 같은 일을 프로세스 메모리에서 한다.
  · 어떤 단계든 실패하면 None → 호출한 쪽은 예전처럼 파일 → ngram 으로 내려간다 (서비스는 멈추지 않는다).

환경변수  VECTOR_STORE = auto(기본) | off      표 정의: sql/schema.sql 13) mac_embeddings
"""
from __future__ import annotations
import hashlib, json, logging, os
from typing import Optional

import numpy as np

logger = logging.getLogger("uvicorn")
TABLE = "mac_embeddings"
BATCH = 64
_MEM: dict[tuple, dict] = {}          # Supabase 없을 때: (kind, model) → {item_id: (hash, vec)}


def enabled() -> bool:
    return (os.getenv("VECTOR_STORE") or "auto").lower() != "off"


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _sb():
    try:
        from utils.supabase_client import supabase_admin
        return supabase_admin
    except Exception:
        return None


def _parse(v) -> list[float]:
    """PostgREST 는 vector 칸을 '[0.1,0.2,…]' 문자열로 돌려준다."""
    return json.loads(v) if isinstance(v, str) else list(v)


def _load(sb, kind: str, model: str) -> dict:
    if sb is None:
        return dict(_MEM.get((kind, model), {}))
    out, start = {}, 0
    while True:                                           # 1000행 단위로 끊어 읽는다 (PostgREST 기본 상한)
        r = (sb.table(TABLE).select("item_id,content_hash,embedding").eq("kind", kind).eq("embedding_model", model)
             .range(start, start + 999).execute())
        rows = r.data or []
        for x in rows:
            out[x["item_id"]] = (x["content_hash"], _parse(x["embedding"]))
        if len(rows) < 1000:
            return out
        start += 1000


def _save(sb, kind: str, model: str, rows: list[tuple[str, str, list[float]]]):
    if sb is None:
        _MEM.setdefault((kind, model), {}).update({i: (h, v) for i, h, v in rows})
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    sb.table(TABLE).upsert([{"kind": kind, "item_id": i, "content_hash": h, "embedding_model": model, "embedding": list(v),
                             "updated_at": now} for i, h, v in rows], on_conflict="kind,item_id,embedding_model").execute()


def vectors(kind: str, items: list[tuple[str, str]]) -> Optional[dict[str, np.ndarray]]:
    """items = [(item_id, 임베딩할 문장)] → {item_id: 벡터}. 지금 모델 벡터가 없거나 문장이 바뀐 항목만 새로 만든다.
    임베딩을 쓸 수 없으면(키 없음·끔·장애) None."""
    if not enabled() or not items:
        return None
    from oracle import similar
    model = similar.model_name()
    if model is None:
        return None
    sb = _sb()
    try:
        have = _load(sb, kind, model)
        todo = [(i, t) for i, t in items if have.get(i, ("",))[0] != content_hash(t)]
        for s in range(0, len(todo), BATCH):
            part = todo[s:s + BATCH]
            vecs = similar.embed_many([t for _, t in part], "document")
            rows = [(i, content_hash(t), v) for (i, t), v in zip(part, vecs)]
            _save(sb, kind, model, rows)
            have.update({i: (h, v) for i, h, v in rows})
        if todo:
            logger.info(f"[vector_store] {kind}: {len(todo)}/{len(items)}개 새로 임베딩 · {model} · "
                        f"{'Supabase ' + TABLE if sb is not None else '메모리'}")
        return {i: np.asarray(have[i][1], float) for i, _ in items}
    except Exception as ex:
        logger.warning(f"[vector_store] {kind} 임베딩 사용 불가 → 파일/ngram: {type(ex).__name__}: {str(ex)[:160]}"
                       + (" (sql/schema.sql 13) 실행?)" if sb is not None else ""))
        return None


def query(text: str) -> list[float]:
    """질의 벡터 — 저장 벡터와 같은 모델 (실패하면 예외를 올린다 → 호출한 쪽이 이번 질의만 ngram)."""
    from oracle import similar
    return similar.embed_many([text], "query")[0]


def status() -> dict:
    """확인용: 지금 모델과 종류별 저장 행 수."""
    from oracle import similar
    model, sb = similar.model_name(), _sb()
    out = {"enabled": enabled(), "model": model, "backend": "supabase" if sb is not None else "memory", "rows": {}}
    if model is None:
        return out
    for kind in ("kb", "corpus"):
        try:
            out["rows"][kind] = len(_load(sb, kind, model))
        except Exception as ex:
            out["rows"][kind] = f"오류 {type(ex).__name__}"
    return out
