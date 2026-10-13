"""scripts/build_corpus_embeddings.py — 코퍼스 장면 문단 임베딩 파일 만들기 (선택, eng-2.2).

  VOYAGE_API_KEY=... python scripts/build_corpus_embeddings.py
  → data/corpus_embeddings.json  {model, corpus_version, ids, vectors}

임베딩 제공자·모델은 '비슷한 문장'(oracle/similar.py)과 같다: VOYAGE_API_KEY → voyage-4(1024차원), 없으면 GEMINI_API_KEY.
파일에 모델 이름과 코퍼스 버전을 같이 적는다. 서버(core/rag.py)는 둘이 지금과 같을 때만 이 파일을 쓰고, 다르면 ngram 으로 내려간다.
→ 코퍼스 문단을 고치거나 모델을 바꾸면 이 스크립트를 다시 돌린다. 그다음 scripts/eval_rag.py --sweep 으로 τc 를 다시 정한다.
"""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")                      # export 없이 .env 의 키를 읽는다
except ImportError:
    pass
from core.kb import KB
from core.corpus import load
from core.rag import EMBED_PATH
from oracle import similar


def with_retry(fn, *a, tries=6, wait=10, **kw):
    """분당 한도(429·RESOURCE_EXHAUSTED)에 걸리면 10→20→40초… 기다렸다 다시 보낸다. 다른 오류는 바로 올린다."""
    for n in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as ex:
            msg = f"{type(ex).__name__} {ex}"
            if "PerDay" in msg:                          # 하루 한도(무료 키 1,000번)는 기다려도 안 풀린다
                sys.exit("하루 임베딩 한도를 다 썼습니다 (무료 키 1,000번/일, Google 프로젝트 단위). "
                         "오류의 'retry in'만큼 기다리거나 다른 프로젝트의 키를 .env 에 넣으세요.")
            if n == tries - 1 or not any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "rate", "quota")):
                raise
            print(f"  한도 초과 — {wait}초 뒤 다시 ({n + 1}/{tries - 1})", flush=True)
            time.sleep(wait)
            wait *= 2


model = similar.model_name()
if model is None:
    sys.exit("임베딩 제공자 키가 없습니다 (VOYAGE_API_KEY 또는 GEMINI_API_KEY)")
c = load(KB())
ids = [s["id"] for s in c.scenes]
texts = [s["text"] for s in c.scenes]
vecs = []
BATCH = 16                                          # 64개씩 보내면 분당 한도에 걸려 통째로 실패했다
for i in range(0, len(texts), BATCH):
    vecs += with_retry(similar.embed_many, texts[i:i + BATCH], "document")
    print(f"  {min(i + BATCH, len(texts))}/{len(texts)}", flush=True)
EMBED_PATH.write_text(json.dumps({"model": model, "corpus_version": c.version, "ids": ids, "vectors": vecs}), encoding="utf-8")
print(f"{EMBED_PATH} · {len(ids)}개 · {model} · {c.version}")
