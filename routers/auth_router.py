"""
auth_router.py — 회원 인증 라우터 (prefix: /auth) — elecai backend 패턴을 MaC에 맞게 조정

프론트는 기본적으로 Supabase로 직접 로그인/회원가입을 하지만,
서버측에서도 동일 기능을 제공한다(관리·서버투서버·프로필 보강 목적).

엔드포인트:
  POST /auth/signup   회원가입 + profiles 생성
  POST /auth/login    로그인 → access_token + role 반환
  GET  /auth/me       내 정보 (Bearer 토큰 필요)
  PATCH /auth/me      내 정보 수정
  DELETE /auth/me     회원 탈퇴

⚠️ profiles 테이블은 sql/schema.sql 기준 (id, email, name, role, credits, free_credit_claimed, updated_at).
가입 직후 크레딧은 0 — 무료 크레딧은 추가 인증 후 POST /api/me/credits/claim 으로만 지급(Q1).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from utils.auth import get_current_user_id
from utils.supabase_client import supabase, supabase_admin
from utils.limiter import limiter


def _require_sb():
    if supabase is None:
        raise HTTPException(status_code=503, detail="인증 서버(Supabase)가 설정되지 않았습니다.")

logger = logging.getLogger("uvicorn")

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, description="비밀번호 (6자 이상)")
    name: str = Field(default="이름없음", description="사용자 이름")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=30)


# ── 회원가입 ────────────────────────────────────────────────────────────────
@router.post("/signup", summary="회원가입 + 기본 role 생성")
@limiter.limit("5/hour")
def signup(request: Request, req: SignupRequest):
    _require_sb()
    logger.info("🆕 회원가입 요청")
    try:
        auth_res = supabase.auth.sign_up(
            {
                "email": req.email,
                "password": req.password,
                "options": {"data": {"name": req.name}},
            }
        )
        if not auth_res.user:
            raise HTTPException(status_code=400, detail="회원가입 실패 (Auth User 생성 불가)")

        user_id = auth_res.user.id

        supabase_admin.table("profiles").upsert(
            {
                "id": user_id,
                "email": req.email,
                "name": req.name,
                "role": "user",
                "credits": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()

        logger.info(f"✅ 회원가입 완료: {user_id}")
        return {"status": "ok", "user_id": user_id, "role": "user"}

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        logger.error(f"❌ 회원가입 오류: {msg}")
        if "already registered" in msg or "User already exists" in msg:
            raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")   # 내부 메시지 노출 안 함


# ── 로그인 ──────────────────────────────────────────────────────────────────
@router.post("/login", summary="로그인 + role 반환")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest):
    _require_sb()
    try:
        auth = supabase.auth.sign_in_with_password(
            {"email": req.email, "password": req.password}
        )
        if not auth.session:
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호를 확인해주세요.")

        user_id = auth.user.id
        user_role, user_name = "user", ""
        try:
            profile = (
                supabase_admin.table("profiles")
                .select("role,name")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
            if profile and profile.data:
                user_role = profile.data.get("role", "user")
                user_name = profile.data.get("name", "")
        except Exception as pe:
            logger.error(f"🚨 role 조회 에러(로그인은 허용): {pe}")

        logger.info(f"🔑 로그인 성공: {user_id} (role={user_role})")
        return {
            "access_token": auth.session.access_token,
            "refresh_token": auth.session.refresh_token,
            "user_id": user_id,
            "email": auth.user.email,
            "name": user_name,
            "role": user_role,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 로그인 오류: {e}")
        raise HTTPException(status_code=400, detail="이메일 또는 비밀번호를 확인해주세요.")


# ── 내 정보 ────────────────────────────────────────────────────────────────
@router.get("/me", summary="내 정보 조회")
def get_my_profile(user_id: str = Depends(get_current_user_id)):
    _require_sb()
    try:
        res = (
            supabase_admin.table("profiles")
            .select("id,email,name,role,credits,free_credit_claimed,updated_at")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        if not res or not res.data:
            raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
        return res.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 내 정보 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="프로필 조회 실패")


@router.patch("/me", summary="내 정보 수정")
def patch_my_profile(
    req: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    _require_sb()
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        res = (
            supabase_admin.table("profiles").update(payload).eq("id", user_id).execute()
        )
        return {"status": "ok", "updated": len(res.data or []), "payload": payload}
    except Exception as e:
        logger.error(f"❌ 프로필 수정 실패: {e}")
        raise HTTPException(status_code=500, detail="프로필 수정 실패")


@router.delete("/me", summary="회원 탈퇴")
def delete_my_profile(user_id: str = Depends(get_current_user_id)):
    """탈퇴 시 표본·원문·로그도 함께 삭제 (FK on delete cascade, sql/schema.sql)."""
    _require_sb()
    try:
        supabase_admin.table("profiles").delete().eq("id", user_id).execute()
        try:
            supabase_admin.auth.admin.delete_user(user_id)
        except Exception as auth_err:
            logger.warning(f"⚠️ Auth 삭제 경고({user_id}): {auth_err}")
        return {"status": "ok", "deleted": True, "user_id": user_id}
    except Exception as e:
        logger.error(f"❌ 탈퇴 처리 실패: {e}")
        raise HTTPException(status_code=500, detail="탈퇴 처리 실패")
