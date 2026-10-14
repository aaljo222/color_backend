"""Strict, evidence-checked selection layered over the legacy TF-IDF search."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

ROOT = Path(__file__).resolve().parents[1]
PAPERS_TEXT = ROOT / "data" / "papers_text"

MIN_RELATIVE_SCORE = 0.60
AMBIGUITY_GAP = 0.01
CROSS_PAPER_SCORE = 0.28
CROSS_PAPER_RATIO = 0.70
MIN_SOURCE_TERMS = 1

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
SECTION_CITATION = re.compile(r"\u00a7\s*(\d+)")
KEYWORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}|\d+(?:\.\d+)?%?|ΔE", re.I)
SOURCE_WORD = re.compile(r"[A-Za-z]+")
Stage = Literal["relative", "evidence", "secondary"]


def _source_name(card: dict[str, Any]) -> str:
    paper = str(card.get("paper", ""))
    for pattern, filename in SOURCE_RULES:
        if pattern.search(paper):
            return filename
    raise ValueError(f"Cannot resolve source for card {card.get('id', '<unknown>')}")


def _cited_pages(cite: str) -> list[int]:
    found: list[int] = []
    for match in PAGE_CITATION.finditer(cite):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        found.extend(range(first, last + 1))
        continued = CONTINUED_PAGE.match(cite[match.end():])
        if continued:
            first, last = int(continued.group(1)), int(continued.group(2) or continued.group(1))
            found.extend(range(first, last + 1))
    return sorted(set(found))


@lru_cache(maxsize=16)
def _read_source(filename: str) -> dict[str, Any]:
    path = PAPERS_TEXT / f"{filename}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing extracted source for strict retrieval: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _citation_text(card: dict[str, Any]) -> str:
    document = _read_source(_source_name(card))
    if document.get("type") == "txt":
        section_numbers = [int(value) for value in SECTION_CITATION.findall(card["cite"])]
        sections = {
            section.get("section"): section
            for section in document.get("sections", [])
        }
        if not section_numbers or any(number not in sections for number in section_numbers):
            raise ValueError(f"Invalid TXT section citation for {card.get('id')}")
        return "\n".join(sections[number].get("text", "") for number in section_numbers)

    if document.get("type") != "pdf":
        raise ValueError(f"Unsupported extracted source type for {card.get('id')}")
    pages = document.get("pages", [])
    cited = _cited_pages(card["cite"])
    if not cited and re.search(r"poster", card["cite"], re.I) and len(pages) == 1:
        resolved = pages
    else:
        by_printed_page = {
            page["printed_page"]: page
            for page in pages
            if isinstance(page.get("printed_page"), int)
        }
        resolved = []
        for number in cited:
            page = by_printed_page.get(number)
            if page is None and 1 <= number <= len(pages):
                page = pages[number - 1]
            if page is None:
                raise ValueError(f"Invalid PDF page citation for {card.get('id')}: {number}")
            resolved.append(page)
        if not resolved:
            raise ValueError(f"Missing page citation for card {card.get('id')}")
    return "\n".join(page.get("text", "") for page in resolved)


def _stem(word: str) -> str:
    normalized = word.casefold()
    if normalized.endswith("culture"):
        return normalized[:-1]
    if normalized.endswith("cultural"):
        return normalized[:-2]
    if len(normalized) > 4 and normalized.endswith("s"):
        return normalized[:-1]
    return normalized


def _keyword_matches(card: dict[str, Any], source_text: str) -> list[str]:
    keywords = list(dict.fromkeys(KEYWORD_TOKEN.findall(card.get("keywords", ""))))
    lower_source = source_text.casefold()
    source_words = {_stem(word) for word in SOURCE_WORD.findall(source_text)}
    matches: list[str] = []
    for keyword in keywords:
        if any(character.isdigit() for character in keyword):
            number = keyword.rstrip("%")
            if number and re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])", source_text):
                matches.append(keyword)
        elif keyword.casefold() in lower_source or _stem(keyword) in source_words:
            matches.append(keyword)
    return matches


def strict_search(
    query: str,
    legacy_search: Callable[..., list[dict[str, Any]]],
    cards: list[dict[str, Any]],
    tau: float,
    stage: Stage = "secondary",
) -> list[dict[str, Any]]:
    """Select up to two citations, without changing the legacy ranker or response shape."""
    if stage not in {"relative", "evidence", "secondary"}:
        raise ValueError(f"Unknown strict retrieval stage: {stage}")

    card_by_id = {card["id"]: card for card in cards}
    hits = legacy_search(query, k=len(cards))
    eligible = [hit for hit in hits if hit["score"] >= tau]
    if not eligible:
        return []

    leading = eligible[0]
    leading_score = leading["score"]
    candidates = [
        hit for hit in eligible
        if (
            hit["paper"] == leading["paper"]
            and hit["score"] >= leading_score * MIN_RELATIVE_SCORE
        )
        or (
            hit["paper"] != leading["paper"]
            and hit["score"] >= max(
                CROSS_PAPER_SCORE,
                leading_score * CROSS_PAPER_RATIO,
            )
        )
    ]

    if stage in {"evidence", "secondary"}:
        candidates = [
            hit for hit in candidates
            if len(_keyword_matches(card_by_id[hit["id"]], _citation_text(card_by_id[hit["id"]])))
            >= MIN_SOURCE_TERMS
        ]

    if stage == "secondary":
        primary_topics = {
            card_by_id[hit["id"]].get("topic_group")
            for hit in candidates
            if card_by_id[hit["id"]].get("tier", "primary") != "secondary"
            and card_by_id[hit["id"]].get("topic_group")
        }
        candidates = [
            hit for hit in candidates
            if not (
                card_by_id[hit["id"]].get("tier") == "secondary"
                and card_by_id[hit["id"]].get("topic_group") in primary_topics
            )
        ]

    if len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] <= AMBIGUITY_GAP:
        candidates = candidates[:1]
    return candidates[:2]
