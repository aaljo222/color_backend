"""Append a human-written card proposal grounded in one extracted source location."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_DIR = ROOT / "data" / "papers_text"
KB_PATH = ROOT / "data" / "chat_kb.json"
PENDING_PATH = ROOT / "data" / "kb_pending.json"
FIELDS = ("id", "paper", "cite", "text", "keywords")
PAGE_CITATION = re.compile(r"(?i)\bpp?\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?")
CONTINUED_PAGE = re.compile(r"(?i),\s*(\d+)(?:\s*[-–]\s*(\d+))?")


def _read_location(
    source: dict[str, Any], cite: str, evidence: str
) -> tuple[str, str]:
    if source.get("type") == "txt":
        match = re.search(r"§\s*(\d+)", cite)
        if not match:
            raise ValueError("TXT citations must identify a section with §N.")
        section_number = int(match.group(1))
        section = next(
            (item for item in source.get("sections", [])
             if item.get("section") == section_number),
            None,
        )
        if section is None:
            raise ValueError(f"TXT section {section_number} does not exist.")
        if evidence not in section["text"]:
            raise ValueError("Evidence excerpt is not present in the cited TXT section.")
        return f"절 {section_number} (시작 글자 위치 {section['start_char']})", evidence

    pages = source.get("pages", [])
    refs: list[int] = []
    for match in PAGE_CITATION.finditer(cite):
        first = int(match.group(1))
        last = int(match.group(2) or first)
        refs.extend(range(first, last + 1))
        continued = CONTINUED_PAGE.match(cite[match.end():])
        if continued:
            first = int(continued.group(1))
            last = int(continued.group(2) or first)
            refs.extend(range(first, last + 1))
    if not refs:
        raise ValueError("PDF citations must include p.N or pp.N–M.")
    chosen = None
    for number in refs:
        chosen = next(
            (item for item in pages
             if item.get("printed_page") == number or item.get("page") == number),
            None,
        )
        if chosen and evidence in chosen.get("text", ""):
            break
        chosen = None
    if chosen is None:
        raise ValueError("Evidence excerpt was not found at any cited PDF page.")
    page_label = f"PDF p.{chosen['page']}"
    if "printed_page" in chosen:
        page_label += f" (인쇄 p.{chosen['printed_page']})"
    return page_label, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="basename in data/papers_text")
    for field in FIELDS:
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--evidence", required=True, help="verbatim short excerpt from source")
    args = parser.parse_args()

    source_path = EXTRACTED_DIR / args.source
    if source_path.parent != EXTRACTED_DIR or not source_path.is_file():
        parser.error(f"source must be an extracted JSON in {EXTRACTED_DIR}")
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(source, dict) or source.get("type") not in {"pdf", "txt"}:
            raise ValueError("source JSON must be an extracted PDF/TXT document.")
        location, excerpt = _read_location(source, args.cite, args.evidence)
        card = {field: getattr(args, field) for field in FIELDS}
        if any(not isinstance(value, str) for value in card.values()):
            raise ValueError("all card fields must be strings.")
        if not 80 <= len(card["text"]) <= 140:
            raise ValueError(f"text must be 80–140 characters (got {len(card['text'])}).")
        keywords = [value for value in re.split(r"[,，\s]+", card["keywords"]) if value]
        source_text = "\n".join(
            item["text"]
            for item in source.get("pages", source.get("sections", []))
        ).casefold()
        unrelated = [word for word in keywords if word.casefold() not in source_text]
        if unrelated:
            raise ValueError("keywords not present in source text: " + ", ".join(unrelated))
        existing = json.loads(KB_PATH.read_text(encoding="utf-8"))
        pending = (
            json.loads(PENDING_PATH.read_text(encoding="utf-8"))
            if PENDING_PATH.exists() else []
        )
        if not isinstance(pending, list):
            raise ValueError("kb_pending.json must contain an array.")
        ids = {
            item.get("id")
            for item in [*existing, *pending]
            if isinstance(item, dict)
        }
        if card["id"] in ids:
            raise ValueError(f"duplicate card id: {card['id']}")
        card["_note"] = {
            "source_file": source.get("file"),
            "evidence_location": location,
            "source_excerpt": excerpt,
        }
        pending.append(card)
        PENDING_PATH.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Draft {card['id']} appended to data/kb_pending.json; chat_kb.json unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
