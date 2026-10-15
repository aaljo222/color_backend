"""Complete Astral results from one request; no account or payment required."""
import json

from api.astral import handler as JsonHandler
from astral.engine import AstralInputError, calculate_report
from api.astral_art import make_art_package


def process_astral_report_request(data, owner=None):
    if not isinstance(data, dict):
        return 400, {"status": "error", "error": "출생정보 형식을 확인해 주세요."}
    try:
        report = calculate_report(data)
        report['artwork'] = make_art_package(report, owner=owner)
        return 200, report
    except AstralInputError as exc:
        return 400, {"status": "error", "error": str(exc)}


class handler(JsonHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"status": "error", "error": "유효하지 않은 요청입니다."})
            return
        try:
            status, report = process_astral_report_request(data)
        except Exception:
            status, report = 500, {"status": "error", "error": "계산 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}
        self._send_json(status, report)
