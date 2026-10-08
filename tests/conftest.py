import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY", "RESEND_API_KEY"):
    os.environ.pop(k, None)
os.environ.update(LLM_MODE="stub", RETRIEVER="ngram", APP_ENV="test", UA_BLOCK="1",
                  JWT_SECRET_KEY="test-secret-for-pytest-only-0123456789",
                  MEMORY_ENC_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
