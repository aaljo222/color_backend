"""eng-2.0 그림 먼저 — 측정·심사·설명·캐시가 정해진 규칙대로 도는지 (키 없이 stub/scene 으로)."""
import numpy as np
from core import image_first as imf
from core.affect import compute
from core.kb import KB
from core.color import hex2lab, delta_e_2000
from core.pipeline import analyze
from core.store import LOG_COLUMNS

SCENE = {"background": "#F2E3C9", "shapes": [
    {"kind": "rect", "x": 0, "y": 0.05, "w": 1, "h": 0.35, "color": "#E8A33D", "softness": 0.2},
    {"kind": "rect", "x": 0, "y": 0.55, "w": 1, "h": 0.30, "color": "#2F6E8F", "softness": 0.2},
    {"kind": "ellipse", "x": 0.6, "y": 0.42, "w": 0.25, "h": 0.1, "color": "#D23A3A", "softness": 0.1}]}


def test_measured_hex_comes_from_pixels():
    m = imf.measure(imf.render_scene(SCENE))
    got = [delta_e_2000(c, hex2lab(h)) for h in ("#F2E3C9", "#E8A33D", "#2F6E8F")
           for c in [min(m["centers"], key=lambda c: delta_e_2000(c, hex2lab(h)))]]
    assert max(got) < 8                                    # 그린 색이 측정 4색 안에 있다 (가장자리 번짐 허용)
    assert abs(m["ratios"].sum() - 1) < 1e-6 and m["coverage"] > 0.8


def test_accent_is_the_contrasting_small_color():
    m = imf.measure(imf.render_scene(SCENE))
    assert delta_e_2000(m["centers"][3], hex2lab("#D23A3A")) < 12   # 작은 빨강이 강조색으로 뽑힌다


def test_bad_scene_values_are_dropped():                # 검증 게이트: 잘못된 색·좌표는 그리지 않는다
    img = imf.render_scene({"background": "red", "shapes": [{"kind": "rect", "x": 0, "y": 0, "w": 1, "h": 1, "color": "#ZZZZZZ"}]})
    assert np.asarray(img).std() < 10                       # 회색 배경 + 결뿐


def test_review_uses_affect_bands():
    kb = KB(); emo = kb.by_id["warm_nostalgia"]
    m = imf.measure(imf.render_scene({"background": "#9A9A9A", "shapes": []}))   # 무채 회색
    assert not imf.review(m, compute({"valence": 4, "arousal": 5}, emo))["ok"]  # 각성 5 인데 채도 0 → 다시 그림
    assert imf.review(m, compute({"valence": 3, "arousal": 1}, emo))["ok"]


def test_pipeline_image_first_stub(monkeypatch):
    monkeypatch.setenv("PAINTER", "stub")
    cache = {}
    a = analyze("한여름 할머니 댁 마루에서 수박 먹던 오후", cache=cache, engine="image_first")
    assert a["engine_version"] == "eng-2.0" and a["verification"]["renderer"] == "image:stub"
    assert [p["role"] for p in a["palette"]] == ["dominant", "supporting", "atmospheric", "accent"]
    assert all(p["basis"]["axis"] == "image" and p["basis"]["nearest"]["name"] for p in a["palette"])
    assert set(a["_log"]) | {"specimen_id", "kb_version", "created_at"} <= LOG_COLUMNS
    b = analyze("한여름 할머니 댁 마루에서 수박 먹던 오후", cache=cache, engine="image_first")
    assert b["cache_hit"] and b["_image"] is a["_image"]           # 같은 기억 = 같은 그림


def test_palette_mode_unchanged():
    a = analyze("한여름 할머니 댁 마루에서 수박 먹던 오후", engine="palette")
    assert a["engine_version"] == "eng-1.2"


def test_painter_falls_back_when_gemini_fails(monkeypatch):     # GEMINI 키만 있고 google-genai 미설치여도 502가 나지 않게
    monkeypatch.setenv("PAINTER", "gemini"); monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from core import image_first as imf
    monkeypatch.setattr(imf, "_paint_gemini", lambda p: (_ for _ in ()).throw(ImportError("no google-genai")))
    a = analyze("비 오는 밤 창가에서 할머니를 떠올렸다", engine="image_first")
    assert a["verification"]["renderer"] == "image:stub"


def test_roles_sorted_by_final_area():             # 재배정 뒤 주조 22% < 보조 34% 로 뒤집혀 보이던 문제 (2026-10-10 운영)
    for seed in range(5):
        img = imf._paint_stub("", seed, [{"role": r, "lch": [70 - 10 * i, 30 + 10 * i, 40 * i], "hex": "#C8A27A"}
                                          for i, r in enumerate(imf.ROLES)])
        r = imf.measure(img)["ratios"]
        assert r[0] >= r[1] >= r[2]
