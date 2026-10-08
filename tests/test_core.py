"""핵심 엔진 테스트 — 백서 실험 E1~E4 와 같은 성질을 회귀 테스트로 고정."""
from core.color import delta_e_2000, hex2lab, lab2hex
from core.kb import KB, NgramRetriever, Resolver
from core.synth import synthesize
from core.render import render_color_field
from core.verify import verify
from core.pii import mask
from utils import crypto

SHARMA = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425), ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
          ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492), ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
          ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065), ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373)]


def test_ciede2000_sharma():
    for a, b, exp in SHARMA:
        assert abs(delta_e_2000(a, b) - exp) < 1e-3


def test_hex_roundtrip():
    for h in ["#7CA5B8", "#FFB7C5", "#A0522D", "#000000", "#FFFFFF"]:
        assert lab2hex(hex2lab(h)) == h


def _resolver():
    kb = KB(); return Resolver(kb, NgramRetriever(kb), 0.15)


def _res(r, e, t, s, q):
    return {"emotion": r.resolve("emotion", e), "time": r.resolve("time", t),
            "space": r.resolve("space", s), "quality": r.resolve("quality", q)}


def test_determinism_paraphrase_same_palette():          # E2
    r = _resolver()
    a = synthesize(_res(r, "설렘 가득한 기쁨", "오후", "놀이공원", "소중한 기억"), r.kb)
    b = synthesize(_res(r, "신나서 웃음이 났던", "햇살 좋은 낮", "회전목마 있는 테마파크", "따뜻한 기억"), r.kb)
    assert [p["hex"] for p in a["palette"]] == [p["hex"] for p in b["palette"]]
    assert a["cache_key"] == b["cache_key"]
    assert len({str(synthesize(_res(r, "설렘", "오후", "놀이공원", "소중한"), r.kb)) for _ in range(50)}) == 1


def test_area_ratio_constant_and_sum():
    r = _resolver()
    p = synthesize(_res(r, "그리움", "해질녘", "바닷가", "희미한"), r.kb)["palette"]
    assert [x["area_ratio"] for x in p] == [0.45, 0.30, 0.15, 0.10]
    assert abs(sum(x["area_ratio"] for x in p) - 1.0) < 1e-9


def test_resolution_paths():                             # E3
    r = _resolver()
    assert r.resolve("space", "장마 끝난 오후 창가").how == "keyword"
    x = r.resolve("emotion", "보고프던 마음")
    assert x.how in ("retrieval", "fallback")
    assert r.resolve("emotion", "처음 느낀 낯선 감정").how == "fallback"
    assert r.resolve("emotion", "알 수 없는", label="calm_peace").how == "label"
    assert r.resolve("emotion", "알 수 없는", label="sea").how != "label"      # 다른 축 라벨은 거부


def test_verify_pass_and_drift_fail():                   # E4
    r = _resolver()
    syn = synthesize(_res(r, "설렘", "오후", "놀이공원", "소중한"), r.kb)
    ok = verify(syn["palette"], render_color_field(syn["palette"], syn["cache_key"]))
    bad = verify(syn["palette"], render_color_field(syn["palette"], syn["cache_key"], drift=(-6, 1.35, 18)))
    assert ok["status"] == "PASS" and ok["max_de00"] < 5
    assert bad["status"] == "FAIL" and bad["max_de00"] > 5


def test_pii_mask():
    t, st = mask("지수랑 바닷가랑 갔던 날 010-1234-5678 a@b.com", protect={"바닷가"})
    assert "010" not in t and "a@b.com" not in t and "지수" not in t and "바닷가" in t
    t2, _ = mask("엄마랑 할머니 댁에서", protect=set())
    assert t2 == "엄마랑 할머니 댁에서"


def test_crypto_roundtrip():
    tok = crypto.encrypt("소중한 기억")
    assert "소중한" not in tok and crypto.decrypt(tok) == "소중한 기억"
