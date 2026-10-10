"""Generate three demo PDFs in sample_pdfs/ (all content is original, generated here).

    digital_report.pdf   3 pages with a normal text layer
    scanned_invoice.pdf  1 page that is only an image (no text layer) -> needs OCR
    mixed_document.pdf   1 text page + 1 image-only page
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sample_pdfs"

A4 = pymupdf.paper_rect("a4")
MARGIN = 56


def add_text_page(doc: pymupdf.Document, title: str, paragraphs: list[str]) -> None:
    page = doc.new_page(width=A4.width, height=A4.height)
    page.insert_text((MARGIN, MARGIN + 20), title, fontsize=18, fontname="helv")
    body = pymupdf.Rect(MARGIN, MARGIN + 45, A4.width - MARGIN, A4.height - MARGIN)
    page.insert_textbox(body, "\n\n".join(paragraphs), fontsize=11, fontname="helv", lineheight=1.35)
    page.insert_text((MARGIN, A4.height - 30), f"Page {page.number + 1}", fontsize=8, fontname="helv")


def add_scanned_page(doc: pymupdf.Document, title: str, lines: list[str], dpi: int = 150) -> None:
    """Lay out text on a scratch page, rasterise it, and insert only the image (simulated scan)."""
    scratch = pymupdf.open()
    tmp = scratch.new_page(width=A4.width, height=A4.height)
    tmp.insert_text((MARGIN, MARGIN + 20), title, fontsize=18, fontname="cour")
    y = MARGIN + 60
    for line in lines:
        tmp.insert_text((MARGIN, y), line, fontsize=12, fontname="cour")
        y += 22
    # A modest-resolution greyscale render, like a typical office scanner.
    pix = tmp.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    scratch.close()

    page = doc.new_page(width=A4.width, height=A4.height)
    page.insert_image(page.rect, pixmap=pix)


def make_digital_report(path: Path) -> None:
    doc = pymupdf.open()
    add_text_page(doc, "Quarterly Operations Report - Q3", [
        "Executive summary. Northwind Logistics processed 18,420 shipments during the third quarter, "
        "an increase of 12 percent compared with the previous quarter. On-time delivery reached 96.4 percent.",
        "The expansion of the Riverside warehouse was completed in August and added 4,000 square metres "
        "of storage capacity. Average order handling time fell from 41 to 33 minutes.",
        "Key risks for the next quarter are fuel price volatility and the planned migration of the "
        "order management system, scheduled for November.",
    ])
    add_text_page(doc, "Financial Overview", [
        "Revenue for the quarter was 2.84 million EUR against a budget of 2.70 million EUR. "
        "Operating costs were 2.31 million EUR, giving an operating margin of 18.7 percent.",
        "Transport costs represented 46 percent of operating costs. Staff costs rose by 3 percent "
        "following the seasonal hiring programme in July.",
        "Capital expenditure totalled 410,000 EUR, mainly for racking, two electric forklifts and "
        "warehouse scanning equipment.",
    ])
    add_text_page(doc, "Outlook and Recommendations", [
        "Volume is expected to grow a further 8 to 10 percent in Q4 due to the holiday season. "
        "Temporary staff should be contracted by mid-October.",
        "Recommendation 1: renegotiate the fuel surcharge clause with the two largest carriers.",
        "Recommendation 2: run the order management migration in a pilot region before full rollout.",
        "Recommendation 3: publish a monthly service dashboard for the five largest customers.",
    ])
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def make_scanned_invoice(path: Path) -> None:
    doc = pymupdf.open()
    add_scanned_page(doc, "INVOICE  INV-2024-0117", [
        "Bill to: Harbor Street Bakery",
        "         12 Harbor Street, Portsmouth",
        "Date:    15 March 2024",
        "Due:     14 April 2024",
        "",
        "Description                  Qty    Amount",
        "Flour delivery 25kg bags      40    680.00",
        "Yeast cartons                 12    144.00",
        "Delivery fee                   1     35.00",
        "",
        "Subtotal                            859.00",
        "VAT 20%                             171.80",
        "TOTAL DUE                         1,030.80",
        "",
        "Payment by bank transfer. Thank you for your business.",
    ])
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def make_mixed_document(path: Path) -> None:
    doc = pymupdf.open()
    add_text_page(doc, "Service Agreement Summary", [
        "This summary describes the maintenance agreement between Brightline Facilities and "
        "Oakridge Medical Centre for the period January to December.",
        "Brightline Facilities will inspect heating, ventilation and air conditioning equipment every "
        "month and respond to urgent faults within four hours.",
        "The signed acknowledgement form is attached on the next page as a scanned image.",
    ])
    add_scanned_page(doc, "ACKNOWLEDGEMENT FORM", [
        "I confirm that I have read the service agreement",
        "and accept its terms on behalf of the client.",
        "",
        "Name:      Dana Whitfield",
        "Position:  Operations Manager",
        "Date:      8 January 2024",
        "",
        "Signature: ____________________",
    ])
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    builders = {
        "digital_report.pdf": make_digital_report,
        "scanned_invoice.pdf": make_scanned_invoice,
        "mixed_document.pdf": make_mixed_document,
    }
    for name, build in builders.items():
        target = OUT_DIR / name
        build(target)
        with pymupdf.open(target) as doc:
            text_chars = sum(len(p.get_text().strip()) for p in doc)
            print(f"  created {target.relative_to(ROOT)}  ({doc.page_count} page(s), "
                  f"{text_chars} chars in text layer, {target.stat().st_size / 1024:.0f} KB)")
    print(f"Done: {len(builders)} sample PDFs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
