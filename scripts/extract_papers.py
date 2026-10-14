"""Extract page/section text from data/papers into data/papers_text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ocr_service import extract_image, extract_pdf


PAPERS_DIR = ROOT / "data" / "papers"
OUTPUT_DIR = ROOT / "data" / "papers_text"
PAGE_MARKER = re.compile(
    r"(?im)^\s*(?:---\s*page\s+(\d+)\s*---|\[p\.?\s*(\d+)\])\s*$"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_long_paragraph(paragraph: str, limit: int) -> list[tuple[int, str]]:
    if len(paragraph) <= limit:
        return [(0, paragraph)]
    chunks: list[tuple[int, str]] = []
    remaining = paragraph
    consumed = 0
    while len(remaining) > limit:
        boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary < limit // 2:
            boundary = limit
        piece = remaining[:boundary].rstrip()
        chunks.append((consumed, piece))
        next_start = boundary
        while next_start < len(remaining) and remaining[next_start].isspace():
            next_start += 1
        consumed += next_start
        remaining = remaining[next_start:]
    if remaining:
        chunks.append((consumed, remaining))
    return chunks


def _section_text(text: str, limit: int = 1500) -> list[dict[str, Any]]:
    paragraphs: list[tuple[int, str]] = []
    start = 0
    separator = re.compile(r"(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)")
    for match in separator.finditer(text):
        raw = text[start:match.start()]
        paragraph = raw.strip()
        if paragraph:
            paragraphs.append((start + len(raw) - len(raw.lstrip()), paragraph))
        start = match.end()
    raw = text[start:]
    paragraph = raw.strip()
    if paragraph:
        paragraphs.append((start + len(raw) - len(raw.lstrip()), paragraph))

    sections: list[tuple[int, str]] = []
    current = ""
    current_start = 0
    for paragraph_start, paragraph in paragraphs:
        for piece_offset, piece in _split_long_paragraph(paragraph, limit):
            piece_start = paragraph_start + piece_offset
            if current and len(current) + 2 + len(piece) > limit:
                sections.append((current_start, current))
                current = piece
                current_start = piece_start
            else:
                if not current:
                    current_start = piece_start
                current = f"{current}\n\n{piece}".strip()
    if current:
        sections.append((current_start, current))
    return [
        {"section": i, "start_char": start, "text": value}
        for i, (start, value) in enumerate(sections, start=1)
    ]


def _extract_txt(path: Path) -> tuple[dict[str, Any], str, list[str]]:
    raw = path.read_bytes()
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp949"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"{path.name} is neither valid UTF-8 nor CP949.") from exc

    warnings: list[str] = []
    bad_chars = text.count("\ufffd")
    suspicious = sum(
        1 for char in text
        if (ord(char) < 32 and char not in "\r\n\t\f") or char == "\ufffd"
    )
    ratio = suspicious / max(len(text), 1)
    if bad_chars or ratio > 0.01:
        warnings.append(
            f"possible text corruption: replacement={bad_chars}, suspicious_ratio={ratio:.2%}"
        )

    markers = list(PAGE_MARKER.finditer(text))
    if markers:
        pages: list[dict[str, Any]] = []
        prefix = text[:markers[0].start()].strip()
        if prefix:
            pages.append({"page": 1, "text": prefix})
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            number = int(marker.group(1) or marker.group(2))
            pages.append({"page": number, "text": text[marker.end():end].strip()})
        result: dict[str, Any] = {"file": path.name, "type": "txt", "pages": pages}
    elif "\f" in text:
        pages = [
            {"page": i, "text": part.strip()}
            for i, part in enumerate(text.split("\f"), start=1)
        ]
        result = {"file": path.name, "type": "txt", "pages": pages}
    else:
        result = {
            "file": path.name,
            "type": "txt",
            "sections": _section_text(text),
        }

    result["source_sha256"] = sha256(path)
    result["source_chars"] = len(text)
    result["encoding"] = encoding
    metadata_path = path.with_name(f"{path.name}.meta.json")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise RuntimeError(f"{metadata_path.name} must contain a JSON object.")
        result["paper_meta"] = {
            key: metadata[key] for key in ("paper", "cite_prefix") if key in metadata
        }
    return result, encoding, warnings


def extract_file(path: Path, force: bool = False) -> dict[str, Any]:
    out_path = OUTPUT_DIR / f"{path.name}.json"
    source_hash = sha256(path)
    metadata_path = path.with_name(f"{path.name}.meta.json")
    metadata_hash = sha256(metadata_path) if metadata_path.exists() else ""
    signature = hashlib.sha256(f"{source_hash}:{metadata_hash}".encode()).hexdigest()
    if out_path.exists() and not force:
        try:
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            if cached.get("source_signature") == signature:
                return {
                    "file": path.name,
                    "status": "unchanged",
                    "chars": cached.get("source_chars", sum(
                        len(item["text"])
                        for item in cached.get("pages", cached.get("sections", []))
                    )),
                    "pages": len(cached.get("pages", [])),
                    "sections": len(cached.get("sections", [])),
                    "page_map": [
                        f"{item['page']}→{item['printed_page']}"
                        + ("*" if item.get("printed_page_inferred") else "")
                        for item in cached.get("pages", [])
                        if "printed_page" in item
                    ],
                    "ocr": [item["page"] for item in cached.get("pages", []) if item.get("ocr")],
                    "encoding": cached.get("encoding", "-"),
                    "warnings": [],
                }
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages, ocr_pages = extract_pdf(path)
        result: dict[str, Any] = {
            "file": path.name,
            "type": "pdf",
            "pages": pages,
            "source_sha256": source_hash,
            "source_signature": signature,
            "source_chars": sum(len(item["text"]) for item in pages),
        }
        encoding = "-"
        warnings: list[str] = []
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        pages, ocr_pages = extract_image(path)
        result = {
            "file": path.name,
            "type": "image",
            "pages": pages,
            "source_sha256": source_hash,
            "source_signature": signature,
            "source_chars": sum(len(item["text"]) for item in pages),
        }
        encoding = "-"
        warnings = []
    else:
        result, encoding, warnings = _extract_txt(path)
        result["source_signature"] = signature
        pages = result.get("pages", [])
        ocr_pages = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    text_items = result.get("pages", result.get("sections", []))
    page_map = [
        f"{item['page']}→{item['printed_page']}"
        + ("*" if item.get("printed_page_inferred") else "")
        for item in result.get("pages", [])
        if "printed_page" in item
    ]
    return {
        "file": path.name,
        "status": "extracted",
        "chars": result.get(
            "source_chars", sum(len(item["text"]) for item in text_items)
        ),
        "pages": len(result.get("pages", [])),
        "sections": len(result.get("sections", [])),
        "page_map": page_map,
        "ocr": ocr_pages,
        "encoding": encoding,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-extract unchanged files")
    args = parser.parse_args()
    if not PAPERS_DIR.is_dir():
        parser.error(f"source directory does not exist: {PAPERS_DIR}")
    inputs = sorted(
        path for path in PAPERS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {
            ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"
        }
    )
    if not inputs:
        parser.error(f"no PDF or TXT sources found in {PAPERS_DIR}")

    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in inputs:
        try:
            reports.append(extract_file(path, force=args.force))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    print("file\tstatus\tpages\tsections\tchars\tPDF→printed page\tOCR pages\tTXT encoding\twarnings")
    for item in reports:
        print(
            f"{item['file']}\t{item['status']}\t{item['pages']}\t{item['sections']}"
            f"\t{item['chars']}\t{', '.join(item.get('page_map', [])) or '-'}"
            f"\t{item['ocr'] or '-'}\t{item['encoding']}"
            f"\t{'; '.join(item['warnings']) or '-'}"
        )
    for error in errors:
        print(f"ERROR\t{error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
