"""Vercel serverless endpoint for deterministic Astral Color calculations."""

from http.server import BaseHTTPRequestHandler
import json

from astral.engine import AstralInputError, calculate_astral_profile
from astral.test_storage import save_free_result_for_demo


def process_astral_request(data: dict):
    try:
        result = calculate_astral_profile(data)
        if save_free_result_for_demo(result):
            result["test_storage"] = "saved"
        return 200, result
    except AstralInputError as exc:
        return 400, {"status": "error", "error": str(exc)}


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._send_json(405, {"status": "error", "error": "Method not allowed"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"status": "error", "error": "유효하지 않은 요청입니다."})
            return

        try:
            status_code, payload = process_astral_request(data)
        except Exception as exc:
            print(f"[Astral Error] {exc}")
            status_code, payload = 500, {
                "status": "error",
                "error": "계산 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            }
        self._send_json(status_code, payload)
