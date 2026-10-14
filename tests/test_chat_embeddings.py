import json

import pytest

from routers import chat_router
from services import embedding_service


def _card(card_id, text):
    return {
        "id": card_id,
        "cite": f"Paper, p.{card_id}",
        "paper": "Test paper",
        "text": text,
        "keywords": "color emotion",
    }


def test_semantic_search_ranks_by_cosine_and_preserves_hit_shape(tmp_path, monkeypatch):
    import core.llm as llm

    cards = [_card("first", "first card"), _card("second", "second card")]
    index_path = tmp_path / "chat_embeddings.json"
    index_path.write_text(json.dumps({
        "cards_fingerprint": embedding_service.cards_fingerprint(cards),
        "model": "test-model",
        "dim": 2,
        "ids": ["first", "second"],
        "vectors": [[0.0, 1.0], [1.0, 0.0]],
    }), encoding="utf-8")
    monkeypatch.setattr(llm, "embed_model_name", lambda: "test-model")
    monkeypatch.setattr(llm, "EMBED_DIM", 2)
    monkeypatch.setattr(llm, "embed_texts", lambda _texts, task: [[1.0, 0.0]])

    hits = embedding_service.search("second-like query", cards, k=1, index_path=index_path)

    assert hits == [{
        "score": 1.0,
        "id": "second",
        "cite": "Paper, p.second",
        "paper": "Test paper",
        "text": "second card",
    }]


def test_semantic_search_rejects_stale_index(tmp_path, monkeypatch):
    import core.llm as llm

    cards = [_card("first", "first card")]
    index_path = tmp_path / "chat_embeddings.json"
    index_path.write_text(json.dumps({
        "cards_fingerprint": "stale",
        "model": "test-model",
        "dim": 2,
        "ids": ["first"],
        "vectors": [[1.0, 0.0]],
    }), encoding="utf-8")
    monkeypatch.setattr(llm, "embed_model_name", lambda: "test-model")
    monkeypatch.setattr(llm, "EMBED_DIM", 2)

    with pytest.raises(embedding_service.EmbeddingSearchError, match="stale"):
        embedding_service.search("query", cards, index_path=index_path)


def test_hybrid_retrieval_returns_empty_when_semantic_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(chat_router, "CHAT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(chat_router, "strict_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        chat_router,
        "semantic_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            embedding_service.EmbeddingSearchError("provider unavailable")
        ),
    )
    monkeypatch.setattr(chat_router, "semantic_paper_search", lambda *_args, **_kwargs: [])

    assert chat_router.retrieve("meaning query") == []


def test_hybrid_retrieval_keeps_strict_hit_without_adding_unverified_embedding(monkeypatch):
    keyword_hit = {"id": "keyword", "score": 0.2}
    monkeypatch.setattr(chat_router, "CHAT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(chat_router, "strict_search", lambda *_args, **_kwargs: [keyword_hit])
    monkeypatch.setattr(
        chat_router,
        "semantic_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic fallback should not run when strict found a citation")
        ),
    )

    assert chat_router.retrieve("meaning query") == [keyword_hit]


def test_hybrid_retrieval_adds_high_score_ocr_source(monkeypatch):
    ocr_hit = {
        "id": "ocr-page",
        "score": 0.8,
        "cite": "scan.pdf, p.1",
        "paper": "scan.pdf",
        "text": "OCR source text",
        "url": None,
        "kind": "paper_source",
    }
    monkeypatch.setattr(chat_router, "CHAT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(chat_router, "strict_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_router, "semantic_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_router, "semantic_paper_search", lambda *_args, **_kwargs: [ocr_hit])

    assert chat_router.retrieve("paper question") == [ocr_hit]


def test_hybrid_retrieval_requires_embedding_threshold(monkeypatch):
    monkeypatch.setattr(chat_router, "CHAT_RETRIEVAL", "hybrid")
    monkeypatch.setattr(chat_router, "CHAT_EMBEDDING_TAU", 0.70)
    monkeypatch.setattr(chat_router, "strict_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        chat_router,
        "semantic_search",
        lambda *_args, **_kwargs: [{"id": "semantic", "score": 0.666}],
    )
    monkeypatch.setattr(
        chat_router,
        "semantic_paper_search",
        lambda *_args, **_kwargs: [],
    )

    assert chat_router.retrieve("out of scope query") == []
