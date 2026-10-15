"""
================================================================================
MaC (Memory & Color) Architecture — Vercel Serverless Pipeline Handler
================================================================================
[설계 목적]
1. 비즈니스 로직과 모델 공급자 간의 완전한 결합 분리(services/llm_engine.py 연동).
2. 4색 HEX 및 면적비(0.45, 0.30, 0.15, 0.10) 가중치를 CIELAB 공간에서 벡터 합성하여
   개인 고유 암호 해시 'MaC-L.C.H' 도출.
3. 원본 emailTemplate.html의 다크 씰 토글(<details>/<summary>) 및 슬림 2x2 카드 복원.
4. CORS 프리플라이트 및 Resend 트랜잭션 메일 발송 처리.
5. Vercel Python 런타임이 실제로 인식하는 BaseHTTPRequestHandler 진입점 적용.
6. 4대 계층별 예외 처리 기준(400 유효성, 502 AI 재시도, HEX 정규식 검증, Non-blocking 이메일) 완비.
7. [신규 추가] 컨시어지 문의 폼(Concierge@mac.ai.kr) 단일 관문 라우팅 분기 처리 완비.
================================================================================
"""

from http.server import BaseHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv
import json
import math
import os
import re
import resend

# 환경 변수 로드
load_dotenv()

# Resend API Key 설정
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# 분리된 프롬프트 빌더 및 고가용성 AI 추론 엔진 임포트
try:
    from prompts.color_prompt import build_system_prompt
    from services.llm_engine import analyze_memory_with_llm
except ImportError:
    from color_prompt import build_system_prompt
    from llm_engine import analyze_memory_with_llm

# 정규식 패턴 사전 컴파일
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
HEX_COLOR_REGEX = re.compile(r"^#[0-9A-F]{6}$")


# ------------------------------------------------------------------------------
# 1. 색채 물리학 연산 엔진 (sRGB -> CIE XYZ -> CIELAB -> 가중 LCH 해시)
# ------------------------------------------------------------------------------
def hex_to_rgb(hex_str: str):
    """HEX(#RRGGBB)를 0.0 ~ 1.0 선형 전 RGB 값으로 변환"""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return 0.5, 0.5, 0.5
    return (
        int(hex_str[0:2], 16) / 255.0,
        int(hex_str[2:4], 16) / 255.0,
        int(hex_str[4:6], 16) / 255.0,
    )

def srgb_to_xyz(r: float, g: float, b: float):
    """sRGB 감마(γ=2.4) 역보정 후 D65 백색광 기준 CIE XYZ 변환"""
    def linearize(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = linearize(r), linearize(g), linearize(b)
    X = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    Y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    Z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    return X, Y, Z

def xyz_to_lab(X: float, Y: float, Z: float):
    """CIE XYZ를 인간 지각 균등 공간인 CIELAB(L*, a*, b*)으로 변환"""
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883
    xr, yr, zr = X / Xn, Y / Yn, Z / Zn

    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t) + (16.0 / 116.0)

    fx, fy, fz = f(xr), f(yr), f(zr)
    L = (116.0 * fy) - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b

def compute_weighted_lch_hash(palette: list) -> str:
    """CIELAB 공간 내 가중 중심점을 구하고 고유 암호 해시(MaC-L.C.H) 산출"""
    total_weight = sum(item.get("weight", item.get("area_ratio", 0.25)) for item in palette)
    if total_weight <= 0:
        total_weight = 1.0

    weighted_L = 0.0
    weighted_a = 0.0
    weighted_b = 0.0

    for item in palette:
        w = item.get("weight", item.get("area_ratio", 0.25)) / total_weight
        r, g, b = hex_to_rgb(item.get("hex", "#888888"))
        X, Y, Z = srgb_to_xyz(r, g, b)
        L, a, b_val = xyz_to_lab(X, Y, Z)

        weighted_L += L * w
        weighted_a += a * w
        weighted_b += b_val * w

    chroma = math.sqrt(weighted_a ** 2 + weighted_b ** 2)
    hue_rad = math.atan2(weighted_b, weighted_a)
    hue_deg = math.degrees(hue_rad)
    if hue_deg < 0:
        hue_deg += 360.0

    l_int = int(round(weighted_L))
    c_int = int(round(chroma))
    h_int = int(round(hue_deg))

    return f"MaC-{l_int:02d}.{c_int:02d}.{h_int:03d}"


# ------------------------------------------------------------------------------
# 2. 데이터 형식 검증 유틸리티
# ------------------------------------------------------------------------------
def validate_palette_schema_and_hex(palette: list) -> bool:
    """[HEX 데이터 형식 오류 검증] 정확히 4개 색상인지 및 대문자 6자리 HEX(^#[0-9A-F]{6}$) 충족 여부 확인"""
    if not isinstance(palette, list) or len(palette) != 4:
        return False
    for chip in palette:
        hex_code = str(chip.get("hex", "")).strip().upper()
        chip["hex"] = hex_code  # 일관되게 대문자로 보정
        if not HEX_COLOR_REGEX.match(hex_code):
            return False
    return True


# ------------------------------------------------------------------------------
# 3. 핵심 비즈니스 로직 (요청 처리 → 응답 payload 생성까지)
# ------------------------------------------------------------------------------
def process_request(data: dict):
    """
    요청 데이터(dict)를 받아 (status_code, response_dict) 튜플을 반환합니다.
    """
    # ==========================================================================
    # [신규 분기] 컨시어지 문의 폼 접수 처리
    # - Vercel 단일 엔드포인트(/api/analyze)를 공유하여 라우트 유실(404)을 원천 차단합니다.
    # - AI 추론을 거치지 않고 바로 Resend를 통해 Concierge@mac.ai.kr(네이버웍스)로 발송합니다.
    # ==========================================================================
    if data.get("type") == "concierge_inquiry":
        client_name = str(data.get("client_name", "익명")).strip()
        client_contact = str(data.get("client_contact", "")).strip()
        subject_type = str(data.get("subject", "일반 문의")).strip()
        message = str(data.get("message", "")).strip()

        # 필수 입력값 검증
        if not client_contact or not message:
            return 400, {"status": "error", "error": "회신 연락처와 문의 내용을 입력해 주세요."}

        # 문의 유형 텍스트 매핑 가독성 처리
        subject_map = {
            "artwork": "Acquisition of Curated Artwork (전시작 원화 소장)",
            "bespoke": "Bespoke Memory Color Commission (1:1 맞춤 조색 의뢰)",
            "partnership": "Confidential Partnership & Curation (비공개 협업 및 전시 대관)",
            "viewing": "Private Salon Viewing (프라이빗 뷰잉 세션 예약)"
        }
        subject_title = subject_map.get(subject_type, subject_type)

        # 네이버웍스 메일함으로 전달될 우아한 미니멀 HTML 서식 생성
        inquiry_html = f"""
        <div style="max-width: 620px; margin: 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Pretendard', sans-serif; color: #2b2725; line-height: 1.7; border: 1px solid #eae6e1; border-radius: 12px; overflow: hidden; background: #ffffff;">
          <div style="background: #3a3430; padding: 24px 32px; color: #f7f6f4;">
            <p style="margin: 0; font-size: 11px; letter-spacing: 0.25em; text-transform: uppercase; color: #c4baa9;">MaC Architecture of Memory &amp; Color</p>
            <h2 style="margin: 6px 0 0 0; font-size: 20px; font-weight: 700; letter-spacing: -0.01em; color: #ffffff;">프라이빗 컨시어지 문의가 접수되었습니다</h2>
          </div>
          <div style="padding: 32px;">
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
              <tr style="border-bottom: 1px solid #f0ede8;">
                <td style="padding: 12px 0; width: 120px; font-size: 12.5px; font-weight: 700; color: #8c827a; letter-spacing: 0.1em; text-transform: uppercase;">CLIENT NAME</td>
                <td style="padding: 12px 0; font-size: 15px; font-weight: 600; color: #1c1917;">{client_name}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f0ede8;">
                <td style="padding: 12px 0; font-size: 12.5px; font-weight: 700; color: #8c827a; letter-spacing: 0.1em; text-transform: uppercase;">CONTACT INFO</td>
                <td style="padding: 12px 0; font-size: 15px; font-weight: 600; color: #8c7042;">{client_contact}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f0ede8;">
                <td style="padding: 12px 0; font-size: 12.5px; font-weight: 700; color: #8c827a; letter-spacing: 0.1em; text-transform: uppercase;">REQUEST TYPE</td>
                <td style="padding: 12px 0; font-size: 14px; font-weight: 600; color: #383330;">{subject_title}</td>
              </tr>
            </table>

            <p style="font-size: 12px; font-weight: 700; color: #8c827a; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 8px;">PRIVATE NOTE</p>
            <div style="background: #faf8f5; border-left: 3.5px solid #8c7042; padding: 18px 20px; border-radius: 4px; font-size: 14.5px; color: #383330; line-height: 1.8; white-space: pre-wrap;">{message}</div>

            <div style="margin-top: 36px; padding-top: 20px; border-top: 1px solid #eae6e1; font-size: 11.5px; color: #a39c94; text-align: center;">
              본 메일은 MaC 웹사이트 Color Concierge 데스크에서 실시간 자동 발송되었습니다.
            </div>
          </div>
        </div>
        """

        # Resend를 사용하여 관리자 네이버웍스 메일함(Concierge@mac.ai.kr)으로 전달
        try:
            if RESEND_API_KEY:
                resend.Emails.send({
                    "from": "MaC Concierge <curator@mac.ai.kr>",
                    "to": ["Concierge@mac.ai.kr"],
                    "subject": f"[MaC Desk] {client_name}님의 프라이빗 문의",
                    "html": inquiry_html,
                })
            return 200, {"status": "success", "message": "문의가 성공적으로 전달되었습니다."}
        except Exception as send_err:
            print(f"[Concierge Mail Send Error]: {send_err}")
            return 500, {"status": "error", "error": "문의 메일 전송 중 통신 오류가 발생했습니다."}

    # ==========================================================================
    # [기존 로직] 색채 표본 분석 및 발송 처리 (불변)
    # ==========================================================================
    memory = str(data.get("memory", "")).strip()
    email = str(data.get("email", "")).strip()

    # [예외 기준 1] 입력 유효성 검증 실패 (HTTP 400 Bad Request)
    if not memory or len(memory) < 10:
        return 400, {"error": "기억 문장을 최소 10자 이상 구체적으로 입력해 주세요."}

    if not email or not EMAIL_REGEX.match(email):
        return 400, {"error": "올바른 이메일 주소 형식을 입력해 주세요."}

    # [예외 기준 2 & 3] AI 추론/JSON 파싱 및 HEX 검증 (실패 시 최대 1회 즉시 재호출)
    system_prompt = build_system_prompt()
    full_prompt = f"{system_prompt}\n\n[입력된 사용자 기억 사연]\n\"{memory}\""

    result_json = None
    palette = []

    for attempt in range(2):
        try:
            temp_result = analyze_memory_with_llm(full_prompt)
            if not isinstance(temp_result, dict):
                temp_result = json.loads(temp_result)

            candidate_palette = temp_result.get("palette", [])
            if validate_palette_schema_and_hex(candidate_palette):
                result_json = temp_result
                palette = candidate_palette
                break
        except Exception as retry_err:
            print(f"[AI Synthesis Attempt {attempt + 1} Failed]: {retry_err}")
            continue

    if not result_json or not palette:
        return 502, {"error": "색채 표본 추출에 실패했습니다. 문장을 조금 더 구체적으로 작성해 주세요."}

    memory_summary = result_json.get("memory_summary", memory)

    # 면적비 가중치 기반 고유 암호 해시(MaC-L.C.H) 산출
    specimen_hash = compute_weighted_lch_hash(palette)
    result_json["specimen_hash"] = specimen_hash
    result_json["specimen_code"] = specimen_hash

    # emailTemplate.html 바인딩
    template_path = Path(__file__).resolve().parent.parent / "emailTemplate.html"
    rendered_html = ""
    if template_path.exists():
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                rendered_html = f.read()

            rendered_html = rendered_html.replace("{{ specimen_hash }}", specimen_hash)
            rendered_html = rendered_html.replace("{{specimen_hash}}", specimen_hash)
            rendered_html = rendered_html.replace("{{SPECIMEN_HASH}}", specimen_hash)

            rendered_html = rendered_html.replace("{{ memory_summary }}", memory_summary)
            rendered_html = rendered_html.replace("{{memory_summary}}", memory_summary)
            rendered_html = rendered_html.replace("{{MEMORY_SUMMARY}}", memory_summary)
            rendered_html = rendered_html.replace("{{USER_MEMORY}}", memory)

            for i in range(4):
                chip = palette[i] if i < len(palette) else {}
                c_name = chip.get("color_name", f"Color {i + 1}")
                c_hex = chip.get("hex", "#CCCCCC").upper()

                rendered_html = rendered_html.replace(f"{{{{ palette[{i}].color_name }}}}", c_name)
                rendered_html = rendered_html.replace(f"{{{{palette[{i}].color_name}}}}", c_name)
                rendered_html = rendered_html.replace(f"{{{{ palette[{i}].hex }}}}", c_hex)
                rendered_html = rendered_html.replace(f"{{{{palette[{i}].hex}}}}", c_hex)
        except Exception as t_err:
            print(f"[Template Render Warning]: {t_err}")

    # [예외 기준 4] Resend 트랜잭션 메일 발송 처리 (Non-blocking)
    email_sent = True
    email_error_log = None

    if RESEND_API_KEY and rendered_html:
        try:
            params = {
                "from": "MaC <curator@mac.ai.kr>",
                "to": [email],
                "subject": f"MaC Chromatic Specimen [{specimen_hash}]",
                "html": rendered_html,
            }
            resend.Emails.send(params)
        except Exception as mail_err:
            email_sent = False
            email_error_log = str(mail_err)
            print(f"[Resend Non-blocking Error]: {email_error_log}")
    else:
        email_sent = False

    response_payload = {
        "status": "success",
        "message": "색채 표본이 성공적으로 추출되었습니다.",
        "hash": specimen_hash,
        "specimen_code": specimen_hash,
        "palette": palette,
        "memory_summary": memory_summary,
        "email_sent": email_sent,
        "email_error": email_error_log,
        "data": result_json,
    }

    return 200, response_payload


# ------------------------------------------------------------------------------
# 4. Vercel Serverless 진입점 (BaseHTTPRequestHandler)
# ------------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):

    def _send_json(self, status_code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # 브라우저 사전 요청 (CORS 프리플라이트) 처리
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._send_json(405, {"error": "Method not allowed"})

    def do_POST(self):
        # JSON 본문(Body) 데이터 수신 및 파싱
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            data = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "유효하지 않은 JSON 데이터입니다."})
            return

        try:
            status_code, payload = process_request(data)
        except Exception as unexpected_err:
            print(f"[Unhandled Error]: {unexpected_err}")
            self._send_json(500, {"error": "서버 내부 오류가 발생했습니다."})
            return

        self._send_json(status_code, payload)