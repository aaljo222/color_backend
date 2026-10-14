"""Semantic retrieval for chat knowledge-base cards using the configured MaC embedder."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "chat_kb_embeddings.json"
PAPERS_TEXT_PATH = ROOT / "data" / "papers_text"
PAPER_CHUNK_CHARS = 1200


class EmbeddingSearchError(RuntimeError):
    """The semantic index or configured embedding provider is unavailable."""


def cards_fingerprint(cards: list[dict[str, Any]]) -> str:
    searchable = [
        {key: card.get(key, "") for key in ("id", "text", "keywords", "paper")}
        for card in cards
    ]
    payload = json.dumps(searchable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def papers_fingerprint(records: list[dict[str, Any]]) -> str:
    searchable = [
        {key: record.get(key, "") for key in ("id", "file", "cite", "text", "ocr")}
        for record in records
    ]
    payload = json.dumps(searchable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def paper_records_from_extractions(
    directory: Path = PAPERS_TEXT_PATH,
    filenames: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build stable page/section chunks from the existing extraction JSON files."""
    records: list[dict[str, Any]] = []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError as exc:
        raise EmbeddingSearchError(f"Paper extraction directory unavailable: {type(exc).__name__}") from exc

    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EmbeddingSearchError(f"Invalid paper extraction {path.name}: {type(exc).__name__}") from exc
        if not isinstance(document, dict) or not isinstance(document.get("file"), str):
            raise EmbeddingSearchError(f"Invalid paper extraction metadata: {path.name}")
        filename = document["file"]
        if filenames is not None and filename not in filenames:
            continue

        units = document.get("pages") or document.get("sections") or []
        if not isinstance(units, list):
            raise EmbeddingSearchError(f"Invalid page/section list in {path.name}")
        for unit in units:
            if not isinstance(unit, dict):
                continue
            text = re.sub(r"\s+", " ", str(unit.get("text") or "")).strip()
            if not text:
                continue
            if document.get("type") == "txt" and "section" in unit:
                cite = f"{filename}, §{unit['section']}"
            else:
                page = unit.get("printed_page", unit.get("page", 1))
                cite = f"{filename}, p.{page}"
            chunks = []
            remaining = text
            while len(remaining) > PAPER_CHUNK_CHARS:
                boundary = remaining.rfind(" ", 0, PAPER_CHUNK_CHARS + 1)
                if boundary < PAPER_CHUNK_CHARS // 2:
                    boundary = PAPER_CHUNK_CHARS
                chunks.append(remaining[:boundary].strip())
                remaining = remaining[boundary:].strip()
            if remaining:
                chunks.append(remaining)
            for chunk_number, chunk in enumerate(chunks, start=1):
                stable = f"{filename}\0{cite}\0{chunk_number}\0{chunk}"
                records.append({
                    "id": hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20],
                    "file": filename,
                    "cite": cite,
                    "text": chunk,
                    "ocr": bool(unit.get("ocr")),
                })
    return records


@lru_cache(maxsize=4)
def _read_index(
    path: str,
    fingerprint: str,
    model: str,
    dimension: int,
    modified_ns: int,
    size: int,
) -> tuple[list[str], list[list[float]]]:
    del modified_ns, size
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingSearchError(f"Chat embedding index unavailable: {type(exc).__name__}") from exc

    if not isinstance(data, dict):
        raise EmbeddingSearchError("Chat embedding index must contain a JSON object")
    if data.get("cards_fingerprint") != fingerprint:
        raise EmbeddingSearchError("Chat embedding index is stale; rebuild it with scripts/build_chat_embeddings.py")
    if data.get("model") != model or data.get("dim") != dimension:
        raise EmbeddingSearchError("Chat embedding index model/dimension does not match the configured provider")

    ids = data.get("ids")
    vectors = data.get("vectors")
    if not isinstance(ids, list) or not isinstance(vectors, list) or len(ids) != len(vectors):
        raise EmbeddingSearchError("Chat embedding index has an invalid ids/vectors structure")
    if any(not isinstance(vector, list) or len(vector) != dimension for vector in vectors):
        raise EmbeddingSearchError("Chat embedding index contains an invalid vector dimension")
    try:
        numeric_vectors = [[float(value) for value in vector] for vector in vectors]
    except (TypeError, ValueError) as exc:
        raise EmbeddingSearchError("Chat embedding index contains non-numeric vector values") from exc
    if any(not math.isfinite(value) for vector in numeric_vectors for value in vector):
        raise EmbeddingSearchError("Chat embedding index contains non-finite vector values")
    return [str(card_id) for card_id in ids], numeric_vectors


@lru_cache(maxsize=4)
def _read_papers_index(
    path: str,
    fingerprint: str,
    model: str,
    dimension: int,
    modified_ns: int,
    size: int,
) -> tuple[list[dict[str, Any]], list[list[float]]]:
    del modified_ns, size
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingSearchError(f"Paper embedding index unavailable: {type(exc).__name__}") from exc

    if not isinstance(data, dict):
        raise EmbeddingSearchError("Paper embedding index must contain a JSON object")
    if data.get("papers_fingerprint") != fingerprint:
        raise EmbeddingSearchError("Paper embedding index is stale; rebuild it with scripts/build_chat_embeddings.py")
    if data.get("model") != model or data.get("dim") != dimension:
        raise EmbeddingSearchError("Paper embedding index model/dimension does not match the configured provider")

    records = data.get("paper_records")
    vectors = data.get("paper_vectors")
    if not isinstance(records, list) or not isinstance(vectors, list) or len(records) != len(vectors):
        raise EmbeddingSearchError("Paper embedding index has an invalid records/vectors structure")
    if any(not isinstance(record, dict) for record in records):
        raise EmbeddingSearchError("Paper embedding index contains an invalid record")
    if any(not isinstance(vector, list) or len(vector) != dimension for vector in vectors):
        raise EmbeddingSearchError("Paper embedding index contains an invalid vector dimension")
    try:
        numeric_vectors = [[float(value) for value in vector] for vector in vectors]
    except (TypeError, ValueError) as exc:
        raise EmbeddingSearchError("Paper embedding index contains non-numeric vector values") from exc
    if any(not math.isfinite(value) for vector in numeric_vectors for value in vector):
        raise EmbeddingSearchError("Paper embedding index contains non-finite vector values")
    return records, numeric_vectors


def _cosine(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _query_embedding(query: str, dimension: int) -> list[float]:
    try:
        from core.llm import embed_texts

        vector = [float(value) for value in embed_texts([query], task="RETRIEVAL_QUERY")[0]]
    except Exception as exc:
        raise EmbeddingSearchError(f"Chat embedding provider failed: {type(exc).__name__}") from exc
    if len(vector) != dimension or any(not math.isfinite(value) for value in vector):
        raise EmbeddingSearchError("Query embedding has an invalid dimension or non-finite values")
    return vector


def search(
    query: str,
    cards: list[dict[str, Any]],
    k: int = 3,
    index_path: Path = INDEX_PATH,
) -> list[dict[str, Any]]:
    """Rank KB cards by cosine similarity, preserving the existing hit shape."""
    if not query.strip() or not cards or k < 1:
        return []

    try:
        from core.llm import EMBED_DIM, embed_model_name

        stat = index_path.stat()
        ids, vectors = _read_index(
            str(index_path),
            cards_fingerprint(cards),
            embed_model_name(),
            EMBED_DIM,
            stat.st_mtime_ns,
            stat.st_size,
        )
    except EmbeddingSearchError:
        raise
    except (OSError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        raise EmbeddingSearchError(f"Chat semantic search unavailable: {type(exc).__name__}") from exc
    query_vector = _query_embedding(query, EMBED_DIM)
    card_by_id = {str(card["id"]): card for card in cards}
    ranked = []
    for card_id, vector in zip(ids, vectors):
        card = card_by_id.get(card_id)
        if card is None:
            raise EmbeddingSearchError(f"Chat embedding index refers to unknown card {card_id}")
        ranked.append((_cosine(query_vector, vector), card))
    ranked.sort(key=lambda item: (-item[0], str(item[1]["id"])))
    return [
        {
            "score": round(score, 4),
            "id": card["id"],
            "cite": card["cite"],
            "paper": card["paper"],
            "text": card["text"],
        }
        for score, card in ranked[:k]
    ]


def search_papers(
    query: str,
    k: int = 3,
    index_path: Path = INDEX_PATH,
    extracted_dir: Path = PAPERS_TEXT_PATH,
) -> list[dict[str, Any]]:
    """Rank OCR/text-extracted paper chunks and return page-addressable citations."""
    if not query.strip() or k < 1:
        return []

    from core.llm import EMBED_DIM, embed_model_name

    try:
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EmbeddingSearchError(
                f"Paper embedding index unavailable: {type(exc).__name__}"
            ) from exc
        if not isinstance(index_data, dict) or not isinstance(index_data.get("paper_files"), list):
            raise EmbeddingSearchError("Paper embedding index does not list indexed source files")
        source_files = {str(filename) for filename in index_data["paper_files"]}
        current_records = paper_records_from_extractions(extracted_dir, source_files)
        fingerprint = papers_fingerprint(current_records)
        stat = index_path.stat()
        records, vectors = _read_papers_index(
            str(index_path),
            fingerprint,
            embed_model_name(),
            EMBED_DIM,
            stat.st_mtime_ns,
            stat.st_size,
        )
        query_vector = _query_embedding(query, EMBED_DIM)
    except EmbeddingSearchError:
        raise
    except (OSError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        raise EmbeddingSearchError(f"Paper semantic search unavailable: {type(exc).__name__}") from exc

    ranked = sorted(
        ((_cosine(query_vector, vector), record) for record, vector in zip(records, vectors)),
        key=lambda item: (-item[0], str(item[1].get("id", ""))),
    )
    return [
        {
            "score": round(score, 4),
            "id": record["id"],
            "cite": record["cite"],
            "paper": record["file"],
            "text": record["text"],
            "url": None,
            "kind": "paper_source",
        }
        for score, record in ranked[:k]
    ]
