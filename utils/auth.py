"""utils/auth.py — Supabase access_token 검증 (elecai backend 패턴 + 보강).

검증 순서 (토큰 헤더의 alg 로 고른다):
  1) HS256  → JWT_SECRET_KEY 로컬 검증 (예전 Supabase 프로젝트)
  2) ES256/RS256 → SUPABASE_URL/auth/v1/.well-known/jwks.json 공개키로 로컬 검증 (새 프로젝트 기본)
  3) 위가 안 되면 supabase_admin.auth.get_user(token) 원격 검증
APP_ENV=prod 에서 두 방법 모두 불가하면 부팅 실패.
"""
import os
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from utils.supabase_client import supabase_admin

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if os.getenv("APP_ENV") == "prod" and not JWT_SECRET_KEY and supabase_admin is None:
    raise RuntimeError("토큰 검증 수단이 없습니다: JWT_SECRET_KEY 또는 Supabase 설정 필요")

security = HTTPBearer(auto_error=True)
_401 = lambda m: HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=m)


_jwks = None
def _jwks_client():
    """Supabase 비대칭 서명키(ES256/RS256) 공개키 — 프로젝트 JWKS 를 받아 캐시한다."""
    global _jwks
    if _jwks is None:
        base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        if not base:
            return None
        _jwks = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)
    return _jwks


def _remote(token: str) -> dict:
    u = supabase_admin.auth.get_user(token).user
    return {"sub": u.id, "email": u.email, "app_metadata": u.app_metadata or {},
            "phone_confirmed": bool(getattr(u, "phone_confirmed_at", None))}


def decode_token(token: str) -> dict:
    """토큰 서명 방식에 맞춰 검증한다.
      HS256 (예전 프로젝트, 공유 비밀) → JWT_SECRET_KEY
      ES256·RS256 (새 프로젝트, 비대칭 키) → JWKS 공개키
      둘 다 안 되면 Supabase 서버에 직접 확인(get_user)"""
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
    except jwt.InvalidTokenError:
        raise _401("유효하지 않은 토큰입니다.")
    try:
        if alg == "HS256" and JWT_SECRET_KEY:
            return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"], audience="authenticated")
        if alg in ("ES256", "RS256") and _jwks_client() is not None:
            key = _jwks_client().get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise _401("토큰이 만료되었습니다. 다시 로그인해주세요.")
    except Exception:
        pass                                    # 로컬 검증 실패 → 원격 확인으로
    if supabase_admin is not None:
        try:
            return _remote(token)
        except Exception:
            pass
    raise _401("유효하지 않은 토큰입니다.")


def get_current_payload(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    p = decode_token(credentials.credentials)
    if not p.get("sub"):
        raise _401("토큰에 사용자 정보가 없습니다.")
    return p


def get_current_user_id(payload: dict = Depends(get_current_payload)) -> str:
    return payload["sub"]


def get_optional_payload(request: Request) -> Optional[dict]:
    """게스트 허용 엔드포인트용: 토큰이 없거나 틀리면 None (401을 내지 않음)."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return decode_token(auth.split(" ", 1)[1].strip())
    except HTTPException:
        return None
