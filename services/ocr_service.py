"""PDF page and raster-image text extraction with optional Tesseract OCR."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pymupdf

OCR_MIN_CHARS = 50
OCR_LANGUAGES = "kor+eng"


def _page_number_from_footer(page: pymupdf.Page) -> int | None:
    height = page.rect.height
    candidates: list[tuple[float, int]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text.isdigit() and len(text) <= 4:
                y0, y1 = line["bbox"][1], line["bbox"][3]
                if y0 < height * 0.08 or y1 > height * 0.92:
                    candidates.append((min(y0, height - y1), int(text)))
    return min(candidates)[1] if candidates else None


def _ocr_page(page: pymupdf.Page, source: Path, page_number: int) -> str:
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            f"{source.name} page {page_number} needs Tesseract OCR ({OCR_LANGUAGES}), "
            "but tesseract is not installed."
        )
    try:
        text_page = page.get_textpage_ocr(language=OCR_LANGUAGES, full=True)
    except Exception as exc:
        raise RuntimeError(f"OCR failed for {source.name} page {page_number}: {exc}") from exc
    return page.get_text("text", textpage=text_page).strip()


def extract_pdf(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Extract searchable PDF text and OCR pages with fewer than 50 text characters."""
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF {path.name}: {exc}") from exc

    pages: list[dict[str, Any]] = []
    ocr_pages: list[int] = []
    try:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            used_ocr = len(text) < OCR_MIN_CHARS
            if used_ocr:
                text = _ocr_page(page, path, page_index)
                ocr_pages.append(page_index)
            entry: dict[str, Any] = {
                "page": page_index,
                "text": text,
                "_detected_printed_page": _page_number_from_footer(page),
            }
            if used_ocr:
                entry["ocr"] = True
            pages.append(entry)
    finally:
        document.close()

    offsets: dict[int, int] = {}
    for entry in pages:
        printed = entry["_detected_printed_page"]
        if printed is not None:
            offset = printed - (entry["page"] - 1)
            offsets[offset] = offsets.get(offset, 0) + 1
    offset, support = max(offsets.items(), key=lambda item: item[1]) if offsets else (0, 0)
    infer_sequence = support >= 2
    for entry in pages:
        detected = entry.pop("_detected_printed_page")
        expected = offset + entry["page"] - 1
        if infer_sequence:
            entry["printed_page"] = expected
            if detected != expected:
                entry["printed_page_inferred"] = True
        elif detected is not None:
            entry["printed_page"] = detected
    return pages, ocr_pages


def extract_image(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """OCR one raster image as a single source page."""
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise RuntimeError(f"Could not open image {path.name}: {exc}") from exc
    try:
        if len(document) != 1:
            raise RuntimeError(f"Expected one image page for {path.name}, got {len(document)}")
        text = _ocr_page(document[0], path, 1)
    finally:
        document.close()
    return [{"page": 1, "text": text, "ocr": True}], [1]
