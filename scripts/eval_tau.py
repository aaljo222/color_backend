"""scripts/eval_tau.py — 골드셋으로 검색 임계값 τ 정하기 (RAG 평가).

  python scripts/eval_tau.py                      # RETRIEVER 환경변수의 검색기로
  python scripts/eval_tau.py --retriever embedding

골드셋(data/goldset.jsonl): {"axis","phrase","expected"} — expected=null 은 '맞는 항목이 없어야 정답'.
지표: 정답률(맞는 항목/기본톤 판단이 맞음), 오연결(엉뚱한 항목에 붙임), 놓침(있는데 기본톤).
키워드 경로로 바로 풀리는 문장은 검색 평가에서 제외한다(검색기의 실력만 본다).
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.kb import KB, make_retriever

ap = argparse.ArgumentParser(); ap.add_argument("--retriever", default=None); a = ap.parse_args()
kb = KB(); ret = make_retriever(kb, a.retriever)
gold = [json.loads(l) for l in open(Path(__file__).resolve().parent.parent / "data" / "goldset.jsonl", encoding="utf-8") if l.strip()]
rows = []
for g in gold:
    if any(k in g["phrase"] for e in kb.by_axis[g["axis"]] for k in e["keywords"]):
        continue
    top = ret.search(g["phrase"], g["axis"])[0]
    rows.append((g, top))
print(f"retriever={ret.name}  검색 평가 문장 {len(rows)}개 (키워드로 풀리는 문장 제외)\n")
for g, (s, i) in rows:
    print(f"  [{g['axis']:7s}] {g['phrase']:<18s} top={i:<20s} {s:.3f}  정답={g['expected']}")
print("\n  τ     정답률  오연결  놓침")
for tau in [x / 100 for x in range(0, 100, 5)]:
    ok = wrong = miss = 0
    for g, (s, i) in rows:
        pred = i if s >= tau else None
        if pred == g["expected"]: ok += 1
        elif pred is None: miss += 1
        else: wrong += 1
    print(f"  {tau:.2f}  {ok/len(rows):6.0%}  {wrong:5d}  {miss:4d}")
print("\n→ 오연결(엉뚱한 색)이 놓침(기본 톤)보다 사용자에게 더 나쁘다면, 오연결 0 을 유지하는 가장 낮은 τ 를 고른다.")
