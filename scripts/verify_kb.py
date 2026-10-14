"""Check chat_kb cards against extracted PDF page/TXT section locations."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "data" / "chat_kb.json"
EXTRACTED_DIR = ROOT / "data" / "papers_text"
REQUIRED_FIELDS = ("id", "paper", "cite", "text", "keywords")

SOURCE_RULES = (
    (re.compile(r"wilms|oberfeld", re.I), "Wilms-Oberfeld2018_Article_ColorAndEmotionEffectsOfHueSat.pdf"),
    (re.compile(r"palmer\s*&\s*schloss.*2010", re.I), "Palmer&Schloss(2010).pdf"),
    (re.compile(r"ou et al\..*2004", re.I), "2004-ou.pdf"),
    (re.compile(r"hansen.*2006", re.I), "Hansen-et-al-2006-MemoryModulatesColorAppearance-NN-9-1367.pdf"),
    (re.compile(r"zhu.*2015", re.I), "REP31_1_2015CIC_ZHU_PG133.pdf"),
    (re.compile(r"langlois", re.I), "Palmer-VSS2013.pdf"),
    (re.compile(r"neuroscience news", re.I), "a.txt"),
)
PAGE_CITATION = re.compile(r"(?i)\bpp?\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?")
CONTINUED_PAGE = re.compile(r"(?i),\s*(\d+)(?:\s*[-–]\s*(\d+))?")
SECTION_CITATION = re.compile(r"§\s*(\d+)")
WORD = re.compile(r"[a-z][a-z0-9-]{2,}", re.I)
NUMBER = re.compile(r"\d+(?:\.\d+)?\s*%?")


def _source_file(card: dict[str, Any]) -> str | None:
    paper = str(card.get("paper", ""))
    for pattern, filename in SOURCE_RULES:
        if pattern.search(paper):
            return filename
    return None


def _extract_cited_pages(cite: str) -> list[int]:
    found: list[int] = []
    for match in PAGE_CITATION.finditer(cite):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        found.extend(range(first, last + 1))
        tail = cite[match.end():]
        continued = CONTINUED_PAGE.match(tail)
        if continued:
            first, last = int(continued.group(1)), int(continued.group(2) or continued.group(1))
            found.extend(range(first, last + 1))
    return sorted(set(found))


def _resolve_pdf_pages(document: dict[str, Any], cited: list[int]) -> tuple[bool, list[dict[str, Any]]]:
    pages = document.get("pages", [])
    by_printed = {
        page["printed_page"]: page
        for page in pages
        if isinstance(page.get("printed_page"), int)
    }
    resolved: list[dict[str, Any]] = []
    valid = bool(cited)
    for number in cited:
        page = by_printed.get(number)
        if page is None and 1 <= number <= len(pages):
            page = pages[number - 1]
        if page is None:
            valid = False
        else:
            resolved.append(page)
    return valid, resolved


def _core_terms_present(card_text: str, source_text: str) -> list[str]:
    source = source_text.casefold()
    missing: set[str] = set()
    approximate = "약" in card_text or re.search(
        r"\b(?:about|approximately|around)\b", card_text, re.I
    ) is not None
    for term in NUMBER.findall(card_text):
        normalized = term.strip().casefold()
        if normalized in source:
            continue
        value_match = re.search(r"\d+(?:\.\d+)?", normalized)
        if approximate and "%" in normalized and value_match:
            target = float(value_match.group())
            decimals = len(value_match.group().partition(".")[2])
            tolerance = 0.5 * (10 ** -decimals)
            source_percentages = [
                float(match.group().replace("%", "").strip())
                for match in NUMBER.finditer(source_text)
                if "%" in match.group()
            ]
            if any(abs(value - target) <= tolerance for value in source_percentages):
                continue
        missing.add(normalized)
    for term in WORD.findall(card_text):
        normalized = term.strip().casefold()
        if normalized and normalized not in source:
            missing.add(normalized)
    return sorted(missing)


def verify() -> tuple[list[dict[str, Any]], list[str]]:
    cards = json.loads(KB_PATH.read_text(encoding="utf-8"))
    if not isinstance(cards, list):
        raise ValueError("chat_kb.json must contain an array.")
    seen: Counter[str] = Counter(
        str(card.get("id", "")) for card in cards if isinstance(card, dict)
    )
    problems: list[str] = []
    results: list[dict[str, Any]] = []

    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            problems.append(f"#{index}: card is not an object")
            continue
        errors: list[str] = []
        warnings: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if field not in card]
        non_strings = [
            field for field in REQUIRED_FIELDS
            if field in card and not isinstance(card[field], str)
        ]
        if missing:
            errors.append("missing " + ", ".join(missing))
        if non_strings:
            errors.append("non-string " + ", ".join(non_strings))
        card_id = str(card.get("id", f"row-{index}"))
        if card_id and seen[card_id] > 1:
            errors.append("duplicate id")
        text = card.get("text", "")
        if isinstance(text, str) and not 80 <= len(text) <= 140:
            warnings.append(f"text length {len(text)} (expected 80–140)")

        source_name = _source_file(card)
        source_marker = "[txt] " if source_name and source_name.endswith(".txt") else ""
        source_path = EXTRACTED_DIR / f"{source_name}.json" if source_name else None
        document = None
        if source_path and source_path.is_file():
            document = json.loads(source_path.read_text(encoding="utf-8"))
        elif source_name:
            errors.append(f"no extraction: {source_name}")
        else:
            errors.append("source file mapping unknown")

        selected_text = ""
        cite_valid = False
        if document is not None and document.get("type") == "txt":
            section_refs = [int(value) for value in SECTION_CITATION.findall(card.get("cite", ""))]
            sections = document.get("sections", [])
            section_map = {entry.get("section"): entry for entry in sections}
            cite_valid = bool(section_refs) and all(n in section_map for n in section_refs)
            selected_text = "\n".join(
                section_map[n]["text"] for n in section_refs if n in section_map
            )
            if not section_refs:
                errors.append("TXT cite must include §section")
            elif not cite_valid:
                errors.append("TXT section outside extracted range")
        elif document is not None and document.get("type") == "pdf":
            cited = _extract_cited_pages(card.get("cite", ""))
            if (
                not cited
                and re.search(r"poster", card.get("cite", ""), re.I)
                and len(document.get("pages", [])) == 1
            ):
                cite_valid, resolved = True, document["pages"]
            else:
                cite_valid, resolved = _resolve_pdf_pages(document, cited)
            selected_text = "\n".join(page.get("text", "") for page in resolved)
            if not cited and not cite_valid:
                errors.append("PDF cite has no p./pp. page number")
            elif not cite_valid:
                errors.append("cited page outside PDF/printed page range")

        if cite_valid and isinstance(text, str):
            missing_terms = _core_terms_present(text, selected_text)
            if missing_terms:
                warnings.append("core terms not found: " + ", ".join(missing_terms[:6]))
        problems.extend(f"{source_marker}{card_id}: {issue}" for issue in errors + warnings)
        results.append({
            "row": index,
            "source": source_marker + (source_name or "unknown"),
            "id": card_id,
            "cite": card.get("cite", ""),
            "citation": "OK" if cite_valid else "FAIL",
            "length": len(text) if isinstance(text, str) else "-",
            "status": "ERROR" if errors else "WARN" if warnings else "OK",
            "details": "; ".join(errors + warnings) or "-",
        })
    return results, problems


def main() -> int:
    try:
        rows, problems = verify()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("#\t출처\tID\tcite\t위치\t글자\t결과\t세부")
    for row in rows:
        print(
            f"{row['row']}\t{row['source']}\t{row['id']}\t{row['cite']}"
            f"\t{row['citation']}\t{row['length']}\t{row['status']}\t{row['details']}"
        )
    print(f"\n{len(rows)} cards; {len(problems)} warning/error item(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
