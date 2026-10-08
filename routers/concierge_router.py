"""routers/concierge_router.py — 컨시어지 문의 (게스트 가능, 로그인 시 user_id 연결)."""
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from core import store
from utils.auth import get_optional_payload
from utils.limiter import limiter

router = APIRouter(prefix="/api", tags=["Concierge"])


class ConciergeRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=50)
    contact: str = Field(min_length=3, max_length=100)
    request_type: Literal["acquisition", "bespoke", "partnership", "viewing"]
    message: str = Field(min_length=1, max_length=2000)


@router.post("/concierge")
@limiter.limit("5/hour")
def concierge(request: Request, req: ConciergeRequest, payload: Optional[dict] = Depends(get_optional_payload)):
    rid = store.save_concierge({**req.model_dump(), "user_id": payload.get("sub") if payload else None})
    return {"status": "ok", "id": rid}
