"""scripts/eval_full.py — 전체 해석 경로로 골드셋 채점 (키워드 → 코퍼스 → KB 검색 → 기본 톤, 모델 라벨 없음).

scripts/eval_rag.py 는 '키워드로 풀리는 문장을 빼고' 검색기만 본다. 이 스크립트는 서비스와 같은 순서로 전부 돌린다.
멘토 보고서(kb-0.2.1)의 61% · 64% 와 같은 방식이다.

  python scripts/eval_full.py                       # 골드셋 전부 (아래)
  python scripts/eval_full.py -v                    # 오연결 문장 보기
  python scripts/eval_full.py -m                    # 놓친 문장도 보기
  CUES=0 CORPUS_NEED_LEMMA=0 python scripts/eval_full.py   # 오늘 변경을 끄고(kb-0.2.1 방식) 비교
  python scripts/eval_full.py --no-env              # .env 를 읽지 않고 (키 없이 ngram 으로) 재기
  python scripts/eval_full.py --sweep               # 기준선 τ(KB 검색) × τc(코퍼스) 조합표. 임베딩은 캐시로 → API 추가 0번
                                                    # 임베딩 제공자를 바꾸면(EMBED_PROVIDER) 점수 분포가 달라 꼭 다시 잴 것

.env 를 읽는다 (서비스와 같은 설정: 키·RETRIEVER·RETRIEVAL_TAU·CORPUS_TAU). 명령줄에 준 값이 .env 보다 우선한다.
첫 줄에 실제로 쓰인 검색기와 기준선이 찍힌다 — 임베딩으로 재려 했는데 ngram 이 찍히면 키나 임베딩 파일 문제다.

골드셋 형식 {"axis","phrase","expected"} — expected 가 null 이면 기본 톤이 정답, 목록이면 그중 하나면 정답.
  data/goldset.jsonl          팀 골드셋 33
  data/goldset_rag.jsonl      확장 골드셋 89 (김우혁, 2026-10-12)
  data/goldset_context.jsonl  문맥 시험셋 (2026-10-13). 같은 낱말이 상황에 따라 정서가 갈리는 문장(비·아빠·혼자·가족·하늘·눈·
                              꽃·할머니·나무·눈물·웃음·떨리다·바다·밤). ChatGPT 가 만든 상황표에서 상황 → KB 항목 대응을 붙였다
                              (사람 검토 전). 절반이 '기본 톤이어야 하는' 문장이라 오연결을 보는 용도.
  data/goldset_context_extra.jsonl  이른·따뜻한·선명하다 96문장 (2026-10-13, ChatGPT 상황표). 시간·감정·기억 질감 축에서
                              뜻이 갈리는 낱말 ('이른 봄' ↛ 아침, '선명한 소리' ↛ 생생한). 상황 → 정답 대응은 사람 검토 전.
지표: 정답 · 오연결(엉뚱한 색, 가장 나쁨) · 놓침(있는데 기본 톤) · 없음 지킴(정답이 기본 톤인 문장을 지킨 수)
"""
import json, logging, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if "--no-env" not in sys.argv:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")                    # override=False: 명령줄 값이 이긴다
    except ImportError:
        pass
import os  # noqa: E402
os.environ.setdefault("EMBED_CACHE", str(ROOT / "data" / ".embed_cache.json"))   # 질의 임베딩 디스크 캐시 → 두 번째부터 API 0번

failures = []


class _Count(logging.Handler):
    def emit(self, rec):
        if "실패" in rec.getMessage() or "사용 불가" in rec.getMessage():
            failures.append(rec.getMessage())


logging.getLogger("uvicorn").addHandler(_Count())

from core.kb import KB, make_retriever, Resolver, tau_for  # noqa: E402
from core.corpus import load  # noqa: E402
from core.rag import CorpusRAG  # noqa: E402
from core import embed_cache  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("-")]
golds = args or [str(p) for p in (ROOT / "data" / f for f in ("goldset.jsonl", "goldset_rag.jsonl", "goldset_v2.jsonl", "goldset_context.jsonl", "goldset_context_extra.jsonl"))
                 if p.exists()]
kb = KB()
ret = make_retriever(kb)
rag = CorpusRAG(load(kb))
tau = tau_for(ret)
R = Resolver(kb, ret, tau, rag)
cues = R.cues.version if R.cues else "끔(부분 문자열)"
print(f"KB {kb.version} · 단서 {cues} · KB 검색 {ret.name} τ={tau} · 코퍼스 {rag.method} {rag.corpus.version} "
      f"({len(rag.scenes)} 장면) τc={rag.tau}", flush=True)

# 임베딩을 쓰면 모든 문장의 질의 임베딩을 묶음으로 먼저 받아 둔다 (문장마다 따로 부르면 하루 한도를 금방 쓴다)
gold_rows = {path: [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] for path in golds}
phrases = list(dict.fromkeys(g["phrase"] for rows in gold_rows.values() for g in rows))
def prewarm():
    if ret.name == "embedding":
        ret._embed(phrases, task="RETRIEVAL_QUERY")
    if rag.method == "embedding":
        from oracle import similar
        similar.embed_many(phrases, "query")


import time  # noqa: E402
prewarm_fail = []
wait = 15
for n in range(7):                                  # 분당 한도에 걸리면 기다렸다 이어서 (받은 묶음은 캐시에 남아 다시 안 보낸다)
    try:
        prewarm()
        break
    except Exception as ex:
        msg = f"{type(ex).__name__} {ex}"
        embed_cache.save()
        if "PerDay" in msg or n == 6 or not any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "rate", "quota")):
            prewarm_fail.append(f"질의 임베딩 미리 받기 실패: {msg[:200]}")
            break
        print(f"  분당 한도 — {wait}초 뒤 이어서 받기 ({n + 1}/6)", flush=True)
        time.sleep(wait)
        wait *= 2
embed_cache.save()
if prewarm_fail:                                    # 미리 받기가 실패하면 채점 중에 문장마다 다시 부르다 한도에 걸려 숫자가 흔들린다
    print(f"⚠ {prewarm_fail[0]}\n  질의 임베딩을 다 못 받았습니다. 이대로 재면 일부 문장이 ngram 으로 내려가 숫자가 흔들립니다. "
          "1~2분 뒤 다시 실행하세요 (받은 것은 캐시에 남아 있습니다).", flush=True)
    sys.exit(1)
if ret.name == "embedding" or rag.method == "embedding":
    print(f"임베딩 요청 {embed_cache.calls}번 (캐시 {os.environ['EMBED_CACHE']})", flush=True)
print(flush=True)
def score(Rx, rows):
    ok = wrong = 0
    for g in rows:
        r = Rx.resolve(g["axis"], g["phrase"])
        p = None if r.how == "fallback" else r.kb_id
        exp = g["expected"] if isinstance(g["expected"], list) else [g["expected"]]
        ok += p in exp
        wrong += p is not None and p not in exp
    return ok, wrong


if "--sweep" in sys.argv:
    grid = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85]
    names = [Path(p).stem for p in golds]
    print("τ(KB)  τc(코퍼스)  " + "  ".join(f"{n:>18s}" for n in names) + "   합계(정답/오연결)")
    best = []
    for t in grid:
        for tc in grid:
            rag.tau = tc
            Rx = Resolver(kb, ret, t, rag, cues=R.cues)
            cells = [score(Rx, gold_rows[p]) for p in golds]
            tot = (sum(c[0] for c in cells), sum(c[1] for c in cells))
            best.append((tot[1], -tot[0], t, tc))
            print(f"{t:5.2f}  {tc:9.2f}   " + "  ".join(f"{c[0]:4d}/{len(gold_rows[p]):<4d} 오{c[1]:2d}" for c, p in zip(cells, golds))
                  + f"   {tot[0]}/{tot[1]}", flush=True)
    best.sort()
    if failures:
        print(f"\n⚠ 조합표를 만드는 동안 검색 실패 {len(failures)}건 — 예: {failures[0][:160]}\n  이 표는 믿을 수 없습니다. 다시 실행하세요.")
    print("\n오연결이 가장 적은 조합 중 정답이 많은 순 (위 5개):")
    for w, nok, t, tc in best[:5]:
        print(f"  τ={t} τc={tc} → 정답 {-nok} · 오연결 {w}")
    embed_cache.save()
    sys.exit(0)

for path in golds:
    rows = gold_rows[path]
    ok = wrong = miss = nullok = nulln = 0
    for g in rows:
        r = R.resolve(g["axis"], g["phrase"])
        p = None if r.how == "fallback" else r.kb_id
        exp = g["expected"] if isinstance(g["expected"], list) else [g["expected"]]
        if exp == [None]:
            nulln += 1
            nullok += p is None
        if p in exp:
            ok += 1
        elif p is None and None not in exp:
            miss += 1
            if "-m" in sys.argv:
                print(f"  놓침    [{g['axis']}] {g['phrase']}  정답={g['expected']}")
        else:
            wrong += 1
            if "-v" in sys.argv or "-m" in sys.argv:
                print(f"  오연결  [{g['axis']}] {g['phrase']}  → {p} ({r.how} {r.ref})  정답={g['expected']}")
    n = len(rows)
    print(f"■ {Path(path).name}: 정답 {ok}/{n} ({ok / n:.0%}) · 오연결 {wrong} · 놓침 {miss} · 없음 지킴 {nullok}/{nulln}\n", flush=True)
embed_cache.save()
if failures:
    print(f"⚠ 검색 실패 {len(failures)}건 — 예: {failures[0]}\n  키·임베딩 파일을 확인하세요. 이 숫자는 믿을 수 없습니다.")
