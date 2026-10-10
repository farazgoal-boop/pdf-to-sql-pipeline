"""Application settings, loaded from environment variables / a .env file."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
LOG_FILE = OUTPUT_DIR / "pipeline.log"
SAMPLE_DIR = PROJECT_ROOT / "sample_pdfs"

WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

load_dotenv(PROJECT_ROOT / ".env")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _default_database_url() -> str:
    # Absolute path so the DB location doesn't depend on the working directory.
    return f"sqlite:///{(OUTPUT_DIR / 'pdf_data.db').as_posix()}"


def _detect_tesseract() -> str | None:
    """Return the Tesseract executable: TESSERACT_CMD, the default Windows install, or PATH."""
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured:
        return configured
    if WINDOWS_TESSERACT.exists():
        return str(WINDOWS_TESSERACT)
    return shutil.which("tesseract")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Setting {name} must be an integer, got {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    database_url: str
    tesseract_cmd: str | None
    ocr_lang: str
    ocr_min_chars: int
    ocr_dpi: int


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "").strip() or _default_database_url(),
        tesseract_cmd=_detect_tesseract(),
        ocr_lang=os.getenv("OCR_LANG", "").strip() or "eng",
        ocr_min_chars=_int_env("OCR_MIN_CHARS", 25),
        ocr_dpi=_int_env("OCR_DPI", 300),
    )


settings = load_settings()
