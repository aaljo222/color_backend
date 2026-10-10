"""Astral Color 통합 — /api/astral 경로, 사주 계산값 보존, 8색 팔레트 규칙."""
from fastapi.testclient import TestClient
from main import app
from core import astral_palette
from core.color import delta_e_2000, hex2lab

UA = {"User-Agent": "Mozilla/5.0 (test) AppleWebKit"}
P = {"calendar_type": "solar", "birth_date": "1999-08-05", "birth_time": "18:01", "time_unknown": False,
     "birth_city": "여수시", "gender": "female"}
c = TestClient(app)


def test_free_endpoint_returns_unique_color():
    r = c.post("/api/astral", json=P, headers=UA)
    assert r.status_code == 200
    assert r.json()["free_result"]["color"]["hex"] == "#CBB79B"      # 원본 Astral 엔진과 같은 값


def test_bad_input_is_400_with_message():
    r = c.post("/api/astral", json={**P, "birth_date": "1999-13-40"}, headers=UA)
    assert r.status_code == 400 and "생년월일" in r.json()["detail"]


def test_report_preview_keeps_astral_colors_and_adds_palette8():
    r = c.post("/api/astral/report-preview", json=P, headers=UA).json()
    base = {x["role"]: x["hex"] for x in r["colors"]}
    pal = r["palette8"]
    assert [b["hex"] for b in pal["base"]] == [base[k] for k in astral_palette.ROLES]   # 원색은 그대로
    assert len(pal["complement"]) == 4 and len(pal["neutrals"]) == 4
    assert r["visual_slot_count"] == 8


def test_complement_is_opposite_hue_and_far_in_lightness():
    for hx in ("#CBB79B", "#244B63", "#E7E2D8", "#426B50"):
        L, C, H = astral_palette._ok(hx)
        comp = astral_palette.complement(hx)
        L2, C2, H2 = comp["oklch"]
        dh = abs(((H2 - H) + 180) % 360 - 180)
        assert dh > 150 or C < 0.02                                   # 색상은 반대편 (무채색 원색은 예외)
        assert abs(L2 - L) >= 0.15                                    # 명도 차이를 확실히
        assert delta_e_2000(hex2lab(hx), hex2lab(comp["hex"])) >= 20


def test_palette_is_deterministic():
    cols = c.post("/api/astral/report-preview", json=P, headers=UA).json()["colors"]
    assert astral_palette.build(cols) == astral_palette.build(cols)
