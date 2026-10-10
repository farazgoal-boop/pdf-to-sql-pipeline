"""Command-line entry point for the PDF -> SQL pipeline.

Examples:
    python run.py                                  # process sample_pdfs/
    python run.py --input "D:\\Client PDFs" --recursive
    python run.py --force                          # re-extract files already in the DB
    python run.py --export-csv output/pages.csv    # also export all pages to CSV
    python run.py --stats --export-xlsx output/pdf_data.xlsx   # export to Excel without processing
    python run.py --stats                          # show what is in the database
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app import __version__
from app.config import settings
from app.database import Database, generate_schema_sql
from app.extractor import check_ocr
from app.pipeline import FileResult, process_folder, setup_logging

STATUS_LABELS = {"success": "OK", "partial": "PARTIAL", "failed": "FAILED", "skipped": "SKIPPED"}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _rule(char: str = "-", width: int = 64) -> str:
    return char * width


def _table(rows: list[tuple[str, object]], width: int = 64) -> str:
    key_width = max(len(k) for k, _ in rows) + 2
    lines = [_rule("-", width)]
    lines += [f"  {k:<{key_width}}{v}" for k, v in rows]
    lines.append(_rule("-", width))
    return "\n".join(lines)


def print_header(db: Database) -> None:
    ocr = check_ocr(settings.tesseract_cmd, settings.ocr_lang)
    print(_rule("="))
    print(f"  PDF -> SQL Extractor v{__version__}")
    print(_rule("="))
    print(f"  Database : {db.backend} | {db.masked_url}")
    print(f"  OCR      : {'ready - ' + ocr.version if ocr.available else 'NOT AVAILABLE'}"
          f" (lang={settings.ocr_lang}, min chars={settings.ocr_min_chars}, dpi={settings.ocr_dpi})")
    if not ocr.available:
        print(f"             {ocr.message}")
    print()


def make_progress_printer():
    def _print(index: int, total: int, result: FileResult) -> None:
        counter = f"[{index:>{len(str(total))}}/{total}]"
        name = result.file_name if len(result.file_name) <= 34 else result.file_name[:31] + "..."
        label = STATUS_LABELS.get(result.status, result.status.upper())
        if result.status in ("skipped", "failed"):
            detail = result.message
        else:
            detail = f"{result.pages} page(s), {result.ocr_pages} OCR, {result.seconds:.2f}s"
        print(f"  {counter} {name:<34} {label:<8} {detail}", flush=True)
        if result.status == "partial" and result.message:
            print(f"  {' ' * len(counter)} note: {result.message}", flush=True)
    return _print


def cmd_process(args: argparse.Namespace, db: Database) -> int:
    input_dir = Path(args.input)
    if not input_dir.is_dir():
        print(f"ERROR: input folder not found: {input_dir.resolve()}", file=sys.stderr)
        return 2

    print(f"  Input    : {input_dir.resolve()}{' (recursive)' if args.recursive else ''}"
          f"{' | FORCE re-processing' if args.force else ''}\n")
    summary = process_folder(
        input_dir, force=args.force, recursive=args.recursive,
        progress_callback=make_progress_printer(), db=db,
    )
    if summary.files_found == 0:
        print("  No PDF files found.")

    print("\n  Summary")
    print(_table([
        ("Files found", summary.files_found),
        ("Processed", f"{summary.processed}" + (f"  ({summary.partial} partial)" if summary.partial else "")),
        ("Skipped (already in DB)", summary.skipped),
        ("Failed", summary.failed),
        ("Pages extracted", summary.total_pages),
        ("Pages via OCR", summary.ocr_pages),
        ("Time taken", f"{summary.seconds:.2f}s"),
    ]))
    print("  Log file: output/pipeline.log")
    return 1 if summary.failed else 0


def cmd_stats(db: Database) -> int:
    stats = db.stats()
    print("  Database statistics")
    print(_table([
        ("Documents", stats["documents"]),
        ("  success", stats["success"]),
        ("  partial", stats["partial"]),
        ("  failed", stats["failed"]),
        ("Pages", stats["pages"]),
        ("Pages via OCR", stats["ocr_pages"]),
        ("Avg OCR confidence", f"{stats['avg_ocr_confidence']}%" if stats["avg_ocr_confidence"] is not None else "-"),
        ("Characters stored", f"{stats['characters']:,}"),
    ]))
    docs = db.documents_df()
    if not docs.empty:
        print("\n  Documents")
        print(f"  {'ID':>4}  {'File':<34} {'Status':<8} {'Pages':>5} {'OCR':>4}  Processed (UTC)")
        print(f"  {_rule('-', 78)}")
        for row in docs.itertuples():
            processed = str(row.processed_at)[:19]
            print(f"  {row.id:>4}  {row.file_name[:34]:<34} {row.status:<8} {row.page_count:>5} "
                  f"{row.ocr_page_count:>4}  {processed}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract the text of every page of a folder of PDFs into an SQL database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:" + __doc__.split("Examples:", 1)[1],
    )
    parser.add_argument("--input", default="sample_pdfs", help="folder containing PDFs (default: sample_pdfs)")
    parser.add_argument("--db", help="database URL; overrides DATABASE_URL from .env")
    parser.add_argument("--force", action="store_true", help="re-process files that are already in the database")
    parser.add_argument("--recursive", action="store_true", help="also process PDFs in sub-folders")
    parser.add_argument("--export-csv", metavar="PATH", help="export all extracted pages to a CSV file")
    parser.add_argument("--export-xlsx", metavar="PATH",
                        help="export pages and documents to an Excel workbook (.xlsx)")
    parser.add_argument("--stats", action="store_true", help="show database statistics and exit (no processing)")
    parser.add_argument("--write-schema", action="store_true", help="regenerate schema.sql and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed log messages on the console")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    # The progress lines below are the normal console output; -v adds the full log.
    setup_logging(console_level=logging.INFO if args.verbose else logging.CRITICAL + 1)

    if args.write_schema:
        print(f"Schema written to {generate_schema_sql()}")
        return 0

    try:
        db = Database(args.db or settings.database_url)
    except Exception as exc:
        print(f"ERROR: cannot connect to the database: {exc}", file=sys.stderr)
        return 2

    print_header(db)
    code = cmd_stats(db) if args.stats else cmd_process(args, db)

    exports = [(args.export_csv, db.export_csv, "CSV"), (args.export_xlsx, db.export_xlsx, "Excel")]
    for target, export, label in exports:
        if not target:
            continue
        try:
            rows = export(target)
        except PermissionError:
            print(f"\n  ERROR: cannot write {target} - is it open in Excel? Close it and try again.",
                  file=sys.stderr)
            code = code or 1
            continue
        print(f"\n  Exported {rows} page(s) to {label}: {Path(target).resolve()}")
    return code


if __name__ == "__main__":
    sys.exit(main())
