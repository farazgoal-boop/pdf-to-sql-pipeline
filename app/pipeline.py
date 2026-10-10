"""Batch pipeline: find PDFs, extract their text, store each one in the database."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import LOG_FILE, Settings, settings as default_settings
from app.database import Database, Document, Page
from app.extractor import ExtractionError, check_ocr, extract_pdf, file_sha256

logger = logging.getLogger("pdf_pipeline")

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"


def setup_logging(console_level: int = logging.INFO, log_file: Path = LOG_FILE) -> logging.Logger:
    """Log to the console and to output/pipeline.log. Safe to call more than once."""
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = next((h for h in logger.handlers if isinstance(h, logging.FileHandler)), None)
    if file_handler is None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

    console = next(
        (h for h in logger.handlers if type(h) is logging.StreamHandler), None
    )
    if console is None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
    console.setLevel(console_level)
    return logger


@dataclass
class FileResult:
    file_name: str
    status: str  # success / partial / failed / skipped
    pages: int = 0
    ocr_pages: int = 0
    seconds: float = 0.0
    message: str = ""


@dataclass
class PipelineSummary:
    files_found: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    partial: int = 0
    total_pages: int = 0
    ocr_pages: int = 0
    seconds: float = 0.0
    results: list[FileResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "files_found": self.files_found,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "partial": self.partial,
            "total_pages": self.total_pages,
            "ocr_pages": self.ocr_pages,
            "seconds": round(self.seconds, 2),
        }


ProgressCallback = Callable[[int, int, FileResult], None]


def find_pdfs(input_dir: str | Path, recursive: bool = False) -> list[Path]:
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")
    candidates = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(p for p in candidates if p.is_file() and p.suffix.lower() == ".pdf")


def process_file(path: Path, db: Database, force: bool = False, cfg: Settings | None = None) -> FileResult:
    """Extract one PDF and store it. Never raises: errors are returned as a 'failed' result."""
    cfg = cfg or default_settings
    started = time.perf_counter()
    try:
        file_hash = file_sha256(path)
    except OSError as exc:
        logger.error("%s: cannot read file: %s", path.name, exc)
        return FileResult(path.name, "failed", message=f"Cannot read file: {exc}")

    existing = db.find_by_hash(file_hash)
    # Previously failed files are retried; successful/partial ones are skipped.
    if existing is not None and not force and existing.status != "failed":
        note = "already in database" if existing.file_name == path.name else f"duplicate of {existing.file_name}"
        logger.info("%s: skipped (%s)", path.name, note)
        return FileResult(path.name, "skipped", existing.page_count, existing.ocr_page_count, message=note)

    document = Document(file_name=path.name, file_path=str(path.resolve()), file_hash=file_hash)
    try:
        extracted = extract_pdf(path, cfg)
        document.page_count = extracted.page_count
        document.ocr_page_count = extracted.ocr_page_count
        document.status = "partial" if extracted.warnings else "success"
        document.error_message = " ".join(extracted.warnings) or None
        document.pages = [
            Page(
                page_number=p.page_number,
                text=p.text,
                extraction_method=p.method,
                char_count=p.char_count,
                ocr_confidence=p.ocr_confidence,
            )
            for p in extracted.pages
        ]
    except ExtractionError as exc:
        document.page_count = 0
        document.ocr_page_count = 0
        document.status = "failed"
        document.error_message = str(exc)
    except Exception as exc:  # unexpected library error: still don't stop the batch
        logger.exception("%s: unexpected extraction error", path.name)
        document.page_count = 0
        document.ocr_page_count = 0
        document.status = "failed"
        document.error_message = f"Unexpected error: {exc}"

    try:
        db.save_document(document, replace=existing is not None)
    except Exception as exc:
        logger.exception("%s: database write failed", path.name)
        return FileResult(path.name, "failed", seconds=time.perf_counter() - started, message=f"Database error: {exc}")

    result = FileResult(
        file_name=path.name,
        status=document.status,
        pages=document.page_count,
        ocr_pages=document.ocr_page_count,
        seconds=time.perf_counter() - started,
        message=document.error_message or ("reprocessed" if existing is not None else ""),
    )
    log = logger.error if result.status == "failed" else logger.warning if result.status == "partial" else logger.info
    log(
        "%s: %s - %d page(s), %d OCR, %.2fs%s",
        path.name, result.status, result.pages, result.ocr_pages, result.seconds,
        f" - {result.message}" if result.message else "",
    )
    return result


def process_files(
    paths: Iterable[Path],
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
    db: Database | None = None,
    cfg: Settings | None = None,
) -> PipelineSummary:
    cfg = cfg or default_settings
    db = db or Database(cfg.database_url)
    paths = list(paths)
    summary = PipelineSummary(files_found=len(paths))
    started = time.perf_counter()

    ocr = check_ocr(cfg.tesseract_cmd, cfg.ocr_lang)
    if not ocr.available:
        logger.warning(ocr.message)

    for index, path in enumerate(paths, start=1):
        result = process_file(Path(path), db, force=force, cfg=cfg)
        summary.results.append(result)
        if result.status == "skipped":
            summary.skipped += 1
        elif result.status == "failed":
            summary.failed += 1
        else:
            summary.processed += 1
            summary.partial += result.status == "partial"
            summary.total_pages += result.pages
            summary.ocr_pages += result.ocr_pages
        if progress_callback is not None:
            progress_callback(index, len(paths), result)

    summary.seconds = time.perf_counter() - started
    logger.info(
        "Batch finished: %d found, %d processed, %d skipped, %d failed, %d pages (%d OCR) in %.2fs",
        summary.files_found, summary.processed, summary.skipped, summary.failed,
        summary.total_pages, summary.ocr_pages, summary.seconds,
    )
    return summary


def process_folder(
    input_dir: str | Path,
    force: bool = False,
    recursive: bool = False,
    progress_callback: ProgressCallback | None = None,
    db: Database | None = None,
    cfg: Settings | None = None,
) -> PipelineSummary:
    """Process every PDF in a folder. Already-imported files (same SHA-256) are skipped unless force=True."""
    paths = find_pdfs(input_dir, recursive=recursive)
    logger.info("Found %d PDF(s) in %s%s", len(paths), input_dir, " (recursive)" if recursive else "")
    return process_files(paths, force=force, progress_callback=progress_callback, db=db, cfg=cfg)
