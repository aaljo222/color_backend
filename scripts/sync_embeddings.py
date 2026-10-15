# -*- coding: utf-8 -*-
"""scripts/sync_embeddings.py — 검색 임베딩을 한 모델로 맞춘다 (emb-1). 서버 기동 때도 자동으로 되지만, 미리·확인용으로 1회.
  python scripts/sync_embeddings.py              # KB·코퍼스 → mac_embeddings, 색 문장 → color_prompts.embedding
  python scripts/sync_embeddings.py --status     # 지금 모델과 저장 행 수만 본다
필요: SUPABASE_URL · SUPABASE_SERVICE_KEY · 임베딩 키(VOYAGE_API_KEY 또는 GEMINI_API_KEY) · sql/migrate_emb-1.sql 실행.
★ 로컬 .env 와 Railway 의 임베딩 제공자를 같게 둘 것 (EMBED_PROVIDER=voyage 또는 gemini). 다르면 두 곳이 서로 다른 모델로
  color_prompts 를 덮어써 '비슷한 문장'이 반쪽만 검색된다 (2026-10-15 운영: gemini 4행 · voyage 1행 섞임).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from oracle import similar
from core import vector_store

if similar.model_name() is None:
    sys.exit("임베딩 키가 없습니다 (VOYAGE_API_KEY 또는 GEMINI_API_KEY)")
if "--status" not in sys.argv:
    from core.kb import KB
    from core.corpus import get_corpus
    kb = KB()
    assert vector_store.vectors("kb", [(e["id"], kb.text_of(e)) for e in kb.items]) is not None, "KB 임베딩 실패 (로그 확인)"
    c = get_corpus()
    assert vector_store.vectors("corpus", [(s["id"], s["text"]) for s in c.scenes]) is not None, "코퍼스 임베딩 실패 (로그 확인)"
    print(f"색 문장(color_prompts) 다시 채움: {similar.backfill(5000)}개")
print(json.dumps(vector_store.status(), ensure_ascii=False, indent=1))
