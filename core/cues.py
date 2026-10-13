"""core/cues.py — 키워드 판정 보조 (cues-0.1, 2026-10-13): 낱말 경계 · 원형 맞춤 · 약한 낱말 · 막는 단서.

kb-0.2.1 의 키워드 판정은 '글자가 들어 있으면' 걸렸다(부분 문자열). 그래서 생긴 문제:
  ① 다른 낱말 속에서 걸림   '비' ⊂ '비행기' → 비 오는 창가 (공항 면세점 문장, 오연결)
  ② 원형 키워드가 안 걸림   '신나다' 는 '신나서'에, '포근하다' 는 '포근한'에 안 걸렸다
  ③ 문맥이 정서를 바꿈      '아빠', '혼자', '가족', '하늘' … 같은 낱말이 상황에 따라 3~4가지 정서 (팀장 요청)
  ④ KB 에 없는 정서         '설렘인지 불안인지' → '설렘'만 보고 기쁨 (오연결). 불안·공포·갈등을 받을 항목이 없다
  ⑤ 한 축에 두 항목         '아침 햇살' → '햇살'(오후)이 먼저 걸림 (오연결)
여기서 하는 일
  · 형태소 분석(Kiwi, 이미 문장급 고정에 쓰는 것과 같은 인스턴스)으로 낱말 경계와 원형을 본다
      - 키워드는 낱말이 시작하는 자리에서만 걸린다. 한 글자 키워드는 낱말이 끝나는 자리까지 맞아야 한다 (비 ≠ 비행기, 눈 ≠ 눈물).
        한 글자 키워드가 붙은 합성어 중 같은 뜻인 것(한밤중·밤하늘·꽃잎…)은 data/cues.json extra_keywords 에 따로 적는다
      - 끝이 '다'인 키워드는 원형으로 맞춘다 (신나다 = 신나서 = 신났던).
      - 띄어 쓴 키워드는 내용 형태소가 이어서 나와야 한다. 사이의 부사는 건너뛴다 (눈 오다 = 눈이 펑펑 오던).
        원형으로 안 맞으면 글자 그대로도 본다 ('보고 싶' 처럼 원형이 아닌 조각 키워드)
  · 약한 낱말(weak)은 혼자서 정하지 않는다 → 코퍼스·검색이 문장 전체로 정한다
  · 부정된 키워드는 걸리지 않는다 ('선명하지 않은', '안 그리웠다')
  · 막는 단서(block)가 감정 축에 나오면 기본 톤 (바로 다음 낱말이 풀리다·않다·없다면 막지 않는다)
  · 한 축에 항목이 여럿 걸리면 light·sensory 낱말(secondary)보다 시간·장소 낱말이 이긴다
Kiwi 가 없으면 예전처럼 부분 문자열로만 맞춘다 (원형·이어진 말은 못 잡음). 막는 단서·약한 낱말은 그대로 쓴다.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

CUES_PATH = Path(os.getenv("CUES_PATH", Path(__file__).resolve().parent.parent / "data" / "cues.json"))
CONTENT = ("NN", "VV", "VA", "VX", "XR", "MA", "MM", "SN", "SL", "NR", "NP", "IC")


@dataclass(frozen=True)
class Hit:
    kb_id: str
    keyword: str
    start: int
    strength: str          # strong | weak | secondary


@dataclass
class Analysis:
    text: str
    starts: set = field(default_factory=set)
    ends: set = field(default_factory=set)
    lemmas: list = field(default_factory=list)   # [(원형, 시작 위치, 겉모양)] 내용 형태소만, 순서대로
    core: list = field(default_factory=list)     # 위에서 부사·관형사·감탄사를 뺀 것 (띄어 쓴 키워드 맞춤용)
    toks: list = field(default_factory=list)     # [(겉모양, 품사, 시작, 길이)] 전부 — 사물 이름 맞춤용
    has_kiwi: bool = False


def _kiwi():
    from core.sentence_class import _kiwi as k
    return k()[0]


@lru_cache(maxsize=4096)
def analyze(text: str) -> Analysis:
    an = Analysis(text=text)
    try:
        kiwi = _kiwi()
    except Exception:
        kiwi = None
    if kiwi is None or not text:
        return an
    toks = kiwi.tokenize(text)
    an.has_kiwi = True
    for i, t in enumerate(toks):
        an.toks.append((t.form, t.tag.split("-")[0], t.start, t.len))
        an.starts.add(t.start)
        an.ends.add(t.start + t.len)
        tag = t.tag.split("-")[0]
        if not tag.startswith(CONTENT):
            continue
        lemma = t.lemma if tag.startswith(("VV", "VA", "VX")) else t.form
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if tag in ("XR", "NNG") and nxt is not None and nxt.tag.startswith(("XSA", "XSV")) and nxt.form == "하":
            lemma = t.form + "하다"                      # 포근+하 → 포근하다, 편안+하 → 편안하다
        an.lemmas.append((lemma, t.start, t.form))
        if not tag.startswith(("MA", "MM", "IC")):
            an.core.append((lemma, t.start, t.form))
    return an


def _surface_at(kw: str, an: Analysis) -> list[int]:
    out, i = [], an.text.find(kw)
    while i >= 0:
        if not an.has_kiwi:
            out.append(i)
        else:
            end = i + len(kw)
            if (i in an.starts or i == 0) and (len(kw) >= 2 or end in an.ends or end == len(an.text)):
                if len(kw) == 1 and not any(st == i and tg.startswith(("NNG", "NNP")) for _, tg, st, _ in an.toks):
                    pass                                  # 한 글자 키워드는 명사로 나올 때만 ('낮은' 의 낮 ≠ 낮)
                else:
                    out.append(i)
        i = an.text.find(kw, i + 1)
    return out


def find(kw: str, an: Analysis) -> list[int]:
    """키워드가 걸린 위치들. 원형('~다')·이어진 말('눈 오다')은 형태소로, 나머지는 낱말 경계로 맞춘다."""
    parts = kw.split()
    if an.has_kiwi and ((kw.endswith("다") and len(kw) >= 3) or len(parts) > 1):
        src = an.core if len(parts) > 1 else an.lemmas
        seq = [l for l, _, _ in src]
        hits = [src[j][1] for j in range(len(seq) - len(parts) + 1)
                if all(seq[j + m] == parts[m] for m in range(len(parts)))]
        if hits:
            return hits
    return _surface_at(kw, an)


def find_noun(name: str, an: Analysis) -> list[int]:
    """사물 이름이 '명사로' 나온 위치. 이별 ⊅ 별, 특별한 ⊅ 별, 달리던 ⊅ 달, 한 달(의존명사) ⊅ 달, 별 거(관형사) ⊅ 별,
    포도주 ⊅ 포도. 이어진 명사 여러 개로 된 이름(생일케이크 = 생일+케이크)도 맞춘다. 분석기가 없으면 글자 포함."""
    if not an.has_kiwi:
        out, i = [], an.text.find(name)
        while i >= 0:
            out.append(i)
            i = an.text.find(name, i + 1)
        return out
    out, nt = [], an.toks
    for j, (form, tag, start, ln) in enumerate(nt):
        if not tag.startswith(("NNG", "NNP")) or not name.startswith(form):
            continue
        acc, end, k = form, start + ln, j
        while acc != name and len(acc) < len(name) and k + 1 < len(nt):
            f2, t2, s2, l2 = nt[k + 1]
            if not t2.startswith(("NNG", "NNP")) or s2 != end:
                break
            acc, end, k = acc + f2, s2 + l2, k + 1
        if acc == name:
            nxt = nt[k + 1] if k + 1 < len(nt) else None
            if nxt and nxt[1].startswith(("XSV", "XSA")) and nxt[2] == end:
                continue                                  # 명사 + 하다 = 동사·형용사 (사과하다 ⊅ 사과)
            if nxt and nxt[1].startswith(("NNG", "NNP")) and nxt[2] == end and nxt[0] not in COMPOUND_OK:
                continue                                  # 합성어의 앞부분 (구름사다리 ⊅ 구름, 우산꽂이 ⊅ 우산)
            out.append(start)
    return out


# 사물 이름 뒤에 붙어도 그 사물 색이 그대로인 말 (딸기밭·포도송이·귤껍질)
COMPOUND_OK = {"밭", "송이", "빛", "색", "잼", "맛", "향", "껍질", "즙", "주스", "잎", "꽃", "알", "더미", "꽃잎"}


def sense_excluded(word: str, an: Analysis, rules: dict) -> bool:
    """뜻이 갈리는 낱말에서 다른 뜻의 단서가 문장에 있으면 True ('밤을 구워' → 먹는 밤, '달이 바뀌고' → 기간)."""
    cue = rules.get(word)
    if not cue or not an.has_kiwi:
        return False
    lem = {l for l, _, _ in an.lemmas} | {f for f, _, _, _ in an.toks}
    return bool(lem & set(cue))


class Cues:
    def __init__(self, kb, path: Path = CUES_PATH):
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
        self.version = raw.get("version", "cues-none")
        self.kb = kb
        strip = lambda d: {k: v for k, v in (d or {}).items() if not k.startswith("_")}
        self.weak = {a: set(v) for a, v in strip(raw.get("weak_keywords")).items()}
        self.secondary = {a: set(v) for a, v in strip(raw.get("secondary_keywords")).items()}
        extra = strip(raw.get("extra_keywords"))
        cue_kw = strip(raw.get("cue_keywords"))
        self.block = {a: list(v) for a, v in strip(raw.get("block_cues")).items()}
        rel = strip(raw.get("release_words"))
        self.release_after = set(rel.get("after", []))
        self.release_before = set(rel.get("before", []))
        self.context = set(strip(raw.get("context_words")).get("emotion", []))
        self.sense = strip(raw.get("sense_exclude"))
        neg = strip(raw.get("negation"))
        self.neg_after, self.neg_before = set(neg.get("after", [])), set(neg.get("before", []))
        self.keywords: dict[str, list[tuple[str, str]]] = {}      # kb_id → [(키워드, 세기)]
        for e in kb.items:
            a = e["axis"]
            kws = [*e.get("keywords", []), *extra.get(e["id"], []), *cue_kw.get(e["id"], [])]
            seen, rows = set(), []
            for k in kws:
                if k in seen:
                    continue
                seen.add(k)
                s = "weak" if k in self.weak.get(a, ()) else "secondary" if k in self.secondary.get(a, ()) else "strong"
                rows.append((k, s))
            self.keywords[e["id"]] = rows

    def weak_lemmas(self, axis: str) -> set:
        """약한 낱말의 원형 ('이른' → 이르다, '따뜻한' → 따뜻하다). 낱말 겹침 검사에서 뺀다."""
        if not hasattr(self, "_wl"):
            self._wl = {}
        if axis not in self._wl:
            out = set(self.weak.get(axis, ()))
            for w in self.weak.get(axis, ()):
                an = analyze(w)
                out |= {l for l, _, _ in an.lemmas}
            self._wl[axis] = out
        return self._wl[axis]

    def hits(self, axis: str, an: Analysis) -> list[Hit]:
        out = []
        for e in self.kb.by_axis[axis]:
            for k, s in self.keywords[e["id"]]:
                if sense_excluded(k, an, self.sense):    # '밤을 구워 먹던' 의 밤은 시간이 아님
                    continue
                for p in find(k, an):
                    if not self._negated(p, an):          # '선명하지 않은', '안 그리웠다' 는 걸리지 않음
                        out.append(Hit(e["id"], k, p, s))
        return sorted(out, key=lambda h: (h.start, -len(h.keyword)))

    def blocked(self, axis: str, an: Analysis) -> Optional[str]:
        """감정 축에서 KB 에 없는 정서 단서가 나오면 그 단서. 바로 다음 '풀리다·않다·없다'나 앞의 '안·못'이 있으면 무시."""
        for c in self.block.get(axis, []):
            for p in find(c, an):
                if not self._released(p, an):
                    return c
        return None

    def _negated(self, pos: int, an: Analysis) -> bool:
        if not an.has_kiwi or not (self.neg_after or self.neg_before):
            return False
        idx = next((i for i, (_, s, _) in enumerate(an.lemmas) if s >= pos), None)
        if idx is None:
            return False
        after = an.lemmas[idx + 1][0] if idx + 1 < len(an.lemmas) else ""
        before = an.lemmas[idx - 1][2] if idx > 0 else ""
        return after in self.neg_after or before in self.neg_before

    def _released(self, pos: int, an: Analysis) -> bool:
        if not an.has_kiwi:
            return False
        idx = next((i for i, (_, s, _) in enumerate(an.lemmas) if s >= pos), None)
        if idx is None:
            return False
        after = [l for l, _, _ in an.lemmas[idx + 1: idx + 2]]
        before = an.lemmas[idx - 1][2] if idx > 0 else ""
        nxt = [l for l, _, _ in an.lemmas[idx + 1: idx + 4]]
        if nxt[:1] == ["것"] and "없다" in nxt[1:3]:       # '무서울 것 하나 없던', '무서운 게 없던' = 두렵지 않음
            return True
        return bool(self.release_after & set(after)) or before in self.release_before


# 낱말 겹침 검사용 — 너무 흔한 말은 겹침으로 치지 않는다
STOP_LEMMAS = {"하다", "있다", "되다", "없다", "않다", "같다", "보다", "오다", "가다", "나다", "지다", "주다", "것", "수", "때",
               "날", "그", "이", "저", "나", "너", "우리", "그때", "그날", "더", "또", "다", "좀", "잘", "참", "정말", "진짜", "너무",
               "앞", "뒤", "옆", "위", "아래", "안", "밖", "속", "사이", "중", "시작하다"}


def content_lemmas(text: str, emotion: bool = False, context: frozenset = frozenset()) -> Optional[set]:
    """내용 형태소 원형 집합. 분석기가 없으면 None. emotion=True 면 문맥 따라 정서가 갈리는 낱말(context)도 뺀다."""
    an = analyze(text)
    if not an.has_kiwi:
        return None
    drop = STOP_LEMMAS | (context if emotion else frozenset())
    return {l for l, _, _ in an.lemmas if l not in drop}


@lru_cache(maxsize=1)
def get_cues_raw() -> dict:
    try:
        return json.loads(CUES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_cues():
    from core.kb import KB
    return Cues(KB())
