# -*- coding: utf-8 -*-
"""oracle/store.py — Color Oracle 메타데이터 저장소. 재활용할 수 있는 것은 전부 여기 남긴다.

  color_prompts : 문장(정규화 키) → 결과 전체 + 출처(rule/lexicon/llm) + 사용 횟수 → 같은 문장은 다시 계산하지 않는다
  color_lexicon : 사물·재료 낱말 → 등급(hue·lightness·chroma) → 다른 문장에 같은 낱말이 나와도 같은 색

백엔드: MaC 와 같은 Supabase 클라이언트(utils.supabase_client.supabase_admin, service_role).
        없으면 메모리(+ lexicon_seed.json). Supabase 장애 시에도 계산은 계속되도록 저장 실패는 넘긴다.
표 정의: sql/schema.sql 의 11) Color Oracle 절.
"""
import json, os, time, logging
from datetime import datetime, timezone

logger = logging.getLogger("uvicorn")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "lexicon_seed.json"), encoding="utf-8") as f:
    SEED = {k: {**v, "source": "seed"} for k, v in json.load(f)["concepts"].items()}
_now = lambda: datetime.now(timezone.utc).isoformat()


class MemoryStore:
    name = "memory"

    def __init__(self):
        self.prompts, self.lexicon = {}, dict(SEED)

    def get_prompt(self, key, count=True):
        row = self.prompts.get(key)
        if row and count:
            row["hits"] += 1; row["updated_at"] = time.time()
        return row["result"] if row else None

    def put_prompt(self, key, prompt, result, overwrite=False):
        if key in self.prompts and not overwrite:
            return
        self.prompts[key] = {"key": key, "prompt": prompt, "result": result, "source": result.get("source"),
                             "hits": 1, "updated_at": time.time()}

    def get_lexicon(self):
        return self.lexicon

    def put_concepts(self, items):
        for c, d in items.items():
            self.lexicon.setdefault(c, d)        # 처음 정해진 등급을 유지 (일관성)

    def gallery(self, limit=24):
        rows = sorted(self.prompts.values(), key=lambda r: r["updated_at"], reverse=True)[:limit]
        return [{"key": r["key"], "prompt": r["prompt"], "source": r["source"], "hits": r["hits"],
                 "palette": r["result"].get("palette", [])} for r in rows]


class SupabaseStore:
    name = "supabase"

    def __init__(self, sb):
        self.sb = sb
        self._lex, self._lex_t = None, 0

    def get_prompt(self, key, count=True):
        try:
            r = self.sb.table("color_prompts").select("result,hits").eq("key", key).limit(1).execute()
            if not r.data:
                return None
            if count:
                try:
                    self.sb.table("color_prompts").update({"hits": r.data[0]["hits"] + 1, "updated_at": _now()}).eq("key", key).execute()
                except Exception:
                    pass
            return r.data[0]["result"]
        except Exception as ex:
            logger.warning(f"[oracle.store] get_prompt 실패: {type(ex).__name__}")
            return None

    def put_prompt(self, key, prompt, result, overwrite=False):
        row = {"key": key, "prompt": prompt, "result": result, "source": result.get("source"), "updated_at": _now()}
        try:
            self.sb.table("color_prompts").upsert(row, on_conflict="key", ignore_duplicates=not overwrite).execute()
        except Exception as ex:
            logger.warning(f"[oracle.store] put_prompt 실패: {type(ex).__name__}")

    def get_lexicon(self):
        if self._lex is not None and time.time() - self._lex_t < 60:
            return self._lex
        lex = dict(SEED)
        try:
            r = self.sb.table("color_lexicon").select("concept,hue,lightness,chroma,source").limit(5000).execute()
            for x in r.data or []:
                lex[x["concept"]] = {"hue": x["hue"], "lightness": x["lightness"], "chroma": x["chroma"], "source": x["source"]}
        except Exception as ex:
            logger.warning(f"[oracle.store] get_lexicon 실패: {type(ex).__name__}")
        self._lex, self._lex_t = lex, time.time()
        return lex

    def put_concepts(self, items):
        if not items:
            return
        rows = [{"concept": c, "hue": d["hue"], "lightness": d["lightness"], "chroma": d["chroma"], "source": d.get("source", "llm")}
                for c, d in items.items()]
        try:
            self.sb.table("color_lexicon").upsert(rows, on_conflict="concept", ignore_duplicates=True).execute()
        except Exception as ex:
            logger.warning(f"[oracle.store] put_concepts 실패: {type(ex).__name__}")
        if self._lex is not None:
            for c, d in items.items():
                self._lex.setdefault(c, d)

    def gallery(self, limit=24):
        try:
            r = (self.sb.table("color_prompts").select("key,prompt,source,hits,result")
                 .order("updated_at", desc=True).limit(limit).execute())
            return [{"key": x["key"], "prompt": x["prompt"], "source": x["source"], "hits": x["hits"],
                     "palette": (x["result"] or {}).get("palette", [])} for x in r.data or []]
        except Exception as ex:
            logger.warning(f"[oracle.store] gallery 실패: {type(ex).__name__}")
            return []


_store = None


def get_store():
    global _store
    if _store is None:
        from utils.supabase_client import supabase_admin
        _store = SupabaseStore(supabase_admin) if supabase_admin is not None else MemoryStore()
    return _store
