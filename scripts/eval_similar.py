# -*- coding: utf-8 -*-
"""scripts/eval_similar.py — '비슷한 문장' 기준선(SIMILAR_MIN) 정하기. 키를 넣고 한 번 돌려 본다.
  python scripts/eval_similar.py
같아야 할 쌍(✓)의 최저 점수와 달라야 할 쌍(✗)의 최고 점수 사이에 기준선을 둔다.
ngram 은 항상, 임베딩은 VOYAGE_API_KEY(또는 GEMINI_API_KEY)가 있을 때 함께 잰다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from oracle import similar

PAIRS = [  # (a, b, 비슷해야 하나)
    ("덕수궁 돌담길", "덕수궁 돌담길 가을", True), ("덕수궁 돌담길", "돌담길 산책", True),
    ("한여름 바닷가 노을", "여름 바닷가의 노을", True), ("비 오는 창밖", "창밖에 비가 내린다", True),
    ("가을 단풍 숲", "단풍 든 가을 산", True), ("벚꽃 아주 연하게", "벚꽃 연하게", True),
    ("새벽 안개 낀 호수", "물안개 피는 이른 아침 호숫가", True),
    ("커피 한 잔", "녹차 한 잔", False), ("가을 단풍 숲", "봄 벚꽃 숲", False),
    ("한여름 바닷가 노을", "겨울 바다", False), ("덕수궁 돌담길", "네온사인 번화가", False),
    ("비 오는 창밖", "사막의 한낮", False),
]
cols = [("ngram", similar.ngram_sim)]
if similar.provider():
    import math
    vs = {}
    texts = sorted({t for a, b, _ in PAIRS for t in (a, b)})
    for t, v in zip(texts, similar.embed_many(texts, "document")):
        vs[t] = v
    cols.append((similar.model_name(), lambda a, b: similar._cos(vs[a], vs[b])))
for name, f in cols:
    yes = [f(a, b) for a, b, y in PAIRS if y]; no = [f(a, b) for a, b, y in PAIRS if not y]
    print(f"\n[{name}]")
    for a, b, y in PAIRS:
        print(f"  {'✓' if y else '✗'} {f(a, b):.3f}  {a} | {b}")
    print(f"  ✓ 최저 {min(yes):.3f} · ✗ 최고 {max(no):.3f} → " +
          (f"기준선 후보 {(min(yes) + max(no)) / 2:.2f}" if min(yes) > max(no) else "겹침: 완전히 가르는 기준선 없음"))
