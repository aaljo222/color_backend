"""utils/supabase_client.py — 서버측 Supabase 클라이언트 (elecai backend 패턴).

  supabase       : anon key — signup/login
  supabase_admin : service_role key — RLS 우회 서버 전용 작업. ⚠️ 절대 프론트로 노출 금지.
SUPABASE_URL/ANON_KEY 가 없으면 None (로컬 개발: 메모리 저장소로 동작).
APP_ENV=prod 에서는 없으면 부팅 실패시킨다.
"""
import os, logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("uvicorn")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

supabase = supabase_admin = None
if SUPABASE_URL and SUPABASE_ANON_KEY:
    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    if SUPABASE_SERVICE_KEY:
        supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    else:
        logger.warning("⚠️ SUPABASE_SERVICE_KEY 미설정 → supabase_admin 이 anon 으로 동작 (RLS에 막힐 수 있음)")
        supabase_admin = supabase
elif os.getenv("APP_ENV") == "prod":
    raise RuntimeError("APP_ENV=prod 인데 SUPABASE_URL / SUPABASE_ANON_KEY 가 없습니다.")
else:
    logger.warning("ℹ️ Supabase 미설정 → 메모리 저장소로 동작 (개발 모드)")
