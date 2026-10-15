"""scripts/eval_ten.py — 같은 10문장을 eng-2.5(측정) 와 eng-2.6(후보 스냅) 으로 실제 화가·Claude 로 그려 비교 (2026-10-13 요구사항).

  python scripts/eval_ten.py                 # .env 의 키로 10문장 × 2엔진 (Claude 추출 20번 · 그림 20~40장)
  python scripts/eval_ten.py --only 2.6      # eng-2.6 만
  python scripts/eval_ten.py -n 3            # 앞 3문장만 (비용 확인용)

DB 를 건드리지 않는다: 문장 고정(SENTENCE_LOCK)을 끄고, 보관함·로그에 저장하지 않는다. 결과는 out/eval_ten/ 에만.
  out/eval_ten/report.html   문장마다 두 엔진의 그림·4색·지표를 나란히
  out/eval_ten/rows.json     지표 원자료

지표 (문장마다, 엔진마다)
  families    4색이 서로 다른 색 계열 몇 개인가 (core.rag.hue_family 기준, 4 가 최고)
  in_cands    4색이 그리기 전 후보 안에 있는 비율 (2.6 은 1.0 이어야 한다. 2.5 는 같은 문장으로 만든 후보와 ΔE00<3 이면 '안에 있음')
  coverage    그림 픽셀 중 4색과 ΔE00 ≤ 10 인 비율
  affect_ok   감정 KB 항목의 기준 쾌와 문장 정서 등급 쾌의 차이 ≤ 1 인가
  attempts    다시 그린 횟수 (그림 비용)
  fidelity    (2.6) 칩 후보 색과 그림 속 실제 색의 ΔE00
"""
from __future__ import annotations
import argparse, base64, io, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "eval_ten"
SENTENCES = [
    "유년의 여름날, 베어 물면 붉은 과즙보다 먼저 혀끝을 적시던 얼룩덜룩한 모스 그린 수박 껍질",
    "비 오는 밤 창가에서 떠나간 사람을 생각하던 쓸쓸한 기억",
    "초여름 오후, 아빠 손을 잡고 놀이공원 회전목마 앞에서 설레던 기억",
    "첫눈 오던 겨울 아침 골목에서 친구와 눈사람을 만들던 날",
    "할머니 댁 툇마루에서 노란 참외를 깎아 먹던 한낮",
    "노을 지는 바닷가를 엄마와 말없이 걷던 저녁",
    "새벽까지 독서실에서 혼자 조용히 공부하던 겨울",
    "벚꽃 흩날리던 꽃길을 처음 손잡고 걷던 봄날",
    "외갓집 마당에서 사촌들과 수박씨 뱉기 하던 한여름 오후",
    "교실 창가 자리에서 분필 냄새 맡으며 졸던 오후",
]


def run_engine(tag: str, n: int) -> list[dict]:
    """한 엔진으로 n 문장. 엔진 설정은 import 할 때 읽히므로 하위 프로세스로 돌린다."""
    env = {**os.environ, "SENTENCE_LOCK": "0", "PALETTE_SNAP": "1" if tag == "2.6" else "0", "_EVAL_N": str(n),
           "AFFECT_RECONCILE": "1" if tag == "2.6" else "0"}     # 2.5 = 감정-정서 대조 전 그대로
    r = subprocess.run([sys.executable, __file__, "--child", tag], env=env, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"eng-{tag} 실행 실패")
    return json.loads((OUT / f"rows_{tag}.json").read_text(encoding="utf-8"))


def child(tag: str):
    sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass
    os.environ["SENTENCE_LOCK"] = "0"
    from core.pipeline import analyze
    from core.kb import KB
    from core.rag import hue_family
    from core.color import hex2lab, delta_e_2000
    kb = KB()
    rows = []
    for i, text in enumerate(SENTENCES[: int(os.environ.get("_EVAL_N", "10"))]):
        a = analyze(text, engine="image_first")
        img = a.pop("_image", None)
        png = OUT / f"{tag}_{i:02d}.png"
        if img is not None:
            img.save(png)
        emo = a["_log"]["features"]["resolved_axes"]["emotion"]
        base = kb.by_id[emo[0]].get("affect") or [3, 3]
        aff = a.get("affect") or {}
        pal = a["palette"]
        cands = [c["hex"] for c in a.get("candidates", [])]
        rows.append({
            "i": i, "text": text, "engine": a["engine_version"], "summary": a.get("memory_summary", ""),
            "emotion": emo[0], "emotion_how": emo[1], "valence": aff.get("valence"), "arousal": aff.get("arousal"),
            "affect_ok": aff.get("valence") is not None and abs(aff["valence"] - base[0]) <= 1,
            "chips": [[p["role"], p["hex"], p.get("color_name", ""), round(p["area_ratio"], 3)] for p in pal],
            "families": len({hue_family(p["lch"]) for p in pal}), "family_names": [hue_family(p["lch"]) for p in pal],
            "coverage": a["verification"].get("coverage"), "status": a["verification"]["status"],
            "attempts": a["verification"].get("attempts"), "renderer": a["verification"].get("renderer"),
            "fidelity": [p["basis"].get("fidelity_de00") for p in pal] if tag == "2.6" else None,
            "cands": cands, "image": png.name if img is not None else None,
        })
        print(f"[{tag}] {i+1}: {rows[-1]['families']}계열 · 대표도 {rows[-1]['coverage']} · 감정 {emo[0]}({emo[1]})", flush=True)
    (OUT / f"rows_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def report(r25: list, r26: list):
    from statistics import mean, median
    sys.path.insert(0, str(ROOT))
    from core.color import hex2lab, delta_e_2000
    by = {r["i"]: r for r in r25}
    for r in r26:                                  # 2.5 의 측정 칩이 같은 문장의 2.6 후보 안에 있었나 (ΔE00 < 3)
        o = by.get(r["i"])
        if o is not None and r["cands"]:
            o["in_cands"] = mean(min(delta_e_2000(hex2lab(h), hex2lab(c)) for c in r["cands"]) < 3 for _, h, _, _ in o["chips"])
        r["in_cands"] = mean(h in r["cands"] for _, h, _, _ in r["chips"]) if r["cands"] else None
    def summ(rows):
        if not rows:
            return {}
        f = lambda k: [x[k] for x in rows if x.get(k) is not None]
        return {"문장": len(rows), "4색 계열 수(평균)": round(mean(f("families")), 2),
                "4색 ⊂ 후보": round(mean(f("in_cands")), 2) if f("in_cands") else "—",
                "대표도 중앙값": round(median(f("coverage")), 3), "감정-정서 일치": f"{sum(f('affect_ok'))}/{len(rows)}",
                "심사 통과": f"{sum(x['status'] == 'PASS' for x in rows)}/{len(rows)}",
                "그린 횟수(평균)": round(mean(f("attempts")), 2)}
    s25, s26 = summ(r25), summ(r26)
    keys = list((s26 or s25).keys())
    head = "".join(f"<tr><th>{k}</th><td>{s25.get(k, '—')}</td><td>{s26.get(k, '—')}</td></tr>" for k in keys)
    def chips(r):
        return "".join(f'<span class="c" style="background:{h}" title="{n} {h} {round(a*100)}%"></span>' for _, h, n, a in r["chips"])
    def cell(r):
        if r is None:
            return "<td>—</td>"
        img = f'<img src="{r["image"]}">' if r.get("image") else ""
        fid = f' · ΔE {r["fidelity"]}' if r.get("fidelity") else ""
        return (f'<td>{img}<div>{chips(r)}</div><small>{"·".join(r["family_names"])} · 대표도 {r["coverage"]} · '
                f'{r["status"]} {r["attempts"]}회<br>감정 {r["emotion"]}({r["emotion_how"]}) · 쾌 {r["valence"]} '
                f'{"✓" if r["affect_ok"] else "✗"}{fid}</small></td>')
    b26 = {r["i"]: r for r in r26}
    rows = "".join(f'<tr><th class="t">{i+1}. {SENTENCES[i]}</th>{cell(by.get(i))}{cell(b26.get(i))}</tr>'
                   for i in sorted(set(by) | set(b26)))
    html = f"""<!doctype html><meta charset="utf-8"><title>MaC 10문장 비교</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse}}
th,td{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}}th.t{{width:220px;font-weight:500}}
img{{width:220px;display:block}}.c{{display:inline-block;width:26px;height:18px;margin:4px 2px 2px 0;border:1px solid #0002}}
small{{color:#555}}</style><h1>MaC 10문장 비교 — eng-2.5(측정) vs eng-2.6(후보 스냅)</h1>
<table><tr><th></th><th>eng-2.5</th><th>eng-2.6</th></tr>{head}</table><h2>문장별</h2>
<table><tr><th></th><th>eng-2.5</th><th>eng-2.6</th></tr>{rows}</table>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    (OUT / "rows.json").write_text(json.dumps({"2.5": r25, "2.6": r26, "summary": {"2.5": s25, "2.6": s26}},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"eng-2.5": s25, "eng-2.6": s26}, ensure_ascii=False, indent=1))
    print(f"→ {OUT / 'report.html'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--child")
    ap.add_argument("--only", choices=["2.5", "2.6"])
    ap.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.child:
        child(a.child)
    else:
        r25 = [] if a.only == "2.6" else run_engine("2.5", a.n)
        r26 = [] if a.only == "2.5" else run_engine("2.6", a.n)
        report(r25, r26)
