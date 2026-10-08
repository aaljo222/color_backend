# -*- coding: utf-8 -*-
"""oracle/tools.py — 오라클 함수 디스패처 (입력 검증 포함). /api/oracle 과 외부 LLM 도구 호출이 같이 쓴다."""
import io, json, os, contextlib
from oracle import color_oracle as co

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "tool_schema.json"), encoding="utf-8") as f:
    TOOLS = json.load(f)


def _num(v, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 값이 숫자가 아닙니다: {v!r}")
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{name} 값이 유효하지 않습니다")
    return x


def _hex(v):
    if not isinstance(v, str):
        raise ValueError("hex가 필요합니다 (#rrggbb 또는 #rgb)")
    s = v.strip().lstrip("#")
    if len(s) not in (3, 6) or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ValueError(f"HEX 형식이 아닙니다: {v!r}")
    return "#" + s.lower()


def run_tool(name, inp):
    if name == "hex2oklch":
        return co.hex2oklch(_hex(inp.get("hex")))
    if name == "hex2lch":
        return co.hex2lch(_hex(inp.get("hex")))
    if name == "oklch2hex":
        L, C, H = _num(inp.get("L"), "L"), _num(inp.get("C"), "C"), _num(inp.get("H"), "H")
        if not 0 <= L <= 1: raise ValueError("OKLCH L은 0~1입니다")
        if not 0 <= C <= 0.5: raise ValueError("OKLCH C는 0~0.5입니다")
        return co.oklch2hex(L, C, H % 360)
    if name == "lch2hex":
        L, C, H = _num(inp.get("L"), "L"), _num(inp.get("C"), "C"), _num(inp.get("H"), "H")
        if not 0 <= L <= 100: raise ValueError("LCH L은 0~100입니다")
        if not 0 <= C <= 230: raise ValueError("LCH C는 0~230입니다")
        return co.lch2hex(L, C, H % 360)
    if name == "scale":
        r = co.scale(_hex(inp.get("hex")), str(inp.get("name") or "brand")[:32])
        return {k: r[k] for k in ("name", "base", "base_oklch", "brand_step", "steps", "css")}
    if name == "step":
        try:
            s = int(inp.get("step"))
        except (TypeError, ValueError):
            raise ValueError("step은 50~900 정수입니다")
        r = co.scale(_hex(inp.get("hex")))
        if str(s) not in {str(k) for k in r["steps"]}:
            raise ValueError("step은 50,100,…,900 중 하나입니다")
        v = r["steps"][s]
        return {"step": s, "hex": v["hex"], "oklch": v["oklch"], "gamut_mapped": v["gamut_mapped"],
                "brand": v["brand"], "brand_step": r["brand_step"]}
    raise ValueError(f"알 수 없는 도구: {name}")


def selfcheck():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = co.selfcheck()
    return {"ok": bool(ok), "items": [l for l in buf.getvalue().splitlines() if l.startswith(("PASS", "FAIL"))]}
