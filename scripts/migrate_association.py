"""scripts/migrate_association.py — 기존 prompts/color_association.py(v1.0) → Color KB 골격 JSON.

  python scripts/migrate_association.py path/to/color_association.py > data/color_kb_from_v1.json
정성 표현(lightness 'medium-high' 등)은 note 로 옮기고 lch 는 null — 코퍼스 팀이 근거 자료로 수치를 채운다.
"""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location("ca", sys.argv[1]); ca = importlib.util.module_from_spec(spec); spec.loader.exec_module(ca)
items = []
for axis, table in (("emotion", ca.EMOTION_COLOR_RULES), ("time", ca.TIME_COLOR_RULES),
                    ("space", ca.SPACE_COLOR_RULES), ("quality", ca.MEMORY_QUALITY_RULES)):
    for rid, r in table.items():
        note = {k: v for k, v in r.items() if k != "keywords"}
        items.append({"id": rid, "axis": axis, "name": (r.get("association") or [rid])[0], "lch": None,
                      "accent_lch": None if axis == "emotion" else None,
                      "modifiers": {"c": 1.0, "l_pull": 0.0} if axis == "quality" else None,
                      "keywords": r.get("keywords", []), "description": "", "v1_note": note,
                      "source": "mac_v1", "status": "todo"})
print(json.dumps({"version": "kb-0.0-from-v1", "items": items}, ensure_ascii=False, indent=2))
