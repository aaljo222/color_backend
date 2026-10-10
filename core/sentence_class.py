"""core/sentence_class.py — '같은 문장급' 판정 (eng-2.3): 조사·어미·시제·어순·띄어쓰기만 다른 문장은 같은 문장으로 본다.

팀장 기준 (2026-10-10): "같은 문장이나 같은 문장급이면 해시·헥스·색상·색상명이 흔들리지 않으면 좋겠다."
eng-2.1 의 문장 키는 문장부호·공백만 지웠다. 그래서 아래 둘이 다른 키였다.
  "초여름에 엄마와 함께 수박을 먹은 기억"
  "초여름 엄마랑 같이 수박 먹었던 기억"
여기서 '문장급' = 형태소 분석(Kiwi)으로 뽑은 내용 형태소의 모음(multiset)이 같다.
  남긴다 : 명사(NNG·NNP·NNB) · 동사·형용사 어간(VV·VA) · 어근(XR) · 부사(MAG) · 숫자(SN) · 외국어(SL) · 부정(안·못·않·못하·말)
  버린다 : 조사(J*) · 어미(E*: 시제 '었'·관형 '던/은' 포함) · 문장부호 · 띄어쓰기 · 어순
  같은 뜻 부사 몇 개만 묶는다 : 같이=함께 (작은 표, 늘리려면 팀이 정한다)
지키는 선
  · 낱말(명사·용언)이 하나라도 다르면 다른 문장이다: "엄마와"↔"아빠와", "먹은"↔"먹지 않은", "초여름"↔"초여름과 가을"
  · 뜻이 비슷한 다른 낱말(엄마↔어머니)은 묶지 않는다 — 그건 '비슷한 문장 추천'(값은 안 바꿈)의 일이다
  · 형태소 분석기 버전이 키에 들어간다. 분석기가 바뀌면 문장급 키가 바뀌고, 정확히 같은 문장 키는 그대로라 기존 고정값은 유지된다
Kiwi(kiwipiepy) 가 없으면 None → 문장급 고정 없이 eng-2.1 처럼 정확한 문장만 고정한다.
"""
from __future__ import annotations
import logging, os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("uvicorn")
ENABLED = os.getenv("SENTENCE_CLASS", "1") == "1"
KEEP_TAGS = {"NNG", "NNP", "NNB", "VV", "VA", "XR", "MAG", "SN", "SL", "NR", "MM"}
NEGATION = {"안", "못", "않", "못하", "말"}
SYNONYM = {"같이": "함께"}


@lru_cache(maxsize=1)
def _kiwi():
    try:
        from kiwipiepy import Kiwi
        import kiwipiepy
        # 오타·다어절 사전을 끈다: 메모리 절약(~520→~330MB 실측) + 오타 교정이 끼어들지 않게 (결정론). 설정도 키에 넣는다
        return Kiwi(load_typo_dict=False, load_multi_dict=False), f"kiwi-{kiwipiepy.__version__}-notypo-nomulti"
    except Exception as ex:                               # 설치 안 됨 → 문장급 없이 (정확한 문장 고정은 그대로)
        logger.warning(f"[sentence_class] 형태소 분석기 없음 → 문장급 고정 끔: {type(ex).__name__}")
        return None, None


def analyzer() -> Optional[str]:
    return _kiwi()[1] if ENABLED else None


def content_tokens(text: str) -> Optional[list[str]]:
    """문장 → 정렬된 내용 형태소 목록 (태그 포함). 분석기가 없으면 None."""
    if not ENABLED:
        return None
    kiwi, _ = _kiwi()
    if kiwi is None:
        return None
    out = []
    for t in kiwi.tokenize(text):
        tag = t.tag.split("-")[0]                          # 'VV-R'(규칙 활용 표시) → 'VV'
        form = t.form
        if form in NEGATION and (tag in ("MAG", "VX", "VV")):
            out.append(f"NEG:{'못' if form.startswith('못') else '안'}")
        elif tag in KEEP_TAGS:
            out.append(f"{tag[:2]}:{SYNONYM.get(form, form)}")
    return sorted(out)
