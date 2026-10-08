"""utils/auth.py — Supabase access_token 검증 (elecai backend 패턴 + 보강).

검증 순서:
  1) JWT_SECRET_KEY 가 있으면 HS256 로컬 검증 (aud=authenticated)
  2) 없으면 supabase_admin.auth.get_user(token) 원격 검증 (비대칭 서명키 프로젝트 대응)
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


def decode_token(token: str) -> dict:
    if JWT_SECRET_KEY:
        try:
            return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"], audience="authenticated")
        except jwt.ExpiredSignatureError:
            raise _401("토큰이 만료되었습니다. 다시 로그인해주세요.")
        except jwt.InvalidTokenError:
            raise _401("유효하지 않은 토큰입니다.")
    if supabase_admin is not None:
        try:
            u = supabase_admin.auth.get_user(token).user
            return {"sub": u.id, "email": u.email, "app_metadata": u.app_metadata or {},
                    "phone_confirmed": bool(getattr(u, "phone_confirmed_at", None))}
        except Exception:
            raise _401("유효하지 않은 토큰입니다.")
    raise _401("인증이 설정되지 않은 서버입니다.")


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
