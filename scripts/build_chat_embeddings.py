"""Build the optional semantic index for data/chat_kb.json.

Run after setting a supported embedding provider key:
    python scripts/build_chat_embeddings.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from core.llm import EMBED_DIM, embed_model_name, embed_texts
from services.embedding_service import (
    INDEX_PATH,
    cards_fingerprint,
    paper_records_from_extractions,
    papers_fingerprint,
)
from scripts.extract_papers import OUTPUT_DIR, PAPERS_DIR, extract_file

KB_PATH = ROOT / "data" / "chat_kb.json"
BATCH_SIZE = 16
SOURCE_SUFFIXES = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def embed_with_retry(texts: list[str]) -> list[list[float]]:
    wait_seconds = 10
    for attempt in range(6):
        try:
            return embed_texts(texts, task="RETRIEVAL_DOCUMENT")
        except Exception as exc:
            message = f"{type(exc).__name__} {exc}"
            if "PerDay" in message:
                raise RuntimeError("Daily embedding quota exhausted; retry after the provider quota resets.") from exc
            quota_error = any(
                marker in message.lower()
                for marker in ("429", "resource_exhausted", "rate", "quota", "too many requests")
            )
            if not quota_error or attempt == 5:
                raise
            print(
                f"Embedding quota/rate limit; retrying in {wait_seconds}s "
                f"({attempt + 1}/5)",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)
            wait_seconds = min(wait_seconds * 2, 60)
    raise RuntimeError("Embedding retries exhausted")


def extract_sources() -> tuple[set[str], list[str]]:
    if not PAPERS_DIR.is_dir():
        return set(), [f"Paper source directory does not exist: {PAPERS_DIR}"]
    valid_files: set[str] = set()
    errors: list[str] = []
    for source in sorted(PAPERS_DIR.iterdir()):
        if not source.is_file() or source.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            report = extract_file(source)
            valid_files.add(report["file"])
            print(
                f"Extracted {report['file']}: {report['chars']} chars; "
                f"OCR pages {report['ocr'] or '-'}",
                flush=True,
            )
        except Exception as exc:
            errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
            print(f"ERROR {errors[-1]}", file=sys.stderr, flush=True)
    return valid_files, errors


def main() -> int:
    valid_paper_files, extraction_errors = extract_sources()
    cards = json.loads(KB_PATH.read_text(encoding="utf-8"))
    if not isinstance(cards, list) or not cards:
        raise ValueError("data/chat_kb.json must contain a non-empty array")
    texts = [
        f"{card['text']}\n{card['keywords']}\n{card['paper']}"
        for card in cards
    ]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = embed_with_retry(texts[start:start + BATCH_SIZE])
        if any(len(vector) != EMBED_DIM for vector in batch):
            raise ValueError(f"Embedding provider returned a vector outside configured dimension {EMBED_DIM}")
        vectors.extend(batch)
        print(f"Embedded {min(start + BATCH_SIZE, len(texts))}/{len(texts)} cards", flush=True)
    if len(vectors) != len(cards):
        raise ValueError("Embedding provider returned an incomplete card index")

    paper_records = paper_records_from_extractions(OUTPUT_DIR, valid_paper_files)
    paper_texts = [
        f"{record['file']}\n{record['cite']}\n{record['text']}"
        for record in paper_records
    ]
    paper_vectors: list[list[float]] = []
    for start in range(0, len(paper_texts), BATCH_SIZE):
        batch = embed_with_retry(paper_texts[start:start + BATCH_SIZE])
        if any(len(vector) != EMBED_DIM for vector in batch):
            raise ValueError(f"Embedding provider returned a paper vector outside configured dimension {EMBED_DIM}")
        paper_vectors.extend(batch)
        print(f"Embedded {min(start + BATCH_SIZE, len(paper_texts))}/{len(paper_texts)} paper chunks", flush=True)
    if len(paper_vectors) != len(paper_records):
        raise ValueError("Embedding provider returned an incomplete paper index")

    payload = {
        "cards_fingerprint": cards_fingerprint(cards),
        "model": embed_model_name(),
        "dim": EMBED_DIM,
        "ids": [card["id"] for card in cards],
        "vectors": vectors,
        "paper_files": sorted(valid_paper_files),
        "paper_records": paper_records,
        "papers_fingerprint": papers_fingerprint(paper_records),
        "paper_vectors": paper_vectors,
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = INDEX_PATH.with_suffix(INDEX_PATH.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(INDEX_PATH)
    print(
        f"Saved semantic index: {INDEX_PATH} "
        f"({len(vectors)} cards, {len(paper_records)} paper chunks, {payload['model']})"
    )
    return 1 if extraction_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
