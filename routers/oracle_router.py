"""routers/oracle_router.py — Color Oracle: 색 값은 LLM 이 아니라 계산기가 정한다.

  GET  /api/oracle?op=…            결정론 변환 (hex2oklch · oklch2hex · hex2lch · lch2hex · scale · step · selfcheck · tools)
  POST /api/oracle                 외부 LLM 의 tool_use 를 그대로 실행 {name, input}
  POST /api/palette                문장 → 팔레트 (캐시 → 규칙 → 어휘사전 → 처음 보는 장면만 Claude 등급 1회 → 오라클)
  GET  /api/palette/similar?q=     비슷한 저장 문장 후보 (LLM 0회 · 결과를 바꾸지 않음)
  GET  /api/palette/gallery        저장된 문장 썸네일 목록
  GET  /api/palette/thumb?prompt=  저장된 문장의 썸네일 SVG
게스트 허용 + rate limit. LLM 을 부르는 경로는 /api/palette 하나뿐이다.
"""
import hashlib, os
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from oracle import tools, palette, similar, color_abstraction as ca
from oracle.store import get_store
from utils.limiter import limiter, client_ip
from utils.auth import get_optional_payload

# 게스트가 '처음 보는 장면'으로 LLM 을 부를 수 있는 하루 횟수 (IP 해시 기준, 로그인 사용자는 제한 없음)
LLM_DAILY = int(os.getenv("ORACLE_LLM_DAILY", "20"))
_llm_count: dict = {}   # ※ 다중 인스턴스면 DB/Redis 로 교체 (MaC 게스트 한도와 같은 한계)


def _llm_quota_ok(ip: str) -> bool:
    k = hashlib.sha256(f"oracle|{ip}|{date.today()}".encode()).hexdigest()[:20]
    n = _llm_count.get(k, 0)
    if n >= LLM_DAILY:
        return False
    _llm_count[k] = n + 1
    return True

router = APIRouter(prefix="/api", tags=["Color Oracle"])


@router.get("/oracle")
@limiter.limit("120/minute")
def oracle_get(request: Request, op: str = ""):
    q = {k: v for k, v in request.query_params.items() if k != "op"}
    if op == "selfcheck":
        return tools.selfcheck()
    if op == "tools":
        return tools.TOOLS
    if not op:
        raise HTTPException(400, detail={"error": "op가 필요합니다", "ops": [t["name"] for t in tools.TOOLS] + ["selfcheck", "tools"]})
    try:
        return tools.run_tool(op, q)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


class ToolCall(BaseModel):
    name: str
    input: dict = Field(default_factory=dict)


@router.post("/oracle")
@limiter.limit("120/minute")
def oracle_post(request: Request, call: ToolCall):
    try:
        return {"name": call.name, "result": tools.run_tool(call.name, call.input)}
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


class PaletteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=300)
    refresh: bool = False


@router.post("/palette")
@limiter.limit("20/minute")
def palette_ask(request: Request, req: PaletteRequest, payload: Optional[dict] = Depends(get_optional_payload)):
    def guarded(p, lexicon):                     # LLM 이 실제로 필요할 때만 불린다 (캐시·규칙·사전으로 끝나면 안 불림)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise palette.LLMError("처음 보는 장면이라 LLM이 필요한데 서버에 ANTHROPIC_API_KEY가 없습니다")
        if payload is None and not _llm_quota_ok(client_ip(request)):
            raise palette.LLMError("오늘 새 장면 추상화 횟수를 다 썼어요. 로그인하면 계속할 수 있어요.")
        return palette._call_claude(p, lexicon)
    try:
        out = palette.answer(req.prompt, refresh=req.refresh, call=guarded)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except palette.LLMError as e:
        raise HTTPException(502, detail=str(e))
    out["similar"] = _with_thumbs(similar.find(req.prompt, k=3, exclude_key=out.get("key")))
    return out


def _with_thumbs(found: dict) -> dict:
    for x in found["items"]:
        x["thumbnail"] = palette._thumb_uri(x["prompt"], x.pop("palette"))
    return found


@router.get("/palette/similar")
@limiter.limit("60/minute")
def palette_similar(request: Request, q: str = "", k: int = 3):
    """입력 중 추천: 이미 저장된 비슷한 문장. 누르면 그 문장의 저장 결과를 불러온다 (LLM 0회)."""
    return _with_thumbs(similar.find(q[:300], k=max(1, min(k, 6))))


@router.get("/palette/gallery")
@limiter.limit("60/minute")
def palette_gallery(request: Request, limit: int = 24):
    return {"items": palette.gallery(max(1, min(limit, 48)))}


@router.get("/palette/thumb")
@limiter.limit("120/minute")
def palette_thumb(request: Request, prompt: str):
    hit = get_store().get_prompt(ca.normalize(prompt), count=False)
    if not hit:
        raise HTTPException(404, detail="저장된 문장이 아닙니다")
    return Response(ca.thumbnail_svg(hit["prompt"], hit["palette"]), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300"})
