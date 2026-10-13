"""scripts/build_kb_embeddings.py — Color KB 항목 임베딩 생성 (Gemini).

  python scripts/build_kb_embeddings.py              # data/kb_embeddings.json 생성 → RETRIEVER=embedding
  python scripts/build_kb_embeddings.py --supabase   # + color_kb 테이블 upsert → RETRIEVER=supabase
KB를 고치면(버전 올림) 반드시 다시 실행한다.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from core.kb import KB
from core.llm import embed_texts, embed_model_name, EMBED_DIM


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


ap = argparse.ArgumentParser(); ap.add_argument("--supabase", action="store_true"); a = ap.parse_args()
kb = KB()
texts = [kb.text_of(e) for e in kb.items]
vecs = []
for i in range(0, len(texts), 16):
    vecs += with_retry(embed_texts, texts[i:i + 16], task="RETRIEVAL_DOCUMENT")
out = {"kb_version": kb.version, "model": embed_model_name(), "dim": EMBED_DIM, "ids": [e["id"] for e in kb.items], "vectors": vecs}
p = Path(__file__).resolve().parent.parent / "data" / "kb_embeddings.json"
p.write_text(json.dumps(out), encoding="utf-8")
print(f"✔ {p} ({len(vecs)}개, {EMBED_DIM}차원)")
if a.supabase:
    from utils.supabase_client import supabase_admin as sb
    rows = [{**{k: e.get(k) for k in ("id", "axis", "name", "keywords", "description", "lch", "accent_lch", "modifiers", "source", "status")},
             "kb_version": kb.version, "embedding": v} for e, v in zip(kb.items, vecs)]
    sb.table("color_kb").upsert(rows).execute()
    print(f"✔ Supabase color_kb upsert {len(rows)}행")
