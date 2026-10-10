"""Streamlit demo UI for the PDF -> SQL pipeline.

Run from the project root:
    streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # make the `app` package importable when launched by Streamlit
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.config import OUTPUT_DIR, SAMPLE_DIR, settings  # noqa: E402
from app.database import Database, to_csv_bytes, to_xlsx_bytes  # noqa: E402
from app.extractor import check_ocr  # noqa: E402
from app.pipeline import PipelineSummary, find_pdfs, process_files, setup_logging  # noqa: E402

UPLOAD_DIR = OUTPUT_DIR / "uploads"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

STATUS_STYLE = {
    "success": "background-color: #e6f4ea; color: #1e6b34; font-weight: 600;",
    "partial": "background-color: #fff4e0; color: #8a5300; font-weight: 600;",
    "failed": "background-color: #fde8e8; color: #a12020; font-weight: 600;",
}
STATUS_BADGE = {"success": "green", "partial": "orange", "failed": "red"}
METHOD_LABEL = {"text": "Native text", "ocr": "OCR", "error": "Error"}

st.set_page_config(page_title="PDF → SQL Extractor", page_icon="📄", layout="wide")
st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1280px; }
      [data-testid="stMetricValue"] { font-size: 1.9rem; }
      .hit { padding: 0.35rem 0 0.15rem; line-height: 1.55; font-size: 0.93rem; }
      .hit mark { background: #ffe58a; padding: 0 2px; border-radius: 3px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_db(url: str) -> Database:
    setup_logging()
    return Database(url)


db = get_db(settings.database_url)
ocr = check_ocr(settings.tesseract_cmd, settings.ocr_lang)


def run_batch(paths: list[Path], force: bool, container) -> PipelineSummary:
    """Process files with a live progress bar inside `container`."""
    with container:
        bar = st.progress(0.0, text=f"Processing {len(paths)} file(s)…")

        def on_progress(index: int, total: int, result) -> None:
            bar.progress(index / total, text=f"{index}/{total} · {result.file_name} → {result.status}")

        summary = process_files(paths, force=force, progress_callback=on_progress, db=db)
        bar.empty()
    st.session_state["last_summary"] = summary
    return summary


def show_summary(summary: PipelineSummary) -> None:
    msg = (
        f"**{summary.processed}** processed · **{summary.skipped}** skipped · "
        f"**{summary.failed}** failed · {summary.total_pages} pages ({summary.ocr_pages} via OCR) "
        f"in {summary.seconds:.1f}s"
    )
    (st.warning if summary.failed else st.success)(msg, icon="✅" if not summary.failed else "⚠️")
    if summary.results:
        df = pd.DataFrame(
            [{"File": r.file_name, "Result": r.status, "Pages": r.pages, "OCR pages": r.ocr_pages,
              "Note": r.message} for r in summary.results]
        )
        st.dataframe(df, hide_index=True, width="stretch")


def _mark(segment: str, pattern: re.Pattern) -> str:
    out, pos = [], 0
    for m in pattern.finditer(segment):
        out.append(html.escape(segment[pos:m.start()]))
        out.append(f"<mark>{html.escape(m.group(0))}</mark>")
        pos = m.end()
    out.append(html.escape(segment[pos:]))
    return "".join(out)


def highlight(text: str, term: str, context: int = 90, max_snippets: int = 3) -> tuple[str, int]:
    """Return HTML snippets around the matches with <mark> highlighting, plus the match count."""
    pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
    matches = list(pattern.finditer(text))
    windows: list[list[int]] = []
    for m in matches:
        start, end = max(0, m.start() - context), min(len(text), m.end() + context)
        if windows and start <= windows[-1][1]:
            windows[-1][1] = end  # merge overlapping snippets
        else:
            windows.append([start, end])
    snippets = [
        ("… " if start > 0 else "") + _mark(text[start:end], pattern) + (" …" if end < len(text) else "")
        for start, end in windows[:max_snippets]
    ]
    return "<br>".join(s.replace("\n", " ") for s in snippets), len(matches)


# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### 📄 PDF → SQL Extractor")
    st.caption("Extract every page of your PDFs into a queryable SQL database.")

    st.markdown("#### Database")
    st.markdown(f"**Type:** `{db.backend}`")
    st.markdown("**Location:**")
    st.code(db.display_location, language=None, wrap_lines=True)  # passwords are masked

    st.markdown("#### OCR engine")
    if ocr.available:
        st.success(f"Tesseract {ocr.version}", icon="✅")
        st.caption(f"Language `{settings.ocr_lang}` · {settings.ocr_dpi} DPI · "
                   f"OCR if page has < {settings.ocr_min_chars} chars")
    else:
        st.error("Tesseract not available", icon="⚠️")
        st.caption(ocr.message)

    st.markdown("#### Batch")
    force = st.toggle("Re-process files already in DB", value=False,
                      help="By default, files whose SHA-256 hash is already stored are skipped.")
    sample_files = find_pdfs(SAMPLE_DIR) if SAMPLE_DIR.is_dir() else []
    sidebar_status = st.container()
    if st.button("Process sample_pdfs folder", type="primary", width="stretch", disabled=not sample_files):
        run_batch(sample_files, force, sidebar_status)
    if not sample_files:
        st.caption("No PDFs in `sample_pdfs/`. Run `python scripts/make_samples.py` to create demo files.")
    else:
        st.caption(f"{len(sample_files)} PDF(s) in `sample_pdfs/`")


# --------------------------------------------------------------------------- main
st.title("PDF → SQL Extractor")
st.caption("Native text extraction with automatic OCR fallback for scanned pages · "
           "one row per page · SQLite, PostgreSQL or MySQL")

with st.container(border=True):
    st.markdown("##### Upload PDFs")
    uploads = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True,
                               label_visibility="collapsed")
    progress_area = st.container()
    if st.button("Extract to database", type="primary", disabled=not uploads):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for upload in uploads:
            target = UPLOAD_DIR / Path(upload.name).name
            target.write_bytes(upload.getbuffer())
            saved.append(target)
        run_batch(saved, force, progress_area)

if "last_summary" in st.session_state:
    with st.expander("Last run", expanded=True):
        show_summary(st.session_state["last_summary"])

stats = db.stats()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents", stats["documents"], border=True)
c2.metric("Pages", stats["pages"], border=True)
c3.metric("OCR pages", stats["ocr_pages"], border=True,
          help=f"Average OCR confidence: {stats['avg_ocr_confidence']}%" if stats["avg_ocr_confidence"] else None)
c4.metric("Failed", stats["failed"], border=True)

if stats["documents"] == 0:
    st.info(
        "**Get started**\n\n"
        "1. Upload one or more PDFs above and click **Extract to database**, or\n"
        "2. Click **Process sample_pdfs folder** in the sidebar to load the demo files, or\n"
        "3. Run the CLI: `python run.py --input path\\to\\pdfs`\n\n"
        "Every page becomes one row in the `pages` table, linked to its file in `documents`.",
        icon="👋",
    )
    st.stop()

docs = db.documents_df()
tab_docs, tab_viewer, tab_search, tab_export = st.tabs(["Documents", "Page viewer", "Search", "Export"])

with tab_docs:
    table = docs[["id", "file_name", "status", "page_count", "ocr_page_count", "processed_at", "error_message"]].copy()
    table["error_message"] = table["error_message"].fillna("")  # blank instead of "None"
    styled = table.style.map(lambda v: STATUS_STYLE.get(v, ""), subset=["status"])
    st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "file_name": st.column_config.TextColumn("File", width="large"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "page_count": st.column_config.NumberColumn("Pages", width="small"),
            "ocr_page_count": st.column_config.NumberColumn("OCR pages", width="small"),
            "processed_at": st.column_config.DatetimeColumn("Processed (UTC)", format="YYYY-MM-DD HH:mm"),
            "error_message": st.column_config.TextColumn("Notes"),
        },
    )

with tab_viewer:
    options = docs["id"].tolist()
    names = dict(zip(docs["id"], docs["file_name"]))
    rows = docs.set_index("id")
    left, right = st.columns([3, 1])
    doc_id = left.selectbox("Document", options, format_func=lambda i: f"{names[i]}  ·  {rows.at[i, 'page_count']} page(s)")
    doc = rows.loc[doc_id]
    if doc["page_count"] == 0:
        st.badge(doc["status"], color=STATUS_BADGE.get(doc["status"], "gray"))
        st.error(doc["error_message"] or "No pages were extracted from this document.")
    else:
        page_number = right.selectbox("Page", list(range(1, int(doc["page_count"]) + 1)))
        page = db.get_page(int(doc_id), int(page_number))
        if page is None:
            st.warning("This page is not in the database.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Method", METHOD_LABEL.get(page.extraction_method, page.extraction_method))
            m2.metric("Characters", f"{page.char_count:,}")
            m3.metric("OCR confidence", f"{page.ocr_confidence:.1f}%" if page.ocr_confidence is not None else "—")
            with m4:
                st.caption("Document status")
                st.badge(doc["status"], color=STATUS_BADGE.get(doc["status"], "gray"))
            if doc["error_message"]:
                st.caption(f"Note: {doc['error_message']}")
            st.code(page.text or "(no text on this page)", language=None, wrap_lines=True, height=460)

with tab_search:
    term = st.text_input("Search all pages", placeholder="e.g. invoice, revenue, Harbor Street")
    if term.strip():
        hits = db.search(term, limit=200)
        st.caption(f"{len(hits)} matching page(s)" + (" (showing first 200)" if len(hits) == 200 else ""))
        for hit in hits:
            snippet, count = highlight(hit["text"], term.strip())
            with st.container(border=True):
                st.markdown(f"**{hit['file_name']}** · page {hit['page_number']} · "
                            f"{METHOD_LABEL.get(hit['extraction_method'], hit['extraction_method'])} · "
                            f"{count} match{'es' if count != 1 else ''}")
                st.html(f"<div class='hit'>{snippet}</div>")
        if not hits:
            st.info("No pages contain that text.")
    else:
        st.caption("Case-insensitive search across the text of every page. Works on SQLite, PostgreSQL and MySQL.")

with tab_export:
    st.markdown("Download the extracted data. Files are generated when you click.")
    # Callables are only run on click, so large exports don't slow down every page refresh.
    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "⬇ Excel workbook (.xlsx)",
            lambda: to_xlsx_bytes({"Pages": db.export_pages_df(), "Documents": db.export_documents_df()}),
            "pdf_data.xlsx", XLSX_MIME, width="stretch", type="primary",
        )
        st.caption("Two sheets (Pages, Documents) · wrapped text · frozen header row")
    with e2:
        st.download_button("⬇ All pages (CSV)", lambda: to_csv_bytes(db.export_pages_df()),
                           "pages.csv", "text/csv", width="stretch")
        st.caption(f"{stats['pages']} rows: file name, page number, method, confidence, text")
    with e3:
        st.download_button("⬇ Documents (CSV)", lambda: to_csv_bytes(db.export_documents_df()),
                           "documents.csv", "text/csv", width="stretch")
        st.caption(f"{stats['documents']} rows: one per PDF, with status and page counts")
    st.caption("CSV files are UTF-8 with BOM so Excel opens them correctly; times are UTC "
               "as YYYY-MM-DD HH:MM:SS. A page longer than 32,767 characters (Excel's cell limit) "
               "is shortened in the .xlsx only.")
