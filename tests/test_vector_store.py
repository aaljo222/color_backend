"""emb-1: KB·코퍼스 임베딩을 테이블(mac_embeddings)에 저장하고, 지금 모델로 없으면 그 자리에서 만든다."""
import json
import pytest

from core import vector_store as vs
from core import rag as ragmod
from core.corpus import get_corpus
from core.kb import KB, make_retriever


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    vs._MEM.clear()
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    yield
    vs._MEM.clear()


def _fake_provider(monkeypatch, model="fake:bag:1"):
    """글자 가방 임베딩 — 결정론. 호출 횟수를 센다."""
    from oracle import similar
    c, kb = get_corpus(), KB()
    vocab = sorted({ch for s in c.scenes for ch in s["text"]} | {ch for e in kb.items for ch in kb.text_of(e)})
    calls = {"document": 0, "query": 0, "texts": 0}

    def embed_many(texts, kind="document"):
        calls[kind] += 1
        calls["texts"] += len(texts) if kind == "document" else 0
        return [[float(t.count(ch)) + 1e-6 for ch in vocab] for t in texts]
    monkeypatch.setattr(similar, "model_name", lambda: model)
    monkeypatch.setattr(similar, "embed_many", embed_many)
    return calls


def test_corpus_rag_uses_store_and_embeds_only_once(monkeypatch, tmp_path):
    monkeypatch.setattr(ragmod, "EMBED_PATH", tmp_path / "없는파일.json")    # 레포 파일 없이도 임베딩 검색
    calls = _fake_provider(monkeypatch)
    c = get_corpus()
    r = ragmod.CorpusRAG(c)
    assert r.method == "embedding" and r.emb_source == "store"
    assert calls["texts"] == len(c.scenes)
    assert r.search("어제 일처럼 또렷하게", axis="quality", k=1)[0].passage["kb_id"] == "vivid"
    ragmod.CorpusRAG(c)                                                     # 두 번째: 저장된 벡터 그대로 → 새 임베딩 0
    assert calls["texts"] == len(c.scenes)


def test_model_change_reembeds_and_text_change_reembeds_only_that_item(monkeypatch):
    calls = _fake_provider(monkeypatch, "fake:a:1")
    items = [("x", "바닷가 노을"), ("y", "엄마 손")]
    assert set(vs.vectors("corpus", items)) == {"x", "y"} and calls["texts"] == 2
    vs.vectors("corpus", [("x", "바닷가 노을"), ("y", "엄마 손 따뜻함")])        # 문장이 바뀐 y 만
    assert calls["texts"] == 3
    _fake_provider(monkeypatch, "fake:b:1")                                 # 모델이 바뀌면 다른 행 (섞지 않는다)
    vs.vectors("corpus", items)
    assert set(vs._MEM) == {("corpus", "fake:a:1"), ("corpus", "fake:b:1")}


def test_no_key_or_off_or_failure_returns_none(monkeypatch):
    from oracle import similar
    monkeypatch.setattr(similar, "model_name", lambda: None)
    assert vs.vectors("kb", [("a", "가")]) is None                            # 키 없음
    _fake_provider(monkeypatch)
    monkeypatch.setenv("VECTOR_STORE", "off")
    assert vs.vectors("kb", [("a", "가")]) is None                            # 끔
    monkeypatch.delenv("VECTOR_STORE")

    def boom(texts, kind="document"):
        raise RuntimeError("API 장애")
    monkeypatch.setattr(similar, "embed_many", boom)
    assert vs.vectors("kb", [("a", "가")]) is None                            # 장애 → 호출한 쪽이 파일/ngram


def test_kb_retriever_embedding_uses_store(monkeypatch):
    _fake_provider(monkeypatch)
    kb = KB()
    r = make_retriever(kb, "embedding")
    assert type(r).__name__ == "StoreRetriever" and r.name == "embedding"
    top = r.search(kb.text_of(kb.by_id["sea"]), "space")[0]
    assert top[1] == "sea" and top[0] > 0.99


def test_kb_retriever_without_key_uses_file_then_ngram(monkeypatch):
    from oracle import similar
    monkeypatch.setattr(similar, "model_name", lambda: None)                 # 키 없음 → 테이블 검색기 못 씀
    assert type(make_retriever(KB(), "embedding")).__name__ == "EmbeddingRetriever"   # 예전처럼 레포 파일 검색기
    monkeypatch.setattr("core.llm.embed_model_name", lambda: "other:model")
    assert make_retriever(KB(), "embedding").name == "ngram"                  # 파일 모델도 안 맞으면 ngram


class _FakeSB:
    """supabase-py 흉내: upsert 저장 → select 시 vector 칸을 문자열로 돌려준다 (실제 PostgREST 와 같게)."""
    def __init__(self):
        self.rows = {}

    def table(self, name):
        assert name == "mac_embeddings"
        return _Q(self)


class _Q:
    def __init__(self, sb):
        self.sb, self.f, self.op, self.payload, self.rng = sb, {}, "select", None, (0, 10 ** 9)

    def select(self, cols): return self
    def eq(self, k, v): self.f[k] = v; return self
    def range(self, a, b): self.rng = (a, b); return self

    def upsert(self, rows, on_conflict=None):
        assert on_conflict == "kind,item_id,embedding_model"
        self.op, self.payload = "upsert", rows
        return self

    def execute(self):
        import types
        if self.op == "upsert":
            for r in self.payload:
                self.sb.rows[(r["kind"], r["item_id"], r["embedding_model"])] = {**r, "embedding": json.dumps(r["embedding"])}
            return types.SimpleNamespace(data=self.payload)
        hit = [r for r in self.sb.rows.values() if all(r[k] == v for k, v in self.f.items())]
        return types.SimpleNamespace(data=hit[self.rng[0]:self.rng[1] + 1])


def test_supabase_table_roundtrip(monkeypatch):
    calls = _fake_provider(monkeypatch)
    sb = _FakeSB()
    monkeypatch.setattr(vs, "_sb", lambda: sb)
    items = [("x", "바닷가 노을"), ("y", "엄마 손")]
    a = vs.vectors("kb", items)
    assert len(sb.rows) == 2 and all(r["content_hash"] == vs.content_hash(t) for (_, i, _), r in sb.rows.items()
                                     for j, t in items if i == j)
    b = vs.vectors("kb", items)                                             # 테이블에서 읽음 (문자열 → 숫자) → 새 임베딩 0
    assert calls["texts"] == 2 and all((a[i] == b[i]).all() for i, _ in items)
    st = vs.status()
    assert st["backend"] == "supabase" and st["model"] == "fake:bag:1" and st["rows"]["kb"] == 2
