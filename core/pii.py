"""core/pii.py — LLM 전송 전 마스킹 (서버 안에서만 처리. 마스킹을 외부 LLM에 맡기지 않는다).

1단계 정규식: 이메일·전화·주민등록번호·카드번호
2단계 이름 휴리스틱: '지수랑', '민지한테' 처럼 조사 앞 2~3음절 + 가족·일반명사 제외 목록
   ※ 휴리스틱은 놓치거나 과하게 가릴 수 있다. 정확도가 중요해지면 형태소 분석기(고유명사 NNP)로 교체.
색 추출에는 이름이 필요 없으므로 과하게 가려도 결과 품질 손실은 작다.
"""
from __future__ import annotations
import re

_PATTERNS = [
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("주민번호", re.compile(r"\b\d{6}\s*-\s*[1-4]\d{6}\b")),
    ("카드", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
    ("전화", re.compile(r"(?:\+82[\s-]?)?0\d{1,2}[\s-]?\d{3,4}[\s-]?\d{4}")),
]
# 사람에게 주로 붙는 조사만 사용 (와/과/가/는 처럼 사물에도 붙는 조사는 오탐이 많아 제외)
_PARTICLE = r"(?:이랑|랑|이한테|한테|에게|이네|씨)"
_NAME = re.compile(r"(?<![가-힣])([가-힣]{2,3})(?=" + _PARTICLE + r")")
_COMMON = set("""엄마 아빠 어머니 아버지 할머니 할아버지 외할머니 외할아버지 동생 언니 오빠 누나 형 형님 친구 친구들 가족
선생님 사촌 이모 고모 삼촌 남편 아내 아들 딸 강아지 고양이 우리 그녀 그는 사람 동네 바다 하늘 노을 바람 햇살 눈 비
사랑 첫사랑 바닷가 바다 해변 공원 놀이터 학교 교실 시골 시장 카페 극장 성당 교회 아이 아이들 연인 남친 여친 애인 짝꿍 선배 후배 동기 이웃 손님 아기 조카 부모 부모님 형제 자매 할매 할배""".split())


def mask(text: str, extra_names: list[str] | None = None, protect: set[str] | None = None) -> tuple[str, dict]:
    """protect: 가리면 안 되는 단어(예: Color KB 키워드 — 바닷가·골목 등 장면 단서)."""
    protect = protect or set()
    stats: dict[str, int] = {}
    out = text
    for tag, pat in _PATTERNS:
        out, n = pat.subn(f"[{tag}]", out)
        if n:
            stats[tag] = n
    for nm in extra_names or []:
        if nm:
            out, n = re.subn(re.escape(nm), "[이름]", out)
            stats["이름"] = stats.get("이름", 0) + n

    def _rep(m):
        w = m.group(1)
        if w in _COMMON or w.startswith("[") or any(k in w or w in k for k in protect if len(k) >= 2):
            return w
        stats["이름"] = stats.get("이름", 0) + 1
        return "[이름]"
    out = _NAME.sub(_rep, out)
    return out, stats
