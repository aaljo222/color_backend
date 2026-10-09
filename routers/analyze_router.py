"""routers/analyze_router.py — POST /api/analyze : 기억 문장 → 4색 SPECIMEN

접근 정책(Q1):
  - 게스트: IP당 하루 GUEST_DAILY_LIMIT 회, 결과는 저장하지 않음(원문·이메일도 저장 안 함)
  - 로그인: 크레딧 1 차감, 결과 저장. 원문은 keep_text=true 일 때만 암호화 보관(Q2)
같은 기억(같은 KB 해석)은 캐시 키가 같아 같은 결과를 돌려준다.
크레딧은 '내 보관함에 새 표본이 생길 때'만 차감 — 이미 가진 표본과 같은 기억이면 기존 표본을 돌려주고 차감하지 않는다.
"""
from __future__ import annotations
import base64, io, logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from core.pipeline import analyze
from core.render import render_color_field
from core import store
from utils.auth import get_optional_payload
from utils.limiter import limiter, client_ip
from utils.mailer import send_palette

logger = logging.getLogger("uvicorn")
router = APIRouter(prefix="/api", tags=["Analyze"])


class AnalyzeRequest(BaseModel):
    memory: str = Field(min_length=10, max_length=300, description="기억 문장 (10~300자)")
    email: Optional[EmailStr] = Field(default=None, description="HEX 컬러칩 수신용 (저장하지 않음)")
    keep_text: bool = Field(default=False, description="원문 보관 동의 (로그인 사용자만, 암호화 저장)")
    engine: Optional[Literal["palette", "image_first"]] = Field(default=None, description="없으면 서버 ENGINE_MODE (A/B 비교용)")
    include_image: bool = Field(default=True, description="응답에 base64 PNG 포함")


@router.post("/analyze")
@limiter.limit("10/minute")
def analyze_memory(request: Request, req: AnalyzeRequest, payload: Optional[dict] = Depends(get_optional_payload)):
    uid = payload.get("sub") if payload else None
    if uid is None and not store.guest_quota_ok(client_ip(request)):
        raise HTTPException(status_code=429, detail="오늘 체험 횟수를 다 썼어요. 로그인하면 더 만들 수 있어요.")
    if uid and store.credit_status(uid)["credits"] <= 0:          # LLM 호출 전에 먼저 확인 (비용 절약)
        raise HTTPException(status_code=402, detail="크레딧이 부족해요. 추가 인증 후 무료 크레딧을 받을 수 있어요.")
    try:
        result = analyze(req.memory, cache=store.CACHE, engine=req.engine)
    except RuntimeError as ex:
        logger.error(f"[analyze] {ex}")
        raise HTTPException(status_code=502, detail="색채 표본 추출에 실패했습니다. 문장을 조금 더 구체적으로 작성해 주세요.")

    img = result.pop("_image", None)
    if img is None:                                               # 캐시 적중: 코드 그림은 결정론이라 다시 그리면 같다
        img = render_color_field(result["palette"], result["cache_key"])
    owned = store.find_owned(uid, result["cache_key"]) if uid else None
    if owned:
        result["specimen_id"], result["already_owned"] = owned, True
    elif uid:
        if not store.consume_credit(uid):
            raise HTTPException(status_code=402, detail="크레딧이 부족해요. 추가 인증 후 무료 크레딧을 받을 수 있어요.")
        png = _png(img)
        try:
            result["specimen_id"] = store.save_specimen(uid, result, png, req.memory if req.keep_text else None)
        except RuntimeError as ex:                     # MEMORY_ENC_KEY 없음 등
            store.refund_credit(uid)
            raise HTTPException(status_code=400, detail=str(ex))
        except Exception as ex:                        # DB 저장 실패 → 크레딧 돌려주고 결과는 그대로 보여 준다
            store.refund_credit(uid)
            logger.error(f"[analyze] 표본 저장 실패: {type(ex).__name__}: {str(ex)[:200]}")
            result["save_error"] = "표본은 만들었지만 보관함에 저장하지 못했습니다. 크레딧은 차감되지 않았습니다."
    result.pop("_log", None)
    if img is not None and req.include_image:
        result["image_png_base64"] = base64.b64encode(_png(img)).decode()
    result["email_sent"] = send_palette(req.email, result) if req.email else False
    return result


def _png(img) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
