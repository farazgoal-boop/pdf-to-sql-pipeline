"""End-to-end tests for extraction and the database pipeline (temporary SQLite DB)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from app.config import settings
from app.database import Database, Document, generate_schema_sql
from app.extractor import ExtractionError, check_ocr, clean_text, extract_pdf
from app.pipeline import process_folder

OCR_AVAILABLE = check_ocr(settings.tesseract_cmd, settings.ocr_lang).available
needs_ocr = pytest.mark.skipif(not OCR_AVAILABLE, reason="Tesseract OCR is not installed")


# --------------------------------------------------------------------------- helpers
def make_text_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def make_image_pdf(path: Path, text: str) -> Path:
    """A PDF whose only page is a raster image of `text` (no text layer)."""
    scratch = pymupdf.open()
    tmp = scratch.new_page()
    tmp.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=16)
    pix = tmp.get_pixmap(dpi=150)
    scratch.close()

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield database
    database.engine.dispose()


@pytest.fixture
def pdf_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "pdfs"
    folder.mkdir()
    make_text_pdf(folder / "report.pdf", [
        "Alpha page one contains the quarterly revenue figures for the company.",
        "Beta page two describes the warehouse expansion project in detail.",
    ])
    return folder


# --------------------------------------------------------------------------- extraction
def test_clean_text_normalises_whitespace_and_keeps_paragraphs():
    raw = "Hello\x00   world\t!\r\n\r\n\r\n\r\nSecond  paragraph   \n"
    assert clean_text(raw) == "Hello world !\n\nSecond paragraph"


def test_text_extraction_multipage(tmp_path: Path):
    pdf = make_text_pdf(tmp_path / "doc.pdf", ["First page text here, long enough.", "Second page text, also long."])
    result = extract_pdf(pdf)
    assert result.page_count == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert all(p.method == "text" for p in result.pages)
    assert "First page text" in result.pages[0].text
    assert "Second page text" in result.pages[1].text
    assert result.pages[0].ocr_confidence is None
    assert not result.warnings


@needs_ocr
def test_ocr_fallback_for_image_only_page(tmp_path: Path):
    pdf = make_image_pdf(tmp_path / "scan.pdf", "INVOICE NUMBER 4471\nTotal amount due 250 dollars")
    result = extract_pdf(pdf)
    page = result.pages[0]
    assert page.method == "ocr"
    assert "INVOICE" in page.text.upper()
    assert "4471" in page.text
    assert page.ocr_confidence is not None and page.ocr_confidence > 50
    assert result.ocr_page_count == 1


def test_missing_tesseract_falls_back_to_text_only(tmp_path: Path):
    pdf = make_image_pdf(tmp_path / "scan.pdf", "Scanned content")
    cfg = replace(settings, tesseract_cmd=str(tmp_path / "no-such-tesseract.exe"))
    result = extract_pdf(pdf, cfg)
    assert result.pages[0].method == "text"
    assert result.pages[0].text == ""
    assert any("OCR" in w for w in result.warnings)


def test_corrupt_file_raises_extraction_error(tmp_path: Path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not really a pdf\x00\x01\x02")
    with pytest.raises(ExtractionError):
        extract_pdf(bad)


def test_encrypted_pdf_raises_extraction_error(tmp_path: Path):
    path = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    doc.close()
    with pytest.raises(ExtractionError, match="password"):
        extract_pdf(path)


# --------------------------------------------------------------------------- pipeline + DB
def test_pipeline_stores_pages(db: Database, pdf_dir: Path):
    summary = process_folder(pdf_dir, db=db)
    assert (summary.files_found, summary.processed, summary.failed) == (1, 1, 0)
    assert summary.total_pages == 2

    pages = db.pages_df()
    assert list(pages["page_number"]) == [1, 2]
    assert pages.loc[0, "file_name"] == "report.pdf"
    assert "quarterly revenue" in pages.loc[0, "text"]
    assert db.search("WAREHOUSE")[0]["page_number"] == 2


def test_duplicates_are_skipped(db: Database, pdf_dir: Path):
    process_folder(pdf_dir, db=db)
    # Same content under a different name is also a duplicate.
    (pdf_dir / "copy_of_report.pdf").write_bytes((pdf_dir / "report.pdf").read_bytes())
    second = process_folder(pdf_dir, db=db)
    assert second.files_found == 2
    assert second.skipped == 2
    assert second.processed == 0
    assert db.stats()["documents"] == 1


def test_force_reprocess_replaces_record(db: Database, pdf_dir: Path):
    process_folder(pdf_dir, db=db)
    first_processed = db.documents_df()["processed_at"].iloc[0]
    summary = process_folder(pdf_dir, force=True, db=db)
    assert summary.processed == 1 and summary.skipped == 0
    docs = db.documents_df()
    assert len(docs) == 1
    assert docs["processed_at"].iloc[0] > first_processed
    assert db.stats()["pages"] == 2  # old pages were cascade-deleted, not duplicated


def test_corrupt_file_does_not_stop_batch(db: Database, pdf_dir: Path):
    (pdf_dir / "aaa_corrupt.pdf").write_bytes(b"garbage, definitely not a PDF")
    summary = process_folder(pdf_dir, db=db)
    assert summary.files_found == 2
    assert summary.failed == 1
    assert summary.processed == 1

    with db.Session() as session:
        failed = session.query(Document).filter_by(status="failed").one()
        assert failed.file_name == "aaa_corrupt.pdf"
        assert failed.error_message
        assert failed.page_count == 0


def test_recursive_option(db: Database, pdf_dir: Path):
    sub = pdf_dir / "sub"
    sub.mkdir()
    make_text_pdf(sub / "nested.pdf", ["Nested document with enough text to skip OCR."])
    assert process_folder(pdf_dir, db=db).files_found == 1
    assert process_folder(pdf_dir, recursive=True, db=db).files_found == 2


def test_export_csv_and_schema(db: Database, pdf_dir: Path, tmp_path: Path):
    process_folder(pdf_dir, db=db)
    assert db.export_csv(tmp_path / "out" / "pages.csv") == 2
    schema = generate_schema_sql(tmp_path / "schema.sql").read_text(encoding="utf-8")
    assert "LONGTEXT" in schema and "CREATE TABLE pages" in schema
