"""core/store.py — 저장소 (Supabase 있으면 DB/Storage, 없으면 메모리). 라우터는 이 함수들만 호출한다.

테이블/버킷/RPC 는 sql/schema.sql 기준.
"""
from __future__ import annotations
import hashlib, io, os, uuid, logging
from datetime import date, datetime, timezone
from utils.supabase_client import supabase_admin as SB
from utils import crypto

logger = logging.getLogger("uvicorn")
BUCKET = os.getenv("SPECIMEN_BUCKET", "specimens")
SIGNED_URL_TTL = int(os.getenv("SIGNED_URL_TTL", "600"))
FREE_CREDITS = int(os.getenv("FREE_CREDITS", "3"))
GUEST_DAILY = int(os.getenv("GUEST_DAILY_LIMIT", "2"))
_now = lambda: datetime.now(timezone.utc).isoformat()

# ── 메모리 대체 저장소 (개발·테스트) ──────────────────────────────────────
_MEM = {"specimens": {}, "texts": {}, "logs": {}, "images": {}, "profiles": {}, "concierge": [], "guest": {}}
CACHE: dict = {}          # cache_key → 결과 (프로세스 캐시)


def backend() -> str:
    return "supabase" if SB is not None else "memory"


# ── 게스트 일일 한도 (IP 해시 · 원본 IP 저장 안 함) ───────────────────────
def guest_quota_ok(ip: str) -> bool:
    k = hashlib.sha256(f"{ip}|{date.today()}".encode()).hexdigest()[:20]
    n = _MEM["guest"].get(k, 0)
    if n >= GUEST_DAILY:
        return False
    _MEM["guest"][k] = n + 1        # ※ 다중 인스턴스면 Redis/DB 카운터로 교체
    return True


# ── 크레딧 (Q1: 추가 인증 계정에만 무료 지급) ─────────────────────────────
def _profile(uid: str) -> dict:
    if SB is None:
        return _MEM["profiles"].setdefault(uid, {"id": uid, "credits": 0, "free_credit_claimed": False})
    r = SB.table("profiles").select("id,credits,free_credit_claimed").eq("id", uid).maybe_single().execute()
    return (r.data if r and r.data else {"id": uid, "credits": 0, "free_credit_claimed": False})


def credit_status(uid: str) -> dict:
    p = _profile(uid)
    return {"credits": p.get("credits", 0), "free_credit_claimed": p.get("free_credit_claimed", False)}


def is_extra_verified(payload: dict) -> bool:
    """소셜 로그인(google·kakao 등) 또는 휴대폰 인증 계정만 True. 이메일 가입만으로는 False."""
    meta = payload.get("app_metadata") or {}
    providers = set(meta.get("providers") or [meta.get("provider")])
    return bool(providers - {"email", None}) or bool(payload.get("phone_confirmed") or payload.get("phone"))


def claim_free_credits(uid: str, payload: dict) -> dict:
    if not is_extra_verified(payload):
        return {"granted": False, "reason": "추가 인증(소셜 로그인 또는 휴대폰 인증) 후 받을 수 있어요."}
    p = _profile(uid)
    if p.get("free_credit_claimed"):
        return {"granted": False, "reason": "이미 받았어요.", **credit_status(uid)}
    if SB is None:
        p.update(credits=p.get("credits", 0) + FREE_CREDITS, free_credit_claimed=True)
    else:
        SB.rpc("claim_free_credits", {"p_user": uid, "p_amount": FREE_CREDITS}).execute()
    return {"granted": True, **credit_status(uid)}


def consume_credit(uid: str) -> bool:
    if SB is None:
        p = _profile(uid)
        if p.get("credits", 0) <= 0:
            return False
        p["credits"] -= 1
        return True
    r = SB.rpc("consume_credit", {"p_user": uid}).execute()   # 원자적 차감, 남은 크레딧 or null
    return r.data is not None and r.data != [] and r.data is not False


# ── 표본 저장 ────────────────────────────────────────────────────────────
LOG_COLUMNS = {"specimen_id", "features", "verify_rows", "masked_text_len", "kb_version", "created_at"}   # sql/schema.sql 4)


def save_specimen(uid: str | None, result: dict, png: bytes, keep_text: str | None) -> str:
    sid = str(uuid.uuid4())
    thumb = _thumb(png)
    row = {"id": sid, "user_id": uid, "specimen_hash": result["specimen_hash"], "cache_key": result["cache_key"],
           "palette": result["palette"], "memory_summary": result["memory_summary"],
           "kb_version": result["kb_version"], "engine_version": result["engine_version"],
           "verification": result["verification"], "image_path": f"{uid or 'guest'}/{sid}.png",
           "thumb_path": f"{uid or 'guest'}/{sid}_t.png", "created_at": _now()}
    log = {"specimen_id": sid, **result.get("_log", {}), "kb_version": result["kb_version"], "created_at": _now()}
    if SB is None:
        _MEM["specimens"][sid] = row; _MEM["logs"][sid] = log
        _MEM["images"][row["image_path"]] = png; _MEM["images"][row["thumb_path"]] = thumb
    else:
        if not _upload_images(row["image_path"], png, row["thumb_path"], thumb):
            row["image_path"] = row["thumb_path"] = None   # 그림은 팔레트로 언제든 다시 그릴 수 있다 → 표본은 저장
        SB.table("memory_specimens").insert(row).execute()
        try:                                        # 운영 로그 실패가 사용자 표본 저장을 깨지 않게
            SB.table("generation_logs").insert({k: v for k, v in log.items() if k in LOG_COLUMNS}).execute()
        except Exception as ex:
            logger.warning(f"[store] generation_logs 저장 실패(표본은 저장됨): {type(ex).__name__}: {str(ex)[:160]}")
    if keep_text and uid:
        enc = crypto.encrypt(keep_text)            # 키 없으면 예외 → 라우터가 400
        trow = {"specimen_id": sid, "user_id": uid, "text_enc": enc, "keep_consent": True, "created_at": _now()}
        if SB is None:
            _MEM["texts"][sid] = trow
        else:
            SB.table("memory_texts").insert(trow).execute()
    return sid


_bucket_ok = False
def _ensure_bucket() -> None:
    """Storage 버킷이 없으면 비공개로 만든다 (service_role 키 필요). 한 번만 시도."""
    global _bucket_ok
    if _bucket_ok:
        return
    try:
        SB.storage.get_bucket(BUCKET)
    except Exception:
        try:
            SB.storage.create_bucket(BUCKET, options={"public": False})
            logger.info(f"[store] Storage 버킷 '{BUCKET}' 생성")
        except Exception as ex:
            logger.warning(f"[store] 버킷 생성 실패: {type(ex).__name__}: {str(ex)[:120]}")
    _bucket_ok = True


def _upload_images(img_path: str, png: bytes, thumb_path: str, thumb: bytes) -> bool:
    """그림 업로드. 실패해도 예외를 올리지 않는다 (크레딧을 쓴 표본 저장을 막지 않기 위해)."""
    for attempt in range(2):
        try:
            if attempt:
                _ensure_bucket()
            st = SB.storage.from_(BUCKET)
            st.upload(img_path, png, {"content-type": "image/png"})
            st.upload(thumb_path, thumb, {"content-type": "image/png"})
            return True
        except Exception as ex:
            logger.warning(f"[store] 그림 업로드 실패({attempt + 1}): {type(ex).__name__}: {str(ex)[:120]}")
    return False


def refund_credit(uid: str) -> None:
    """저장이 실패했을 때 방금 쓴 크레딧 1을 되돌린다."""
    try:
        if SB is None:
            _profile(uid)["credits"] += 1
            return
        p = _profile(uid)
        SB.table("profiles").update({"credits": p.get("credits", 0) + 1}).eq("id", uid).execute()
    except Exception as ex:
        logger.error(f"[store] 크레딧 환불 실패 uid={uid[:8]}: {type(ex).__name__}")


def _thumb(png: bytes) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(png)); im.thumbnail((240, 300))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def find_owned(uid: str, cache_key: str) -> str | None:
    if SB is None:
        return next((r["id"] for r in _MEM["specimens"].values() if r["user_id"] == uid and r["cache_key"] == cache_key), None)
    r = SB.table("memory_specimens").select("id").eq("user_id", uid).eq("cache_key", cache_key).limit(1).execute()
    return r.data[0]["id"] if r.data else None


def list_specimens(uid: str) -> list[dict]:
    cols = "id,specimen_hash,palette,memory_summary,created_at"
    if SB is None:
        rows = [r for r in _MEM["specimens"].values() if r["user_id"] == uid]
    else:
        rows = SB.table("memory_specimens").select(cols + ",thumb_path").eq("user_id", uid).order("created_at", desc=True).limit(50).execute().data or []
    return [{**{k: r[k] for k in cols.split(",")}, "thumb_url": signed_url(r["thumb_path"])} for r in rows]


def get_specimen(uid: str, sid: str) -> dict | None:
    if SB is None:
        r = _MEM["specimens"].get(sid)
    else:
        res = SB.table("memory_specimens").select("*").eq("id", sid).eq("user_id", uid).maybe_single().execute()
        r = res.data if res else None
    if not r or r["user_id"] != uid:
        return None
    return {k: v for k, v in r.items() if k not in ("image_path", "thumb_path")} | {
        "image_url": signed_url(r["image_path"]), "thumb_url": signed_url(r["thumb_path"])}


def signed_url(path: str | None) -> str | None:
    if not path:
        return None                              # 그림 업로드가 실패했던 표본 → 프론트가 팔레트로 그린다
    if SB is None:
        return f"/api/dev/images/{path}"        # 개발 모드 전용 경로 (프론트가 API 주소를 앞에 붙인다)
    r = SB.storage.from_(BUCKET).create_signed_url(path, SIGNED_URL_TTL)
    return r.get("signedURL") or r.get("signedUrl") or r.get("signed_url", "")


def dev_image(path: str) -> bytes | None:
    return _MEM["images"].get(path)


def save_concierge(row: dict) -> str:
    row = {"id": str(uuid.uuid4()), "status": "new", "created_at": _now(), **row}
    if crypto.enabled():                       # 연락처는 키가 있으면 암호화 저장
        row["contact_enc"] = crypto.encrypt(row.pop("contact")); row["contact"] = None
    if SB is None:
        _MEM["concierge"].append(row)
    else:
        SB.table("concierge_requests").insert(row).execute()
    return row["id"]
