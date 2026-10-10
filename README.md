# PDF → SQL Extractor

**Turn a folder of unstructured PDFs — digital or scanned — into clean, queryable rows in PostgreSQL, MySQL or SQLite with one command.**

Every page of every PDF becomes one database row holding the file name, page number and clean plain text. Pages without a text layer (scans, photos, faxes) are detected automatically and read with OCR. The workflow is repeatable: drop new PDFs in the folder, run the same command again, and only the new files are processed.

---

## Features

- **All text, every page** – native text extraction with PyMuPDF, in reading order, paragraph breaks preserved.
- **Automatic OCR fallback** – pages with little or no text layer are rendered at 300 DPI and read with Tesseract; the OCR confidence is stored per page.
- **Clean plain text** – no layout, fonts or styling; whitespace normalised, NUL/control characters removed, ligatures expanded, hyphenated line breaks joined.
- **Any SQL database** – SQLite out of the box; PostgreSQL and MySQL/MariaDB by changing one line. Tables are created automatically.
- **Repeatable and safe to re-run** – files are identified by SHA-256 hash, so already-imported files (even renamed copies) are skipped; `--force` re-imports them.
- **Robust batches** – each PDF is saved in its own transaction. Corrupt, password-protected or empty PDFs are recorded as `failed` with a reason and the batch carries on.
- **Command-line tool and web UI** – a scriptable CLI for scheduled jobs, and a Streamlit dashboard to upload files, browse pages, search the full text and download Excel or CSV.
- **Logging and exports** – console output plus `output/pipeline.log`; Excel (.xlsx) export with wrapped text and a frozen header row, and UTF-8 CSV that opens cleanly in Excel.
- **Tested** – automated tests cover text extraction, OCR, duplicates, force re-processing and corrupt files.

## How it works

```mermaid
flowchart LR
    A[PDF folder<br/>or upload] --> B[Pipeline<br/>app/pipeline.py]
    B -->|SHA-256 already stored?| S[Skip]
    B --> C[Extractor<br/>app/extractor.py]
    C --> D{Text layer<br/>≥ OCR_MIN_CHARS?}
    D -->|yes| E[Native text<br/>PyMuPDF]
    D -->|no| F[Render page 300 DPI<br/>Tesseract OCR]
    E --> G[Clean text]
    F --> G
    G --> H[(SQL database<br/>documents + pages)]
    H --> I[CLI stats / Excel + CSV export]
    H --> J[Streamlit UI<br/>browse · search · download]
    H --> K[Your SQL queries / BI tools]
```

| File | Purpose |
|---|---|
| `run.py` | Command-line entry point |
| `app/config.py` | Settings from `.env` with safe defaults |
| `app/extractor.py` | Per-page text extraction + OCR fallback + text cleaning |
| `app/database.py` | SQLAlchemy models, queries, Excel/CSV export, `schema.sql` generator |
| `app/pipeline.py` | Batch processing, duplicate detection, logging, summary |
| `ui/streamlit_app.py` | Web dashboard |
| `scripts/make_samples.py` | Generates three demo PDFs (digital, scanned, mixed) |
| `tests/test_pipeline.py` | Automated tests |
| `schema.sql` | Table definitions for PostgreSQL and MySQL (reference) |

---

## Setup on Windows (step by step)

**1. Install Python 3.11 or newer** from <https://www.python.org/downloads/windows/>. On the first installer screen tick **"Add python.exe to PATH"**.

**2. Install Tesseract OCR** (needed only for scanned pages) from the UB Mannheim builds:
<https://github.com/UB-Mannheim/tesseract/wiki>
Install to the default folder `C:\Program Files\Tesseract-OCR\` — the tool finds it there automatically. To OCR other languages, tick them under *Additional language data* during installation.

**3. Get the code and open PowerShell in the project folder**

```powershell
git clone https://github.com/farazgoal-boop/pdf-to-sql-pipeline.git
cd pdf-to-sql-pipeline
```

(Or download the ZIP from <https://github.com/farazgoal-boop/pdf-to-sql-pipeline>, extract it, and open PowerShell in that folder.)

**4. Create and activate a virtual environment**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

> If PowerShell blocks the script, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**5. Install the Python packages**

```powershell
pip install -r requirements.txt
```

**6. (Optional) Configure** – copy the example settings and edit them:

```powershell
copy .env.example .env
notepad .env
```

Without a `.env` file the tool uses a local SQLite database at `output\pdf_data.db`.

**7. Check everything works**

```powershell
python scripts\make_samples.py     # creates 3 demo PDFs in sample_pdfs\
python run.py                      # imports them
python run.py --stats              # shows what is in the database
```

---

## Usage

### Command line

```powershell
# Process every PDF in a folder (default folder: sample_pdfs)
python run.py --input "D:\Client PDFs"

# Include sub-folders
python run.py --input "D:\Client PDFs" --recursive

# Re-process files that are already in the database (replaces their records)
python run.py --input "D:\Client PDFs" --force

# Write to a specific database for this run (overrides DATABASE_URL)
python run.py --input "D:\Client PDFs" --db "postgresql+psycopg2://pdf_user:secret@localhost:5432/pdf_data"

# Export every page to CSV after processing
python run.py --input "D:\Client PDFs" --export-csv output\pages.csv

# Export to Excel without processing anything (sheets: Pages, Documents)
python run.py --stats --export-xlsx output\pdf_data.xlsx

# Show database statistics only (no processing)
python run.py --stats

# Show the detailed log on screen as well
python run.py --input "D:\Client PDFs" -v
```

Running the same command again later only processes **new** PDFs. The exit code is `0` on success and `1` if any file failed, so the command can be used in Windows Task Scheduler or other automation.

### Web UI

```powershell
streamlit run ui/streamlit_app.py
```

Then open <http://localhost:8501>. From the dashboard you can:

- upload PDFs and extract them to the database with a progress bar,
- process the whole `sample_pdfs` folder from the sidebar,
- see totals (documents, pages, OCR pages, failures) and every document's status,
- open any page and read its extracted text, extraction method and OCR confidence,
- search the full text of all pages with highlighted matches,
- download everything as an Excel workbook, or pages and documents as CSV.

The sidebar shows which database is in use (passwords are masked) and whether Tesseract was found.

---

## Using PostgreSQL or MySQL

Create an empty database, then set `DATABASE_URL` in `.env` (or pass `--db`). The tables are created automatically on the first run.

| Database | Example `DATABASE_URL` |
|---|---|
| SQLite (default) | `sqlite:///output/pdf_data.db` |
| PostgreSQL | `postgresql+psycopg2://pdf_user:your_password@localhost:5432/pdf_data` |
| MySQL / MariaDB | `mysql+pymysql://pdf_user:your_password@localhost:3306/pdf_data?charset=utf8mb4` |

PostgreSQL example setup:

```sql
CREATE DATABASE pdf_data;
CREATE USER pdf_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE pdf_data TO pdf_user;
-- PostgreSQL 15+: also run inside pdf_data:  GRANT ALL ON SCHEMA public TO pdf_user;
```

MySQL example setup:

```sql
CREATE DATABASE pdf_data CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'pdf_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON pdf_data.* TO 'pdf_user'@'localhost';
```

> If the password contains special characters such as `@ : / #`, URL-encode them (`@` → `%40`).

---

## Database schema

Two tables: one row per PDF in `documents`, one row per page in `pages`. The full DDL for PostgreSQL and MySQL is in [`schema.sql`](schema.sql) (regenerate with `python run.py --write-schema`).

**`documents`**

| Column | Type | Description |
|---|---|---|
| `id` | integer, PK | |
| `file_name` | varchar(255) | File name, e.g. `invoice_0117.pdf` |
| `file_path` | varchar(1024) | Full path at the time of import |
| `file_hash` | varchar(64), unique | SHA-256 of the file – used to skip duplicates |
| `page_count` | integer | Number of pages |
| `ocr_page_count` | integer | Pages that were read with OCR |
| `status` | varchar(16) | `success`, `partial` (some pages had problems) or `failed` |
| `error_message` | text | Reason for `partial` / `failed` |
| `processed_at` | timestamp (UTC) | When the file was imported |

**`pages`**

| Column | Type | Description |
|---|---|---|
| `id` | integer, PK | |
| `document_id` | integer, FK → `documents.id` (ON DELETE CASCADE) | |
| `page_number` | integer | 1-based; unique together with `document_id` |
| `text` | TEXT (LONGTEXT on MySQL) | Clean plain text of the page |
| `extraction_method` | varchar(8) | `text` (text layer), `ocr`, or `error` |
| `char_count` | integer | Length of `text` |
| `ocr_confidence` | float | Average Tesseract word confidence 0–100 (OCR pages only) |

### Example queries

```sql
-- 1. Full text of one document, page by page
SELECT p.page_number, p.text
FROM pages p JOIN documents d ON d.id = p.document_id
WHERE d.file_name = 'digital_report.pdf'
ORDER BY p.page_number;

-- 2. Find every page that mentions a word (case-insensitive on all databases)
SELECT d.file_name, p.page_number
FROM pages p JOIN documents d ON d.id = p.document_id
WHERE LOWER(p.text) LIKE '%invoice%'
ORDER BY d.file_name, p.page_number;

-- 3. Scanned pages with low OCR confidence that may need a manual check
SELECT d.file_name, p.page_number, p.ocr_confidence
FROM pages p JOIN documents d ON d.id = p.document_id
WHERE p.extraction_method = 'ocr' AND p.ocr_confidence < 80
ORDER BY p.ocr_confidence;

-- 4. Files that could not be fully processed, and why
SELECT file_name, status, error_message, processed_at
FROM documents
WHERE status <> 'success'
ORDER BY processed_at DESC;

-- 5. Per-document totals
SELECT d.file_name, d.page_count, d.ocr_page_count, SUM(p.char_count) AS characters
FROM documents d LEFT JOIN pages p ON p.document_id = d.id
GROUP BY d.id, d.file_name, d.page_count, d.ocr_page_count
ORDER BY characters DESC;
```

---

## Configuration

All settings are optional and live in `.env` (see [`.env.example`](.env.example)):

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///output/pdf_data.db` | Where to store the data |
| `TESSERACT_CMD` | auto-detect | Path to `tesseract.exe` if not in the default folder or on PATH |
| `OCR_LANG` | `eng` | Tesseract language(s), e.g. `eng+deu` |
| `OCR_MIN_CHARS` | `25` | Pages with fewer text-layer characters than this are OCR'd |
| `OCR_DPI` | `300` | Render resolution for OCR |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `OCR : NOT AVAILABLE` / "Tesseract OCR was not found" | Install Tesseract from the link above, or set `TESSERACT_CMD` in `.env` to the full path of `tesseract.exe`. Text PDFs are still processed; scanned pages are stored as `partial` until OCR is available – re-run with `--force` afterwards. |
| "language data is missing" | Re-run the Tesseract installer and tick the language, or change `OCR_LANG`. |
| A file shows `failed` – "password-protected" | Remove the password (e.g. *Print → Save as PDF*) and run again. |
| A file shows `failed` – "Corrupt or unreadable PDF" | The file is damaged or is not really a PDF. Re-download or re-export it. |
| My files were "skipped" | They are already in the database (same content). Use `--force` to re-import. |
| OCR text has mistakes | Scan at 300 DPI or higher; try `OCR_DPI=400`. Check `ocr_confidence` to find weak pages. |
| `could not connect to server` / `Access denied` | Check host, port, user, password and database name in `DATABASE_URL`, and that the database exists. |
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. |
| Strange characters in MySQL | Make sure the URL ends with `?charset=utf8mb4` and the database uses `utf8mb4`. |

Detailed logs are written to `output\pipeline.log`.

---

## Running the tests

```powershell
python -m pytest -q
```

Tests use a temporary SQLite database and generated PDFs; OCR tests are skipped automatically if Tesseract is not installed.

## Screenshots

Screenshots of the dashboard go in [`docs/screenshots/`](docs/screenshots/).

<!--
![Dashboard](docs/screenshots/dashboard.png)
![Page viewer](docs/screenshots/page_viewer.png)
![Search](docs/screenshots/search.png)
-->

## Known limitations

- OCR quality depends on scan quality; handwriting is not reliably recognised.
- A page that has *some* text layer (above `OCR_MIN_CHARS`) plus a scanned image is treated as a text page, so the image part is not OCR'd. Raise `OCR_MIN_CHARS` if your documents look like this.
- Tables are extracted as plain text lines, not as structured rows and columns.
- Password-protected PDFs are recorded as failed rather than unlocked.
- Excel cells hold at most 32,767 characters, so an exceptionally long page is shortened in the `.xlsx` export (marked as truncated). The database and CSV always contain the full text.

---

**Author:** Faraz — Faraz Automation
**License:** [MIT](LICENSE)
