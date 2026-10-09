"""
main.py — MaC (Memory & Color) API

보안 계층은 elecai backend(보안 강화판) 패턴을 그대로 따른다:
  1. CORS 화이트리스트          2. slowapi rate limit         3. User-Agent 크롤러 차단(UA_BLOCK=1)
  4. Cloudflare 경유 강제(옵션)   5. 접근 로그(IP 해시)          6. /docs · /openapi.json 비활성(prod)
색채 파이프라인: core/pipeline.py (마스킹 → 특징 추출 → KB 해석 → LCh 합성 → 그림 → ΔE00 검증)
Color Oracle:   routers/oracle_router.py (결정론 색 변환 · 문장 → 팔레트)
"""
import hashlib, logging, os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()
logger = logging.getLogger("uvicorn")
logging.basicConfig(level=logging.INFO)

from routers.analyze_router import router as analyze_router
from routers.specimen_router import router as specimen_router
from routers.concierge_router import router as concierge_router
from routers.auth_router import router as auth_router
from routers.oracle_router import router as oracle_router
from utils.limiter import limiter, client_ip
from core import store
from core.kb import get_resolver
from core.llm import llm_mode

PROD = os.getenv("APP_ENV") == "prod"
app = FastAPI(title="MaC API", version="1.0.0",
              docs_url=None if PROD else "/docs", redoc_url=None, openapi_url=None if PROD else "/openapi.json")

# ── rate limit ───────────────────────────────────────────────────────────
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ─────────────────────────────────────────────────────────────────
_default = ["https://mac.ai.kr", "https://www.mac.ai.kr"] + ([] if PROD else ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5500"])
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()] or _default

# ── User-Agent 차단 (브라우저 앱 전용 API) ─────────────────────────────────
UA_BLOCK = os.getenv("UA_BLOCK", "1") == "1"
BLOCKED_AGENTS = ["python", "curl", "wget", "requests", "scrapy", "selenium", "puppeteer", "beautifulsoup",
                  "httpx", "node-fetch", "bot", "crawler", "spider", "scraper", "go-http-client", "okhttp",
                  "java", "apache-httpclient"]
ALLOWED_BOTS = ["googlebot", "bingbot", "yeti", "duckduckbot", "applebot", "kakao", "daumoa", "facebookexternalhit"]
UA_WHITELIST_PATHS = ("/health", "/favicon.ico")


@app.middleware("http")
async def check_user_agent(request: Request, call_next):
    if not UA_BLOCK or request.method == "OPTIONS" or request.url.path.startswith(UA_WHITELIST_PATHS):
        return await call_next(request)
    ua = request.headers.get("user-agent", "").lower()
    if any(g in ua for g in ALLOWED_BOTS):
        return await call_next(request)
    if not ua or len(ua) < 10:
        return JSONResponse(status_code=403, content={"error": "Invalid User-Agent", "code": "INVALID_UA"})
    if any(b in ua for b in BLOCKED_AGENTS):
        logger.warning(f"🚨 Crawler blocked: {ua[:60]}")
        return JSONResponse(status_code=403, content={"error": "Bot access denied", "code": "BOT_DETECTED"})
    return await call_next(request)


# ── Cloudflare 경유 강제 (CF_GUARD_ENFORCE=1 일 때 차단, 기본은 로그만) ─────
CF_ORIGIN_SECRET = os.getenv("CF_ORIGIN_SECRET", "")
CF_GUARD_ENFORCE = os.getenv("CF_GUARD_ENFORCE", "0") == "1"


@app.middleware("http")
async def cloudflare_only(request: Request, call_next):
    if not CF_ORIGIN_SECRET or request.method == "OPTIONS" or request.url.path.startswith(("/health",)):
        return await call_next(request)
    if request.headers.get("x-origin-verify", "") != CF_ORIGIN_SECRET:
        logger.warning(f"[CF-GUARD] invalid origin header: {request.method} {request.url.path}")
        if CF_GUARD_ENFORCE:
            return JSONResponse(status_code=403, content={"error": "Forbidden", "code": "DIRECT_ACCESS"})
    return await call_next(request)


# ── 접근 로그 (IP는 해시로만 남긴다 — 민감 서비스) ─────────────────────────
@app.middleware("http")
async def access_log(request: Request, call_next):
    response = await call_next(request)
    iph = hashlib.sha256(client_ip(request).encode()).hexdigest()[:10]
    logger.info(f"ACCESS|ip#={iph}|method={request.method}|path={request.url.path}|status={response.status_code}")
    return response


# Vercel 미리보기 주소(color-xxxx-leejaeohs-projects-....vercel.app)까지 허용하려면 정규식으로
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or None

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_origin_regex=CORS_ORIGIN_REGEX,
                   allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"], max_age=600)

app.include_router(auth_router)
app.include_router(analyze_router)
app.include_router(specimen_router)
app.include_router(concierge_router)
app.include_router(oracle_router)


@app.on_event("startup")
def _similar_backfill():
    """임베딩을 쓰면, 벡터가 없는 저장 문장을 백그라운드로 채운다 (서버 응답은 막지 않는다)."""
    import threading
    from oracle import similar
    if similar.method() == "embedding":
        threading.Thread(target=similar.backfill, daemon=True).start()


@app.get("/health")
def health():
    r = get_resolver()
    from oracle.store import get_store
    from oracle import similar
    return {"status": "ok", "kb_version": r.kb.version, "retriever": r.retriever.name, "tau": r.tau,
            "llm_mode": llm_mode(), "store": store.backend(), "oracle_store": get_store().name, "similar": {"method": similar.method(), "model": similar.model_name()}}
