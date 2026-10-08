"""routers/specimen_router.py — 내 표본 목록/상세, 크레딧 (모두 로그인 필요, 본인 행만)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from core import store
from utils.auth import get_current_payload, get_current_user_id

router = APIRouter(prefix="/api", tags=["Specimen"])


@router.get("/specimens")
def my_specimens(uid: str = Depends(get_current_user_id)):
    return {"items": store.list_specimens(uid)}


@router.get("/specimens/{sid}")
def my_specimen(sid: str, uid: str = Depends(get_current_user_id)):
    r = store.get_specimen(uid, sid)
    if not r:
        raise HTTPException(status_code=404, detail="표본을 찾을 수 없습니다.")
    return r


@router.get("/me/credits")
def my_credits(uid: str = Depends(get_current_user_id)):
    return store.credit_status(uid)


@router.post("/me/credits/claim")
def claim(payload: dict = Depends(get_current_payload)):
    return store.claim_free_credits(payload["sub"], payload)


@router.get("/dev/images/{path:path}", include_in_schema=False)
def dev_image(path: str):
    """메모리 저장소 개발 모드 전용. Supabase 모드에서는 signed URL 을 쓴다."""
    if store.backend() != "memory":
        raise HTTPException(status_code=404)
    b = store.dev_image(path)
    if b is None:
        raise HTTPException(status_code=404)
    return Response(b, media_type="image/png")
