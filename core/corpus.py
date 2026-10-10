"""core/corpus.py — MaC 색 코퍼스 (eng-2.2): 근거가 붙은 문단 묶음.

KB(data/color_kb.json)는 축마다 '기준색 하나'를 정하는 21항목 표다. 표만으로는 두 가지가 모자랐다.
  ① 검색 재현율 — 항목마다 키워드 몇 개 + 설명 한 줄뿐이라 "엄마 밥 냄새 나던 따뜻한 옛날" 같은 다른 말투를 못 찾았다
     (백서 v1.1 12장: ngram 정답률 22%)
  ② 근거 — 수치·규칙이 어디서 왔는지 응답에 붙일 자료가 없었다
코퍼스는 이 둘을 채운다. 색 숫자는 여전히 계산기가 정한다. 코퍼스는 '어느 KB 항목인가'와 '왜 그런가'만 말한다.

파일 (data/corpus/*.jsonl, 한 줄 = 한 문단)
  scenes.jsonl   장면 문단 → KB 항목(kb_id)에 연결. 같은 항목을 여러 말투로 서술 + 색 묘사(color_note, 숫자 없음)
  objects.jsonl  기억 속 사물 → 등급(색상 계열·밝기·채도). 어휘사전(lexicon)에 없는 사물을 받는다
  research.jsonl 색채 심리 연구 근거(인용·URL). 엔진 규칙(applies_to)마다 어떤 연구가 뒷받침하는지

상태(status)
  confirmed  출처를 확인한 문단 (연구 근거)
  draft      코퍼스 초안 (source=mac_corpus_draft). 팀이 검토해 confirmed 로 바꾼다 — KB status=demo 와 같은 규칙
버전
  corpus_version = "corpus-0.1+<파일 내용 해시 8자>". 문단 하나만 바뀌어도 버전이 바뀐다 (어느 코퍼스로 계산했는지 추적)
"""
from __future__ import annotations
import hashlib, json, os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from oracle import color_abstraction as ca

CORPUS_DIR = Path(os.getenv("CORPUS_DIR", Path(__file__).resolve().parent.parent / "data" / "corpus"))
CORPUS_BASE_VERSION = "corpus-0.1"
FILES = ("scenes.jsonl", "objects.jsonl", "research.jsonl")
STATUSES = ("draft", "confirmed")
EVIDENCE = ("strong", "moderate", "weak", "null")


def norm_name(s: str) -> str:
    """사물 이름 비교 키 — core/objects.py 의 사전 키와 같은 규칙 (정규화 + 공백 제거, 12자)."""
    return ca.normalize(str(s or "")).replace(" ", "")[:12]


@dataclass
class Corpus:
    version: str
    scenes: list[dict]
    objects: list[dict]
    research: list[dict]
    by_id: dict = field(default_factory=dict)
    object_by_name: dict = field(default_factory=dict)       # 정규화 이름·별칭 → 사물 문단

    def scenes_of(self, axis: str) -> list[dict]:
        return [s for s in self.scenes if s["axis"] == axis]

    def object_names(self) -> list[str]:
        """문장 속에서 찾을 이름(별칭 포함). 긴 이름 먼저 — '군고구마'가 '고구마'보다 먼저 잡히게."""
        names = {n for o in self.objects for n in [o["name"], *o.get("aliases", [])] if n}
        return sorted(names, key=lambda n: (-len(n), n))


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as ex:
            raise ValueError(f"{path.name}:{i} JSON 오류: {ex}") from ex
    return rows


def validate(scenes: list[dict], objects: list[dict], research: list[dict], kb) -> list[str]:
    """틀린 문단 목록(사람이 읽는 문장). 비어 있어야 로드된다 — 틀린 코퍼스로 조용히 계산하지 않는다."""
    errs, seen = [], set()
    for r in [*scenes, *objects, *research]:
        rid = r.get("id")
        if not rid:
            errs.append(f"id 없음: {str(r)[:60]}")
        elif rid in seen:
            errs.append(f"id 중복: {rid}")
        seen.add(rid)
        if r.get("status") not in STATUSES:
            errs.append(f"{rid}: status 는 {STATUSES} 중 하나")
        if not (r.get("text") or "").strip():
            errs.append(f"{rid}: text 없음")
    for s in scenes:
        e = kb.by_id.get(s.get("kb_id"))
        if e is None:
            errs.append(f"{s.get('id')}: KB 에 없는 kb_id {s.get('kb_id')}")
        elif e["axis"] != s.get("axis"):
            errs.append(f"{s.get('id')}: 축 불일치 ({s.get('axis')} ≠ KB {e['axis']})")
        if not s.get("source"):
            errs.append(f"{s.get('id')}: source 없음")
        if any(ch.isdigit() for ch in s.get("color_note", "")) or "#" in s.get("color_note", ""):
            errs.append(f"{s.get('id')}: color_note 에 숫자·HEX 금지 (색 숫자는 계산기만 낸다)")
    names = {}
    for o in objects:
        if ca.validate_descriptor(o) is None:
            errs.append(f"{o.get('id')}: 등급 범위 밖 (hue={o.get('hue')}, lightness={o.get('lightness')}, chroma={o.get('chroma')})")
        for n in [o.get("name"), *o.get("aliases", [])]:
            k = norm_name(n)
            if not k:
                errs.append(f"{o.get('id')}: 빈 이름")
            elif k in names and names[k] != o.get("id"):
                errs.append(f"{o.get('id')}: 이름 '{n}' 이 {names[k]} 와 겹침")
            names[k] = o.get("id")
    for r in research:
        if not r.get("citation") or not str(r.get("url", "")).startswith("http"):
            errs.append(f"{r.get('id')}: 연구 문단은 citation 과 url 이 필요")
        if r.get("evidence") not in EVIDENCE:
            errs.append(f"{r.get('id')}: evidence 는 {EVIDENCE} 중 하나")
        if r.get("status") != "confirmed":
            errs.append(f"{r.get('id')}: 연구 문단은 출처 확인 후 confirmed 로만 넣는다")
        if not r.get("applies_to"):
            errs.append(f"{r.get('id')}: applies_to 없음")
    return errs


def load(kb, directory: Path | None = None) -> Corpus:
    d = Path(directory or CORPUS_DIR)
    raw = {f: (d / f).read_bytes() if (d / f).exists() else b"" for f in FILES}
    scenes = _read_jsonl(d / FILES[0]) if raw[FILES[0]] else []
    objects = _read_jsonl(d / FILES[1]) if raw[FILES[1]] else []
    research = _read_jsonl(d / FILES[2]) if raw[FILES[2]] else []
    errs = validate(scenes, objects, research, kb)
    if errs:
        raise ValueError("코퍼스 검증 실패:\n  " + "\n  ".join(errs[:20]))
    digest = hashlib.sha256(b"\0".join(raw[f] for f in FILES)).hexdigest()[:8]
    c = Corpus(version=f"{CORPUS_BASE_VERSION}+{digest}", scenes=scenes, objects=objects, research=research)
    c.by_id = {r["id"]: r for r in [*scenes, *objects, *research]}
    for o in objects:
        for n in [o["name"], *o.get("aliases", [])]:
            c.object_by_name[norm_name(n)] = o
    return c


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    from core.kb import KB
    return load(KB())
