"""scripts/eval_rag.py — 코퍼스 RAG 평가: KB 설명만 검색 vs 코퍼스(장면 문단) 검색 vs 둘을 이은 해석 경로.

  python scripts/eval_rag.py                              # 두 골드셋 모두, 기본 τ
  python scripts/eval_rag.py --gold data/goldset.jsonl     # 하나만
  python scripts/eval_rag.py --sweep                       # 코퍼스 τc 를 0.00~0.95 로 바꿔 가며

골드셋 {"axis","phrase","expected"} — expected=null 은 '맞는 항목이 없어야 정답'(기본 톤).
키워드로 바로 풀리는 문장은 뺀다(검색기 실력만 본다). 지표: 정답률 · 오연결(엉뚱한 항목) · 놓침(있는데 기본 톤).
  data/goldset.jsonl      팀 골드셋 (코퍼스와 따로 작성됨)
  data/goldset_rag.jsonl  eng-2.2 추가 골드셋 — 코퍼스를 쓴 사람이 작성했다. 낱말 겹침을 줄였지만 낙관 편향이 있다.
                          실제 사용자 문장으로 바꿔 가는 것이 다음 단계.
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.kb import KB, make_retriever, Resolver, DEFAULT_TAU
from core.corpus import load
from core.rag import CorpusRAG

ap = argparse.ArgumentParser()
ap.add_argument("--gold", action="append")
ap.add_argument("--sweep", action="store_true")
a = ap.parse_args()
golds = a.gold or [str(ROOT / "data" / "goldset.jsonl"), str(ROOT / "data" / "goldset_rag.jsonl")]

kb = KB()
ret = make_retriever(kb)
tau = DEFAULT_TAU.get(ret.name, 0.25)
rag = CorpusRAG(load(kb))


def score(rows, pred_fn):
    ok = wrong = miss = 0
    for g in rows:
        p = pred_fn(g)
        if p == g["expected"]:
            ok += 1
        elif p is None:
            miss += 1
        else:
            wrong += 1
    return ok, wrong, miss


def kb_only(g, t=tau):
    s, i = ret.search(g["phrase"], g["axis"])[0]
    return i if s >= t else None


def corpus_only(g, t=None):
    hits = rag.search(g["phrase"], axis=g["axis"], k=1)
    t = rag.tau if t is None else t
    return hits[0].passage["kb_id"] if hits and hits[0].score >= t else None


def chained(g, t=None):
    r = Resolver(kb, ret, tau, rag if t is None else CorpusRAG(rag.corpus, tau=t)).resolve(g["axis"], g["phrase"])
    return None if r.how == "fallback" else r.kb_id


print(f"KB {kb.version} · KB 검색 {ret.name} τ={tau} · 코퍼스 {rag.corpus.version} ({len(rag.scenes)} 장면) {rag.method} τc={rag.tau}\n")
for path in golds:
    gold = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [g for g in gold if not any(k in g["phrase"] for e in kb.by_axis[g["axis"]] for k in e["keywords"])]
    n = len(rows)
    print(f"■ {Path(path).name}: 평가 {n}문장 (전체 {len(gold)}, 키워드로 풀리는 {len(gold) - n}개 제외)")
    print("  방법                      정답률   오연결  놓침")
    for name, fn in (("KB 설명 검색만 (eng-2.1)", kb_only), ("코퍼스 장면 검색만", corpus_only), ("코퍼스 → KB (eng-2.2 경로)", chained)):
        ok, wrong, miss = score(rows, fn)
        print(f"  {name:<24s} {ok}/{n} {ok / n:5.0%}  {wrong:5d}  {miss:4d}")
    if a.sweep:
        print("\n  τc    정답률  오연결  놓침   (코퍼스 → KB 경로)")
        for t in [x / 100 for x in range(0, 100, 5)]:
            ok, wrong, miss = score(rows, lambda g: chained(g, t))
            print(f"  {t:.2f}  {ok / n:6.0%}  {wrong:5d}  {miss:4d}")
    print("\n  틀린 문장 (eng-2.2 경로)")
    for g in rows:
        p = chained(g)
        if p != g["expected"]:
            h = rag.search(g["phrase"], axis=g["axis"], k=1)
            top = f"{h[0].passage['kb_id']} {h[0].score:.3f} ({h[0].passage['id']})" if h else "-"
            print(f"    [{g['axis']:7s}] {g['phrase']:<22s} 예측={p}  정답={g['expected']}  코퍼스1위={top}")
    print()
print("→ 오연결(엉뚱한 색)이 놓침(기본 톤)보다 나쁘다. 오연결을 늘리지 않는 가장 낮은 τc 를 고른다.")
