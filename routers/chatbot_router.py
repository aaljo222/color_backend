"""routers/chatbot_router.py — simple async /ask + /result/{id} endpoints

POST /ask            -> {job_id}  (백그라운드 스레드에서 oracle.palette 처리)
GET  /result/{id}    -> {status, result?, error?}

Notes:
- 인메모리 job store (프로세스 단위). 워커를 2개 이상 쓰면 폴링이 깨지므로
  운영에서는 Redis/DB/큐로 교체하세요.
- 완료/오류 job은 TTL(기본 10분) 후 자동 삭제됩니다.
- /ask 는 비용이 드는 호출이라 엄격하게, /result 는 폴링용이라 느슨하게 rate limit 합니다.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import rag as core_rag
from oracle import palette as oracle_palette
from utils.limiter import limiter

logger = logging.getLogger("uvicorn")
router = APIRouter(tags=["Chatbot"])

# {job_id: {status, result, error, created}}
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()

JOB_TTL_SECONDS = 600      # 10분 지난 job 삭제
MAX_JOBS = 1000            # 메모리 폭주 방지 상한

ASK_PATH = "/ask"
RESULT_PATH = "/result/{job_id}"


class AskRequest(BaseModel):
    prompt: Optional[str] = None
    q: Optional[str] = None  # prompt 대신 q 로 보내도 허용


def _cleanup_jobs() -> None:
    """TTL 지난 job 정리. 호출 시 _JOBS_LOCK 을 잡고 있어야 한다."""
    now = time.time()
    expired = [jid for jid, rec in _JOBS.items() if now - rec["created"] > JOB_TTL_SECONDS]
    for jid in expired:
        _JOBS.pop(jid, None)


def _map_source(src: Optional[str]) -> str:
    if not src:
        return "none"
    if src in ("lexicon", "rule", "table"):
        return "paper"
    return "web"


def _build_answer_from_palette(res: dict) -> str:
    try:
        if res.get("status") != "ok":
            return res.get("message") or "색을 찾지 못했어요."
        parts = []
        pal = res.get("palette") or []
        for p in pal[:6]:
            h = p.get("hex") or p.get("color") or p.get("hex_upper") or "#000000"
            name = p.get("name") or p.get("role") or p.get("color_name") or ""
            parts.append(f"{h}{(' ' + name) if name else ''}")
        return "어울리는 색: " + ", ".join(parts) if parts else "적절한 색을 찾지 못했어요."
    except Exception:
        return "응답을 생성하는 중 오류가 발생했습니다."


def _worker(jid: str, text: str) -> None:
    with _JOBS_LOCK:
        if jid in _JOBS:
            _JOBS[jid]["status"] = "running"
    try:
        # NOTE: 새로운 장면은 LLM(유료)을 호출할 수 있음.
        # TODO: 비용이 발생하면 로그인/토큰 검증을 여기서 요구할 것.
        try:
            pal_res = oracle_palette.answer(text, refresh=False, call=None)
        except Exception as e:
            logger.exception("Palette generation failed")
            with _JOBS_LOCK:
                if jid in _JOBS:
                    _JOBS[jid]["status"] = "error"
                    _JOBS[jid]["error"] = str(e)
            return

        citations = []
        try:
            rag = core_rag.get_rag()
            if rag is not None:
                for h in rag.search(text, k=3):
                    citations.append({"cite": h.passage.get("text"), "score": float(h.score)})
        except Exception:
            logger.exception("RAG grounding failed")  # 비치명적

        result = {
            "source": _map_source(pal_res.get("source")),
            "mode": "scene",
            "svg": pal_res.get("thumbnail"),
            "palette": pal_res.get("palette"),
            "answer": _build_answer_from_palette(pal_res),
            "ou_preference": None,
            "citations": citations,
            "raw": pal_res,
        }
        with _JOBS_LOCK:
            if jid in _JOBS:
                _JOBS[jid]["status"] = "done"
                _JOBS[jid]["result"] = result
    except Exception as ex:
        logger.exception("Unexpected error in chatbot worker")
        with _JOBS_LOCK:
            if jid in _JOBS:
                _JOBS[jid]["status"] = "error"
                _JOBS[jid]["error"] = str(ex)


# slowapi 규칙: 함수에 `request: Request` 인자가 반드시 있어야 하고,
# 데코레이터 순서는 @router.xxx 가 위, @limiter.limit 이 아래.
# 바디 인자 이름은 `request` 와 겹치면 안 되므로 `body` 사용.
@router.post(ASK_PATH)
@limiter.limit("20/minute")
def post_ask(request: Request, body: Optional[AskRequest] = None):
    """Body: {"prompt": "..."}  →  {"job_id": "..."}"""
    prompt = None
    if body is not None:
        prompt = body.prompt or body.q
    if not prompt:
        prompt = request.query_params.get("prompt") or request.query_params.get("q")
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt가 필요합니다")
    prompt = str(prompt).strip()

    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _cleanup_jobs()
        if len(_JOBS) >= MAX_JOBS:
            raise HTTPException(status_code=503, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요")
        _JOBS[job_id] = {"status": "pending", "result": None, "error": None, "created": time.time()}

    threading.Thread(target=_worker, args=(job_id, prompt), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.get(RESULT_PATH)
@limiter.limit("180/minute")
def get_result(request: Request, job_id: str):
    """Poll job status. status: pending|running|done|error"""
    with _JOBS_LOCK:
        rec = _JOBS.get(job_id)
        rec = dict(rec) if rec else None
    if not rec:
        raise HTTPException(status_code=404, detail="job_id를 찾을 수 없습니다")

    out = {"status": rec["status"]}
    if rec["status"] == "done":
        out["result"] = rec.get("result")
    elif rec["status"] == "error":
        out["error"] = rec.get("error")
    return JSONResponse(out)