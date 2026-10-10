"""core/sentence_lock.py — 문장 고정 (eng-2.1): 같은 문장이면 언제·어느 서버에서·몇 번을 넣어도 같은 해시·HEX·색상·색 이름.

왜 필요한가 (2026-10-10 팀장 피드백 — 같은 문장 두 번 → 해시·HEX 가 달랐다)
  ① 캐시가 프로세스 메모리(store.CACHE)뿐 → 재배포·재시작·인스턴스가 바뀌면 처음부터 다시 계산
  ② palette 엔진의 해시는 Claude 가 읽은 결과(라벨) 뒤에 정해진다 → 다시 읽으면 라벨이 흔들릴 수 있다
  ③ image_first 엔진은 HEX 를 그림에서 잰다 → 그림을 다시 그리면 HEX 가 바뀐다
해법
  문장 키 = sha256( 정규화한 마스킹 문장 · 엔진·엔진 버전·화가·KB 버전 )
           정규화 = 소문자 · 문장부호 제거 · 공백 전부 제거  ("5월의 오후." == "5월의오후")
  처음 계산한 값(해시·팔레트·정서·검증)을 영구 저장소에 '먼저 쓴 쪽이 이김'으로 고정한다.
  다음부터는 LLM·화가를 부르지 않고 고정값을 돌려준다. 그림은 있으면 같은 그림, 없으면 다시 그려도 값은 고정값.
  같은 서버 안의 동시 요청은 키별 잠금으로 줄을 세우고, 서버가 여러 대면 DB 기본키 충돌로 먼저 쓴 값이 이긴다.
개인정보
  원문은 저장하지 않는다(키는 해시). LLM 요약(memory_summary)은 기본으로 저장하지 않는다 — LOCK_KEEP_SUMMARY=1 일 때만.
끄기: SENTENCE_LOCK=0
"""
from __future__ import annotations
import hashlib, io, json, logging, os, re, threading
from typing import Optional

logger = logging.getLogger("uvicorn")
ENABLED = os.getenv("SENTENCE_LOCK", "1") == "1"
KEEP_SUMMARY = os.getenv("LOCK_KEEP_SUMMARY", "0") == "1"
TABLE = "mac_sentence_locks"
LOCK_VERSION = "lock-1"

_MEM: dict = {}                 # 메모리 저장소 (Supabase 없을 때): key → {"payload":…, "png": bytes|None}
_GUARDS: dict = {}
_GUARDS_LOCK = threading.Lock()


def normalize(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[\s\"'“”‘’`.,!?~·…()\[\]{}:;\-_/]+", "", s)
    return s


def key(masked_text: str, engine: str, engine_version: str, painter: str, kb_version: str) -> str:
    blob = json.dumps([normalize(masked_text), engine, engine_version, painter, kb_version, LOCK_VERSION], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def guard(k: str) -> threading.Lock:
    with _GUARDS_LOCK:
        return _GUARDS.setdefault(k, threading.Lock())


def _sb():
    from utils.supabase_client import supabase_admin
    return supabase_admin


def payload_of(result: dict) -> dict:
    """고정할 값만 고른다 (그림·로그·원문 제외)."""
    keep = ("specimen_hash", "cache_key", "kb_version", "engine_version", "palette", "affect", "verification",
            "grounding")                          # eng-2.2: 어느 코퍼스 문단·연구로 계산했는지도 같이 고정 (원문 없음)
    p = {k: result[k] for k in keep if k in result}
    if KEEP_SUMMARY:
        p["memory_summary"] = result.get("memory_summary", "")
    return p


def get(k: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        row = _MEM.get(k)
        return dict(row["payload"]) if row else None
    try:
        r = sb.table(TABLE).select("payload").eq("key", k).limit(1).execute()
        return r.data[0]["payload"] if r.data else None
    except Exception as ex:                       # 표가 아직 없거나 DB 장애 → 고정 없이 계산 (서비스는 계속)
        logger.warning(f"[lock] 조회 실패 → 고정 없이 계산: {type(ex).__name__}: {str(ex)[:120]}")
        return None


def put_if_absent(k: str, payload: dict, png: Optional[bytes]) -> dict:
    """먼저 쓴 쪽이 이긴다. 돌려주는 값 = 실제로 고정된 값 (내가 졌으면 상대 값)."""
    sb = _sb()
    if sb is None:
        row = _MEM.setdefault(k, {"payload": payload, "png": png})
        return dict(row["payload"])
    img_path = None
    if png:
        try:
            from core.store import BUCKET
            sb.storage.from_(BUCKET).upload(f"locks/{k}.png", png, {"content-type": "image/png"})
            img_path = f"locks/{k}.png"
        except Exception as ex:                   # 이미 있음(다른 서버가 먼저) 또는 업로드 실패 — 값 고정에는 영향 없음
            logger.info(f"[lock] 그림 업로드 생략: {type(ex).__name__}")
    try:
        sb.table(TABLE).upsert({"key": k, "payload": payload, "image_path": img_path,
                                "engine_version": payload.get("engine_version"), "kb_version": payload.get("kb_version")},
                               on_conflict="key", ignore_duplicates=True).execute()
        won = get(k)
        return won if won is not None else payload
    except Exception as ex:
        logger.warning(f"[lock] 저장 실패 → 이번 결과만 반환: {type(ex).__name__}: {str(ex)[:120]}")
        return payload


def image(k: str):
    """고정된 그림 (PIL.Image) 또는 None."""
    from PIL import Image
    sb = _sb()
    try:
        if sb is None:
            png = (_MEM.get(k) or {}).get("png")
        else:
            png = sb.storage.from_(__import__("core.store", fromlist=["BUCKET"]).BUCKET).download(f"locks/{k}.png")
        return Image.open(io.BytesIO(png)).convert("RGB") if png else None
    except Exception:
        return None


def _png(img) -> Optional[bytes]:
    if img is None:
        return None
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()
