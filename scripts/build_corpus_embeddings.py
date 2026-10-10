"""scripts/build_corpus_embeddings.py — 코퍼스 장면 문단 임베딩 파일 만들기 (선택, eng-2.2).

  VOYAGE_API_KEY=... python scripts/build_corpus_embeddings.py
  → data/corpus_embeddings.json  {model, corpus_version, ids, vectors}

임베딩 제공자·모델은 '비슷한 문장'(oracle/similar.py)과 같다: VOYAGE_API_KEY → voyage-4(1024차원), 없으면 GEMINI_API_KEY.
파일에 모델 이름과 코퍼스 버전을 같이 적는다. 서버(core/rag.py)는 둘이 지금과 같을 때만 이 파일을 쓰고, 다르면 ngram 으로 내려간다.
→ 코퍼스 문단을 고치거나 모델을 바꾸면 이 스크립트를 다시 돌린다. 그다음 scripts/eval_rag.py --sweep 으로 τc 를 다시 정한다.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.kb import KB
from core.corpus import load
from core.rag import EMBED_PATH
from oracle import similar

model = similar.model_name()
if model is None:
    sys.exit("임베딩 제공자 키가 없습니다 (VOYAGE_API_KEY 또는 GEMINI_API_KEY)")
c = load(KB())
ids = [s["id"] for s in c.scenes]
texts = [s["text"] for s in c.scenes]
vecs = []
for i in range(0, len(texts), 64):
    vecs += similar.embed_many(texts[i:i + 64], "document")
EMBED_PATH.write_text(json.dumps({"model": model, "corpus_version": c.version, "ids": ids, "vectors": vecs}), encoding="utf-8")
print(f"{EMBED_PATH} · {len(ids)}개 · {model} · {c.version}")
