"""scripts/eval_objects.py — 키 없는 사물 추출(core/llm._stub_extract) 채점 (2026-10-13).

  python scripts/eval_objects.py          # data/goldset_objects.jsonl
  python scripts/eval_objects.py -v       # 틀린 문장 보기
  CUES=0 python scripts/eval_objects.py   # 예전 방식(글자 포함)과 비교

사물 색은 그림 4색과 강조색에 직접 들어가는데 지금까지 따로 재지 않았다.
지표: 문장 정답(찾은 사물 목록이 정답과 같음) · 잘못 찾은 사물(이별 → 별 같은 것) · 놓친 사물.
정답은 사람 검토 전 (2026-10-13 작성). 모델 추출(키 있음)은 이 스크립트가 재지 않는다.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.kb import KB  # noqa: E402
from core.llm import _stub_extract  # noqa: E402

path = next((a for a in sys.argv[1:] if not a.startswith("-")), str(ROOT / "data" / "goldset_objects.jsonl"))
rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
kb = KB()
ok = fp = fn = 0
for g in rows:
    got = [o["name"] if isinstance(o, dict) else o.name for o in _stub_extract(g["text"], kb).objects]
    exp = g["expected"]
    extra = [x for x in got if x not in exp]
    miss = [x for x in exp if x not in got]
    fp += len(extra)
    fn += len(miss)
    ok += not extra and not miss
    if (extra or miss) and "-v" in sys.argv:
        print(f"  {g['text']}  → {got}  정답={exp}" + (f"  ({g['note']})" if g.get("note") else ""))
n = len(rows)
print(f"■ {Path(path).name}: 문장 정답 {ok}/{n} ({ok / n:.0%}) · 잘못 찾은 사물 {fp} · 놓친 사물 {fn}")
