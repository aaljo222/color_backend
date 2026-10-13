import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 로컬 .env 를 테스트에서 읽지 않는다. main.py 가 load_dotenv() 를 부르면 아래에서 지운 키·설정이 되살아나
# 실제 API 를 부르고(느리고 한도를 쓴다) IMAGE_AFFECT_GATE·RETRIEVER 같은 설정이 테스트 기대와 달라진다 (2026-10-13).
try:
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
except ImportError:
    pass
for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
          "OPENAI_API_KEY", "VOYAGE_API_KEY", "EMBED_PROVIDER", "RETRIEVAL_TAU", "CORPUS_TAU", "EMBED_CACHE"):
    os.environ.pop(k, None)
os.environ.update(LLM_MODE="stub", RETRIEVER="ngram", APP_ENV="test", UA_BLOCK="1",
                  JWT_SECRET_KEY="test-secret-for-pytest-only-0123456789",
                  MEMORY_ENC_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
