"""routers/astral_router.py — Astral Color (사주 컬러) API.

원본: github.com/ssebni/MaC_astral-color (2026-10-09, 1a1baa2) 의 astral/ 패키지를 astral_color/ 로 그대로 옮겼다
(사주 계산·색·점수 규칙은 바꾸지 않음). 여기서는 HTTP 연결과 8색 팔레트(core/astral_palette.py)만 붙인다.
main.py 는 고치지 않는다 → oracle_router 에 include 되어 /api/astral 로 열린다.

  POST /api/astral                 무료 고유색 (calculate_astral_profile)
  POST /api/astral/report-preview  상세 보고서 미리보기 (calculate_paid_report + palette8)
     ※ 실제 결제·접근 권한 검사가 아직 없다. 원본 문서대로 개발용이며, APP_ENV=prod 에서는
       ASTRAL_REPORT_PREVIEW=1 을 명시해야 열린다. 입력·결과는 저장하지 않는다.
"""
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from utils.limiter import limiter
from astral_color.engine import AstralInputError, calculate_astral_profile, calculate_paid_report
from core import astral_palette

router = APIRouter(prefix="/astral", tags=["Astral Color"])
PREVIEW_ON = os.getenv("ASTRAL_REPORT_PREVIEW", "0" if os.getenv("APP_ENV") == "prod" else "1") == "1"


class AstralIn(BaseModel):
    calendar_type: str = "solar"
    birth_date: str
    is_leap_month: bool = False
    birth_time: str = ""
    time_unknown: bool = False
    birth_city: str
    gender: str


@router.post("")
@limiter.limit("60/minute")
def astral_free(request: Request, body: AstralIn):
    try:
        return calculate_astral_profile(body.model_dump())
    except AstralInputError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/report-preview")
@limiter.limit("20/minute")
def astral_report_preview(request: Request, body: AstralIn):
    if not PREVIEW_ON:
        raise HTTPException(403, detail="상세 보고서는 결제 확인 기능이 붙은 뒤에 열립니다.")
    try:
        report = calculate_paid_report(body.model_dump())
    except AstralInputError as e:
        raise HTTPException(400, detail=str(e))
    report["palette8"] = astral_palette.build(report["colors"])
    report["preview"] = True
    return report
