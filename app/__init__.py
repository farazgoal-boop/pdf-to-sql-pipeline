"""PDF → SQL extraction pipeline.

Extracts plain text from every page of a batch of PDFs (with OCR fallback for
scanned pages) and stores it in a relational database (SQLite, PostgreSQL or
MySQL) via SQLAlchemy.
"""

__version__ = "1.0.0"
