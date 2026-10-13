"""scripts/import_keyword_colors.py — 코퍼스 팀 키워드-색 표(MaC_color_keywords_v1.json)를 KB·사물 색 표로 합친다.

  python scripts/import_keyword_colors.py path/to/MaC_color_keywords_v1.json

규칙 (결정론, 다시 돌려도 같은 결과)
  ① KB 18 색 항목(감정·시간·장소): 표의 키워드를 '그 항목의 색과 같은 HEX' 묶음으로 찾아 붙인다.
     - 키워드는 합친다 (기존 키워드는 지우지 않는다 → 이미 잘 걸리던 문장이 놓치지 않게)
     - 색(lch)은 표 값으로 바꾸고 status=confirmed, source=corpus_v1
     - accent_lch(강조색 기준)는 표에 없으므로 바탕색이 움직인 만큼(ΔL·ΔC·Δh) 같이 옮긴다
       (그대로 두면 바탕이 어두워진 감정색에서 대비를 벌리느라 강조색 채도가 치솟는다: #E47570 → #FF5F62)
     - 같은 HEX 로 묶인 light·sensory 키워드(햇살·노을·산들바람·빗소리 …)도 그 항목에 붙는다
  ② quality 3 항목은 표에 없으므로 그대로 둔다
  ③ 나머지(memory_color + KB 색과 다른 light 키워드: 달·별·촛불·불꽃놀이 …) → data/object_colors.json
     사물 색은 등급이 아니라 표의 HEX 를 그대로 쓴다 (core/objects.py 가 사전보다 먼저 본다)
  ④ KB version 을 kb-0.2 로 올린다 → 문장 고정 키가 새로 잡힌다 (예전 표본은 보관함에 그대로)
"""
from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.color import hex2lab, lch2lab, delta_e_2000  # noqa: E402


def merge_keywords(base: list[str], extra: list[str]) -> list[str]:
    """기존 키워드 + 표 키워드. 단, 이미 있는 키워드를 '포함하는' 활용형(보고 싶 → 보고 싶다)은 넣지 않는다.
    키워드 매칭은 부분 문자열이라 짧은 쪽이 이미 다 잡는다 — 긴 활용형은 매칭에 보탬이 없고
    n-gram 검색 점수만 부풀려(고싶·싶 …) '기대고 싶을 만큼 듬직한' 같은 문장을 그리움으로 오연결시킨다."""
    out = list(dict.fromkeys(base))
    for k in extra:
        if k in out or any(b in k for b in out):
            continue
        out.append(k)
    return out

KB_PATH = ROOT / "data" / "color_kb.json"
OBJ_PATH = ROOT / "data" / "object_colors.json"
KB_VERSION = "kb-0.2.1"   # 0.2.1: 겹치는 활용형 키워드 제외(오연결 2건 수정) → 문장 고정 키 새로
MATCH_DE = 12.0      # 표 HEX 묶음이 KB 항목의 '그 색'이라고 볼 거리 (기존 KB 와 표의 최대 차이 ≈ 11, 바다만 30 → 키워드로 묶음)


def main(src: str):
    rows = json.loads(Path(src).read_text(encoding="utf-8-sig"))
    # v3: quality(기억 질감) 행은 색이 아니라 보정 규칙이라 hex 가 없다 → 색 합치기에서 뺀다 (KB quality 항목은 그대로)
    rows = [r for r in rows if r.get("hex") and r.get("category") != "quality"]
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    by_hex = defaultdict(list)
    for r in rows:
        by_hex[r["hex"].upper()].append(r)

    used = set()
    for e in kb["items"]:
        if "lch" not in e:                                   # quality 축
            continue
        # 이 항목의 기존 키워드가 표에서 가장 많이 가리키는 HEX = 이 항목의 새 색
        votes = Counter(r["hex"].upper() for r in rows if r["keyword"] in e["keywords"]
                        and r["category"] in ("emotion", "time", "space", "light", "sensory"))
        if not votes:
            continue
        hx = votes.most_common(1)[0][0]
        group = [r for r in by_hex[hx] if r["category"] != "memory_color" or r["keyword"] in e["keywords"]]
        r0 = group[0]
        old = tuple(e["lch"])
        e["lch"] = [r0["lch_l"], r0["lch_c"], r0["lch_h"]]
        if "accent_lch" in e:                                # 강조색 기준도 바탕색이 움직인 만큼 같이 옮긴다
            dl, dc = e["lch"][0] - old[0], e["lch"][1] - old[1]
            dh = (e["lch"][2] - old[2] + 180) % 360 - 180
            a = e["accent_lch"]
            e["accent_lch"] = [round(min(95, max(5, a[0] + dl)), 2), round(max(0, a[1] + dc), 2), round((a[2] + dh) % 360, 2)]
        e["hex"] = hx
        e["name_ko"] = r0["color_name"]
        e["keywords"] = merge_keywords(e["keywords"], [r["keyword"] for r in group])
        e["source"], e["status"] = "corpus_v1", "confirmed"
        e["changed_de00"] = round(delta_e_2000(lch2lab(old), hex2lab(hx)), 1)
        used.update(r["keyword"] for r in group)

    objects = {}
    for r in rows:
        if r["keyword"] in used:
            continue
        objects[r["keyword"]] = {"hex": r["hex"].upper(), "name": r["color_name"], "category": r["category"],
                                 "lch": [r["lch_l"], r["lch_c"], r["lch_h"]]}

    kb["version"] = KB_VERSION
    kb["note"] = ("kb-0.2.1: 코퍼스 팀 MaC_color_keywords_v1(2026-10-12) 반영. 18 색 항목의 lch 는 표의 확정값(status=confirmed), "
                  "키워드는 기존 + 표 합집합. quality 3 항목은 kb-0.1 그대로. 사물 색은 data/object_colors.json.")
    KB_PATH.write_text(json.dumps(kb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OBJ_PATH.write_text(json.dumps({"version": "obj-0.1", "source": Path(src).name, "objects": objects},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"KB {KB_VERSION}: 키워드 {sum(len(e['keywords']) for e in kb['items'])}개 · 사물 색 {len(objects)}개")
    for e in kb["items"]:
        if "changed_de00" in e:
            print(f"  {e['id']:20s} {e['hex']}  ΔE00 {e['changed_de00']:5.1f}  키워드 {len(e['keywords'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "MaC_color_keywords_v1.json")
