import json

import pytest

from scripts import extract_papers
from services import embedding_service, ocr_service


class _Page:
    def __init__(self, text=""):
        self.text = text
        self.rect = type("Rect", (), {"height": 1000})()

    def get_text(self, kind, textpage=None):
        if kind == "dict":
            return {"blocks": []}
        return "OCR로 읽은 색채 연구 본문입니다." if textpage else self.text

    def get_textpage_ocr(self, language, full):
        assert language == "kor+eng"
        assert full is True
        return object()


class _Document(list):
    def close(self):
        self.closed = True


def test_extract_image_uses_korean_and_english_ocr(monkeypatch, tmp_path):
    page = _Page()
    document = _Document([page])
    monkeypatch.setattr(ocr_service.pymupdf, "open", lambda _path: document)
    monkeypatch.setattr(ocr_service.shutil, "which", lambda _name: "tesseract.exe")

    pages, ocr_pages = ocr_service.extract_image(tmp_path / "paper.png")

    assert pages == [{"page": 1, "text": "OCR로 읽은 색채 연구 본문입니다.", "ocr": True}]
    assert ocr_pages == [1]
    assert document.closed


def test_extract_image_reports_missing_tesseract(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_service.pymupdf, "open", lambda _path: _Document([_Page()]))
    monkeypatch.setattr(ocr_service.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="Tesseract OCR"):
        ocr_service.extract_image(tmp_path / "scanned.png")


def test_extract_file_writes_image_extraction_json(monkeypatch, tmp_path):
    source = tmp_path / "scanned.png"
    source.write_bytes(b"test image bytes")
    output_dir = tmp_path / "papers_text"
    monkeypatch.setattr(extract_papers, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(
        extract_papers,
        "extract_image",
        lambda _path: ([{"page": 1, "text": "recognized words", "ocr": True}], [1]),
    )

    report = extract_papers.extract_file(source)

    extracted = json.loads((output_dir / "scanned.png.json").read_text(encoding="utf-8"))
    assert extracted["type"] == "image"
    assert extracted["pages"][0]["ocr"] is True
    assert report["ocr"] == [1]
    assert report["chars"] == len("recognized words")


def test_paper_records_preserve_page_and_ocr_metadata(tmp_path):
    extraction_dir = tmp_path / "papers_text"
    extraction_dir.mkdir()
    (extraction_dir / "scan.pdf.json").write_text(json.dumps({
        "file": "scan.pdf",
        "type": "pdf",
        "pages": [{
            "page": 3,
            "printed_page": 7,
            "text": "A" * 1300,
            "ocr": True,
        }],
    }), encoding="utf-8")

    records = embedding_service.paper_records_from_extractions(extraction_dir)

    assert len(records) == 2
    assert {record["cite"] for record in records} == {"scan.pdf, p.7"}
    assert all(record["ocr"] for record in records)
    assert all(len(record["text"]) <= embedding_service.PAPER_CHUNK_CHARS for record in records)


def test_ocr_paper_search_returns_source_page_citation(tmp_path, monkeypatch):
    import core.llm as llm

    extraction_dir = tmp_path / "papers_text"
    extraction_dir.mkdir()
    (extraction_dir / "scan.pdf.json").write_text(json.dumps({
        "file": "scan.pdf",
        "type": "pdf",
        "pages": [{"page": 3, "printed_page": 7, "text": "광학 문자 인식으로 추출한 연구 결과", "ocr": True}],
    }), encoding="utf-8")
    records = embedding_service.paper_records_from_extractions(extraction_dir)
    index_path = tmp_path / "chat_embeddings.json"
    index_path.write_text(json.dumps({
        "papers_fingerprint": embedding_service.papers_fingerprint(records),
        "model": "test-model",
        "dim": 2,
        "paper_files": ["scan.pdf"],
        "paper_records": records,
        "paper_vectors": [[1.0, 0.0]],
    }), encoding="utf-8")
    monkeypatch.setattr(llm, "embed_model_name", lambda: "test-model")
    monkeypatch.setattr(llm, "EMBED_DIM", 2)
    monkeypatch.setattr(llm, "embed_texts", lambda _texts, task: [[1.0, 0.0]])

    hits = embedding_service.search_papers(
        "연구 결과", index_path=index_path, extracted_dir=extraction_dir
    )

    assert hits[0]["cite"] == "scan.pdf, p.7"
    assert hits[0]["kind"] == "paper_source"
    assert hits[0]["score"] == 1.0
