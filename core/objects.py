"""core/objects.py — 기억 속 '사물'의 색 (eng-1.1).

eng-1.0 은 감정·시간·장소 축에서만 색을 가져와, 수박·옥수수처럼 기억을 대표하는 사물이 색에 나오지 않았다.
eng-1.1 은 사물 색을 강조색에 쓴다. 단, LLM은 여전히 숫자 색값을 내지 않는다.

  LLM  → 사물마다 '등급'만 (색상 계열 13개 · 밝기 1~9 · 채도 0~5)   ← Color Oracle 과 같은 등급 체계
  사전 → 이미 아는 사물이면 LLM 등급을 버리고 사전 등급 (같은 낱말 = 같은 색)
  코퍼스 → 사전에 없으면 data/corpus/objects.jsonl 의 등급 (eng-2.2). 코퍼스 등급은 사전에 적지 않는다(초안이 고쳐질 수 있다)
  계산 → 등급 → OKLCH 표 → HEX → CIE LCh  (oracle.color_abstraction / oracle.color_oracle, 결정론)

사전은 Color Oracle 과 같은 color_lexicon 을 쓴다 (Supabase, 없으면 메모리 + lexicon_seed.json).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from core.color import hex2lab, lab2lch
from oracle import color_abstraction as ca
from oracle import color_oracle as co

logger = logging.getLogger("uvicorn")
MAX_OBJECTS = 3


@dataclass(frozen=True)
class ObjectColor:
    name: str                       # 문장 속 사물 이름 (예: 수박)
    descriptor: tuple               # (hue, lightness, chroma) 등급
    lch: tuple                      # CIE LCh (synth 와 같은 공간)
    how: str                        # lexicon | corpus | grade


def _key(name: str) -> str:
    return ca.normalize(str(name or "")).replace(" ", "")[:12]


def _lexicon():
    try:
        from oracle.store import get_store
        return get_store().get_lexicon()
    except Exception as ex:                                   # 저장소 장애여도 계산은 계속
        logger.warning(f"[objects] lexicon 불러오기 실패: {type(ex).__name__}")
        from oracle.store import SEED
        return dict(SEED)


def _remember(new: dict):
    if not new:
        return
    try:
        from oracle.store import get_store
        get_store().put_concepts(new)                          # 처음 정해진 등급을 유지 (setdefault)
    except Exception as ex:
        logger.warning(f"[objects] lexicon 저장 실패: {type(ex).__name__}")


def descriptor_to_lch(d: dict) -> tuple:
    """등급 → OKLCH 표 → HEX(색역 매핑) → CIE LCh. 같은 등급이면 항상 같은 값."""
    L, C, H = ca.descriptor_to_oklch(d)
    hx = co.oklch2hex(L, C, H)["hex"]
    l, c, h = lab2lch(hex2lab(hx))
    return (round(l, 2), round(c, 2), round(h, 2))


def _corpus_object(name: str):
    try:
        from core.rag import get_rag
        rag = get_rag()
        return rag.object_of(name) if rag is not None else None
    except Exception as ex:
        logger.warning(f"[objects] 코퍼스 조회 실패: {type(ex).__name__}")
        return None


def resolve_objects(objects: list, lexicon: Optional[dict] = None, learn: bool = True) -> list[ObjectColor]:
    """LLM 이 낸 사물 목록 → 색. 이름이 비었거나 등급이 범위 밖이고 사전에도 없으면 버린다(검증 게이트)."""
    lex = lexicon if lexicon is not None else _lexicon()
    out, seen, new = [], set(), {}
    for o in (objects or [])[:MAX_OBJECTS]:
        if isinstance(o, str):
            o = {"name": o}
        elif hasattr(o, "model_dump"):
            o = o.model_dump()
        name = str(o.get("name") or "").strip()[:12]
        k = _key(name)
        if not k or k in seen:
            continue
        cp = _corpus_object(name) if k not in lex else None
        if k in lex:                                           # 사전 우선
            d = {x: lex[k][x] for x in ("hue", "lightness", "chroma")}
            how = "lexicon"
        elif cp is not None:                                   # 다음은 코퍼스 (모델 등급보다 우선 → 같은 낱말 = 같은 색)
            d = {x: cp[x] for x in ("hue", "lightness", "chroma")}
            how = "corpus"
        else:
            d = ca.validate_descriptor(o)
            if d is None:
                continue
            how = "grade"
            new[k] = {**d, "source": "mac"}
        seen.add(k)
        out.append(ObjectColor(name=name, descriptor=(d["hue"], d["lightness"], d["chroma"]),
                               lch=descriptor_to_lch(d), how=how))
    if learn:
        _remember(new)
    return out
