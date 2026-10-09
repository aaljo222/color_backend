# -*- coding: utf-8 -*-
"""프롬프트 → 팔레트. LLM은 최소로, 나머지는 전부 파이썬.

처리 순서 (앞 단계에서 끝나면 뒤로 가지 않는다)
  0. 정규화      문장 → 키 (소문자·문장부호·공백 정리)
  1. 문장 캐시   같은 키가 저장돼 있으면 그대로 반환                      … LLM 0회
  2. 규칙        HEX · OKLCH 수치 · 브랜드 단계(teal 600, 한 단계 진하게, hover) … LLM 0회
  3. 어휘사전    문장이 사전 단어(돌담·하늘…)+수식어+조사로만 되어 있으면  … LLM 0회
  4. LLM 추상화  처음 보는 장면·분위기만. LLM은 단어별 '등급'만 낸다(숫자 없음).
                 이미 사전에 있는 단어는 LLM 등급을 버리고 사전 등급을 쓴다.  … LLM 1회
  5. 수식어      진하게·연하게·선명하게·탁하게 → 등급을 칸 단위로 이동 (파이썬)
  6. 오라클      등급 → OKLCH 표 → HEX·LCH (color_oracle, 결정론)
  7. 저장        문장 결과와 새 단어 등급을 메타데이터로 보관, 썸네일 생성

그래서
  - 같은 문장        → 1단계에서 같은 결과 (저장소가 있으면 서버가 바뀌어도 같음)
  - 같은 단어가 든 다른 문장 → 3·4단계에서 단어 등급이 같으므로 같은 색
  - LLM이 흔들려도   → 등급 칸(밝기 9칸·채도 6칸·색상 13계열)이 굵어서 결과가 잘 안 바뀌고,
                       한 번 정해진 단어는 사전이 고정한다
"""
import json, os, urllib.parse

from oracle import color_oracle as co
from oracle import color_abstraction as ca
from oracle.store import get_store

MODEL = os.environ.get("ORACLE_MODEL") or os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_PROMPT = 300


class LLMError(Exception):
    pass


# ── LLM: 색채 추상화 한 번만, 등급만 ─────────────────────────────────────────
ABSTRACT_TOOL = {
    "name": "abstract_colors",
    "description": "장면·분위기 문장을 대표하는 사물·재료 2~5개로 나누고, 각각의 색을 등급으로만 표현한다. 숫자 색값(HEX·OKLCH)은 쓰지 않는다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "not_color": {"type": "boolean", "description": "색과 전혀 관계없는 문장이면 true"},
            "colors": {
                "type": "array", "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "화면에 보일 역할 이름 (예: 돌담, 기와)"},
                        "concept": {"type": "string", "description": "사물·재료의 기본형 명사 1개, 2~6자 (예: 돌담, 은행잎). 수식어 없이"},
                        "hue": {"type": "string", "enum": list(ca.HUES)},
                        "lightness": {"type": "integer", "minimum": 1, "maximum": 9, "description": "1=아주 어두움 … 9=아주 밝음"},
                        "chroma": {"type": "integer", "minimum": 0, "maximum": 5, "description": "0=무채 … 5=아주 선명"},
                    },
                    "required": ["label", "concept", "hue", "lightness", "chroma"],
                },
            },
        },
        "required": ["colors"],
    },
}


def _system(lexicon):
    known = ", ".join(sorted(k for k in lexicon)[:300])
    return ("너는 색채 추상화만 한다. 문장이 가리키는 장면을 대표하는 사물·재료 2~5개를 고르고, "
            "각 사물의 '기본 색'을 등급(hue·lightness·chroma)으로만 적는다.\n"
            "- 숫자 색값을 쓰지 않는다. 등급 외의 값은 버려진다.\n"
            "- '진하게·연하게·선명하게·탁하게' 같은 수식어는 무시하고 기본 색만 적는다. 수식어는 서버가 처리한다.\n"
            "- concept는 아래 기존 단어 중 같은 뜻이 있으면 그 단어를 그대로 쓴다.\n"
            f"기존 단어: {known}\n"
            "- 색과 전혀 관계없는 문장이면 not_color=true, colors=[]")


def _call_claude(prompt, lexicon):
    """구조화 출력 1회 호출. 응답은 등급(enum·정수)뿐 — 숫자 색값을 쓸 자리가 없다.
    정수 범위(1~9, 0~5)는 API 스키마가 아니라 validate_descriptor 게이트가 걸러낸다."""
    try:
        from core.llm import structured
        out = structured(_system(lexicon), prompt, ABSTRACT_TOOL["input_schema"], max_tokens=700, model=MODEL)
    except Exception as e:
        raise LLMError(f"Claude API 호출 실패: {type(e).__name__}: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise LLMError("LLM이 추상화 결과를 내지 않았습니다")
    return out


# ── 오라클로 한 색 만들기 ───────────────────────────────────────────────────
def _entry(label, concept, descriptor, L, C, H, origin):
    r = co.oklch2hex(L, C, H)
    actual = co.hex2oklch(r["hex"])
    return {"label": label, "concept": concept, "descriptor": descriptor, "origin": origin,
            "requested": f"oklch({L:.2f} {C:.3f} {H:.1f})", "hex": r["hex"], "gamut_mapped": r["gamut_mapped"],
            "oklch": actual["css"], "lch": co.hex2lch(r["hex"])["css"], "L": actual["L"]}


def _from_hex(label, h):
    h = co.srgb_to_hex(co.hex_to_srgb(h))
    o = co.hex2oklch(h)
    return {"label": label, "concept": None, "descriptor": None, "origin": "rule", "requested": h,
            "hex": h, "gamut_mapped": False, "oklch": o["css"], "lch": co.hex2lch(h)["css"], "L": o["L"]}


def _rule_palette(r):
    if r["kind"] == "hex":
        return [_from_hex("입력 색", r["hex"])]
    if r["kind"] == "oklch":
        L, C, H = r["L"], r["C"], r["H"]
        if L > 1.5:            # 0~100으로 적은 밝기도 받는다
            L /= 100
        if not (0 <= L <= 1 and 0 <= C <= 0.5):
            raise ValueError("OKLCH 범위: 밝기 0~1, 채도 0~0.5")
        return [_entry("지정 색", None, None, L, C, H % 360, "rule")]
    # 브랜드 단계: 단계 번호를 칸으로 이동 (50,100,…,900)
    sc = co.scale(ca.BRANDS[r["brand"]], r["brand"])
    base = r["base"] if r["base"] in ca.STEPS else sc["brand_step"]
    raw_i = ca.STEPS.index(base) + round(r["delta"] / 100)
    i = min(len(ca.STEPS) - 1, max(0, raw_i))
    step = ca.STEPS[i]
    v = sc["steps"][step]
    e = _from_hex(f"{r['brand']} {step}", v["hex"])
    e.update({"requested": v["oklch"], "gamut_mapped": v["gamut_mapped"], "step": step, "base_step": base,
              "clamped": raw_i != i})
    return [e]


def _palette_from_descriptors(items, dl, dc, origin_of):
    out = []
    for label, concept, d in items:
        d2 = ca.shift(d, dl, dc)
        L, C, H = ca.descriptor_to_oklch(d2)
        out.append(_entry(label, concept, d2, L, C, H, origin_of(concept)))
    return out


def _thumb_uri(prompt, palette):
    return "data:image/svg+xml;utf8," + urllib.parse.quote(ca.thumbnail_svg(prompt, palette))


def answer(prompt, refresh=False, call=None):
    """call(prompt, lexicon) → LLM 추상화 결과. 테스트용 주입 지점."""
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt가 비어 있습니다")
    if len(prompt) > MAX_PROMPT:
        raise ValueError(f"prompt는 {MAX_PROMPT}자 이하로 써 주세요")
    key = ca.normalize(prompt)
    store = get_store()

    if not refresh:
        hit = store.get_prompt(key)
        if hit:
            return {**hit, "cached": True, "thumbnail": _thumb_uri(hit["prompt"], hit["palette"])}

    dl, dc, _ = ca.parse_modifiers(key)
    new_concepts, llm_used = {}, False
    rule = ca.parse_rules(key)
    if rule:
        palette, source = _rule_palette(rule), "rule"
    else:
        lexicon = store.get_lexicon()
        matched = ca.match_lexicon(key, lexicon)
        if matched:
            items = [(c, c, {k: d[k] for k in ("hue", "lightness", "chroma")}) for c, d in matched]
            palette, source = _palette_from_descriptors(items, dl, dc, lambda c: "lexicon"), "lexicon"
        else:
            if call is None:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    raise LLMError("처음 보는 장면이라 LLM이 필요한데 ANTHROPIC_API_KEY가 없습니다 (Vercel 환경변수)")
                call = _call_claude
            raw = call(prompt, lexicon)
            llm_used = True
            items, seen = [], set()
            for it in (raw.get("colors") or [])[:5]:
                concept = ca.normalize(str(it.get("concept") or "")).replace(" ", "")[:12]
                d = ca.validate_descriptor(it)
                if not concept or d is None or concept in seen:
                    continue                                   # 등급 밖 값·중복은 버린다 (검증 게이트)
                seen.add(concept)
                if concept in lexicon:                         # 사전 우선: 같은 단어 = 같은 색
                    d = {k: lexicon[concept][k] for k in ("hue", "lightness", "chroma")}
                else:
                    new_concepts[concept] = {**d, "source": "llm"}
                label = str(it.get("label") or concept)[:10]
                items.append((label, concept, d))
            if not items:
                return {"prompt": prompt, "key": key, "status": "no_color", "source": "llm", "palette": [],
                        "llm_used": True, "cached": False, "thumbnail": None,
                        "message": "색으로 바꿀 장면·사물을 찾지 못했습니다"}
            palette = _palette_from_descriptors(items, dl, dc,
                                                lambda c: "llm" if c in new_concepts else "lexicon")
            source = "llm"

    result = {
        "prompt": prompt, "key": key, "status": "ok", "source": source, "palette": palette,
        "modifiers": {"lightness": dl, "chroma": dc}, "new_concepts": sorted(new_concepts),
        "llm_used": llm_used, "model": MODEL if llm_used else None, "table_version": ca.TABLE_VERSION,
    }
    store.put_concepts(new_concepts)
    store.put_prompt(key, prompt, result, overwrite=refresh)
    try:
        from oracle import similar
        similar.remember(key, prompt)                 # 임베딩을 쓸 때만 벡터 저장 (실패해도 결과엔 영향 없음)
    except Exception:
        pass
    return {**result, "cached": False, "thumbnail": _thumb_uri(prompt, palette)}


def gallery(limit=24):
    rows = get_store().gallery(limit)
    for r in rows:
        r["thumbnail"] = _thumb_uri(r["prompt"], r["palette"])
        r.pop("palette", None)
    return rows
