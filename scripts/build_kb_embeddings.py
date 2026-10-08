"""scripts/build_kb_embeddings.py — Color KB 항목 임베딩 생성 (Gemini).

  python scripts/build_kb_embeddings.py              # data/kb_embeddings.json 생성 → RETRIEVER=embedding
  python scripts/build_kb_embeddings.py --supabase   # + color_kb 테이블 upsert → RETRIEVER=supabase
KB를 고치면(버전 올림) 반드시 다시 실행한다.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from core.kb import KB
from core.llm import embed_texts, EMBED_MODEL, EMBED_DIM

ap = argparse.ArgumentParser(); ap.add_argument("--supabase", action="store_true"); a = ap.parse_args()
kb = KB()
texts = [kb.text_of(e) for e in kb.items]
vecs = []
for i in range(0, len(texts), 20):
    vecs += embed_texts(texts[i:i + 20], task="RETRIEVAL_DOCUMENT")
out = {"kb_version": kb.version, "model": EMBED_MODEL, "dim": EMBED_DIM, "ids": [e["id"] for e in kb.items], "vectors": vecs}
p = Path(__file__).resolve().parent.parent / "data" / "kb_embeddings.json"
p.write_text(json.dumps(out), encoding="utf-8")
print(f"✔ {p} ({len(vecs)}개, {EMBED_DIM}차원)")
if a.supabase:
    from utils.supabase_client import supabase_admin as sb
    rows = [{**{k: e.get(k) for k in ("id", "axis", "name", "keywords", "description", "lch", "accent_lch", "modifiers", "source", "status")},
             "kb_version": kb.version, "embedding": v} for e, v in zip(kb.items, vecs)]
    sb.table("color_kb").upsert(rows).execute()
    print(f"✔ Supabase color_kb upsert {len(rows)}행")
