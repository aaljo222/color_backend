"""utils/mailer.py — Resend 로 HEX 컬러칩 메일 발송 (MaC 기존 기능 유지). 실패해도 결과 응답은 막지 않는다."""
import os, logging, html
import httpx

logger = logging.getLogger("uvicorn")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM", "MaC <mac@mac.ai.kr>")


def send_palette(to: str, result: dict) -> bool:
    if not RESEND_API_KEY:
        return False
    chips = "".join(
        f'<td style="background:{p["hex"]};width:{int(p["area_ratio"]*100)}%;height:80px"></td>' for p in result["palette"])
    codes = " · ".join(f'{html.escape(p["color_name"])} {p["hex"]}' for p in result["palette"])
    body = (f'<p>{html.escape(result.get("memory_summary",""))}</p><table width="100%" cellspacing="0"><tr>{chips}</tr></table>'
            f'<p>{codes}</p><p style="color:#888">{result["specimen_hash"]}</p>')
    try:
        r = httpx.post("https://api.resend.com/emails", timeout=10,
                       headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                                "Idempotency-Key": f'{result["cache_key"]}-{abs(hash(to))}'},
                       json={"from": MAIL_FROM, "to": [to], "subject": "당신의 기억 색 — MaC SPECIMEN", "html": body})
        return r.status_code < 300
    except Exception as ex:
        logger.warning(f"[mail] 발송 실패(결과는 정상 반환): {type(ex).__name__}")
        return False
