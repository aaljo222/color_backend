# -*- coding: utf-8 -*-
"""scripts/embed_prompts.py — 저장된 색 문장에 임베딩을 채운다 (임베딩을 켠 뒤, 또는 모델을 바꾼 뒤 1회).
  python scripts/embed_prompts.py            # 지금 모델의 벡터가 없는 행만 채운다
필요: SUPABASE_URL · SUPABASE_SERVICE_KEY · VOYAGE_API_KEY(또는 GEMINI_API_KEY), schema.sql 11-1 실행.
모델을 바꾸면(embedding_model 이 달라지면) 모든 행을 다시 채운다 — 다른 모델의 벡터와는 비교할 수 없기 때문.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from utils.supabase_client import supabase_admin as sb
from oracle import similar

model = similar.model_name()
if sb is None or model is None:
    sys.exit("Supabase 와 임베딩 키(VOYAGE_API_KEY 또는 GEMINI_API_KEY)가 필요합니다")
rows = (sb.table("color_prompts").select("key,prompt,embedding_model").neq("source", "rule").limit(5000).execute().data or [])
rows = [r for r in rows if r.get("embedding_model") != model]
print(f"모델 {model} · 채울 문장 {len(rows)}개")
for i in range(0, len(rows), 64):
    part = rows[i:i + 64]
    vecs = similar.embed_many([r["prompt"] for r in part], "document")
    for r, v in zip(part, vecs):
        sb.table("color_prompts").update({"embedding": v, "embedding_model": model}).eq("key", r["key"]).execute()
    print(f"  {i + len(part)}/{len(rows)}"); time.sleep(0.3)
print("✔ 완료")
