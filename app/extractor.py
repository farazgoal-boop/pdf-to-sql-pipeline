"""Per-page text extraction from PDFs, with Tesseract OCR fallback for scanned pages."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf
from PIL import Image

from app.config import Settings, settings as default_settings

logger = logging.getLogger("pdf_pipeline")

TESSERACT_DOWNLOAD_URL = "https://github.com/UB-Mannheim/tesseract/wiki"

# Native text flags: keep whitespace, clip to the page, expand ligatures (ﬁ -> fi)
# and join words hyphenated across line breaks.
_TEXT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_DEHYPHENATE
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_SPACE = re.compile(r"[ \t  -​  　]+")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


class ExtractionError(Exception):
    """A PDF could not be read at all (corrupt, encrypted, empty...)."""


@dataclass
class PageResult:
    page_number: int  # 1-based
    text: str
    method: str  # "text", "ocr" or "error"
    char_count: int
    ocr_confidence: float | None = None
    warning: str | None = None


@dataclass
class DocumentResult:
    path: Path
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for p in self.pages if p.method == "ocr")


@dataclass(frozen=True)
class OcrStatus:
    available: bool
    version: str | None
    command: str | None
    message: str


def clean_text(text: str) -> str:
    """Normalise whitespace while keeping paragraph breaks (blank lines)."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = _CONTROL_CHARS.sub("", text)  # includes NUL
    text = text.replace("­", "")  # soft hyphen
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return _EXTRA_BLANK_LINES.sub("\n\n", text).strip()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=8)
def check_ocr(tesseract_cmd: str | None, lang: str = "eng") -> OcrStatus:
    """Check that Tesseract and the requested language data are installed."""
    try:
        import pytesseract
    except ImportError:
        return OcrStatus(False, None, tesseract_cmd, "pytesseract is not installed (pip install pytesseract).")

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        version = str(pytesseract.get_tesseract_version()).splitlines()[0]
    except Exception:  # TesseractNotFoundError, OSError, ...
        return OcrStatus(
            False,
            None,
            tesseract_cmd,
            "Tesseract OCR was not found. Scanned pages will be stored without OCR text. "
            f"Install it from {TESSERACT_DOWNLOAD_URL} or set TESSERACT_CMD in .env.",
        )

    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception:
        installed = set()
    missing = [code for code in lang.split("+") if installed and code not in installed]
    if missing:
        return OcrStatus(
            False,
            version,
            tesseract_cmd,
            f"Tesseract {version} is installed but language data is missing for: {', '.join(missing)}. "
            "Re-run the Tesseract installer and tick the extra languages, or change OCR_LANG.",
        )
    return OcrStatus(True, version, tesseract_cmd, f"Tesseract {version} ready (lang: {lang}).")


def _native_text(page: pymupdf.Page) -> str:
    """Text-layer extraction in reading order, one paragraph per text block."""
    blocks = page.get_text("blocks", flags=_TEXT_FLAGS, sort=True)
    paragraphs = [clean_text(b[4]) for b in blocks if b[6] == 0]
    return "\n\n".join(p for p in paragraphs if p)


def _ocr_page(page: pymupdf.Page, cfg: Settings) -> tuple[str, float | None]:
    """Render the page to an image and OCR it. Returns (text, mean word confidence)."""
    import pytesseract

    pix = page.get_pixmap(dpi=cfg.ocr_dpi, colorspace=pymupdf.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    data = pytesseract.image_to_data(image, lang=cfg.ocr_lang, output_type=pytesseract.Output.DICT)

    # Rebuild the text from Tesseract's block/paragraph/line structure so that
    # paragraph breaks survive; collect word confidences along the way.
    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        conf = float(data["conf"][i])
        if conf >= 0:
            confidences.append(conf)
        para_key = (data["block_num"][i], data["par_num"][i])
        paragraphs.setdefault(para_key, {}).setdefault(data["line_num"][i], []).append(word)

    text = "\n\n".join(
        "\n".join(" ".join(words) for _, words in sorted(lines.items()))
        for _, lines in sorted(paragraphs.items())
    )
    confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    return clean_text(text), confidence


def extract_pdf(path: str | Path, cfg: Settings | None = None) -> DocumentResult:
    """Extract the text of every page of a PDF.

    Raises ExtractionError if the file cannot be opened at all. Problems with
    individual pages are recorded on the page (method "error") instead of raising.
    """
    cfg = cfg or default_settings
    path = Path(path)

    try:
        doc = pymupdf.open(path, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ExtractionError(f"Corrupt or unreadable PDF: {exc}") from exc
    except Exception as exc:
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass and not doc.authenticate(""):
            raise ExtractionError("PDF is password-protected (encrypted); cannot extract text.")
        if doc.page_count == 0:
            raise ExtractionError("PDF contains no pages.")

        result = DocumentResult(path=path, page_count=doc.page_count)
        ocr = check_ocr(cfg.tesseract_cmd, cfg.ocr_lang)
        ocr_skipped = 0

        for index in range(doc.page_count):
            number = index + 1
            try:
                page = doc.load_page(index)
                text = _native_text(page)
            except Exception as exc:
                logger.warning("%s page %d: text extraction failed: %s", path.name, number, exc)
                result.pages.append(PageResult(number, "", "error", 0, warning=f"Page could not be read: {exc}"))
                continue

            page_result = PageResult(number, text, "text", len(text))
            if len(text) < cfg.ocr_min_chars:
                if not ocr.available:
                    ocr_skipped += 1
                    page_result.warning = "Page looks scanned but OCR is unavailable."
                else:
                    try:
                        ocr_text, confidence = _ocr_page(page, cfg)
                        if len(ocr_text) > len(text):
                            page_result = PageResult(number, ocr_text, "ocr", len(ocr_text), confidence)
                    except Exception as exc:
                        logger.warning("%s page %d: OCR failed: %s", path.name, number, exc)
                        page_result.warning = f"OCR failed: {exc}"
            result.pages.append(page_result)

        if ocr_skipped:
            result.warnings.append(f"{ocr_skipped} page(s) need OCR but it is unavailable: {ocr.message}")
        errors = [p for p in result.pages if p.method == "error" or (p.warning and "OCR failed" in p.warning)]
        if errors:
            result.warnings.append(f"{len(errors)} page(s) had extraction errors.")
        return result
