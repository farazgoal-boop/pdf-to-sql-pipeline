-- PDF -> SQL Extractor: database schema
-- Generated from app/database.py (SQLAlchemy models). The pipeline creates these
-- tables automatically; this file is for reference or manual setup.

-- ======================================================================
-- PostgreSQL
-- ======================================================================

CREATE TABLE documents (
	id SERIAL NOT NULL,
	file_name VARCHAR(255) NOT NULL,
	file_path VARCHAR(1024) NOT NULL,
	file_hash VARCHAR(64) NOT NULL,
	page_count INTEGER NOT NULL,
	ocr_page_count INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	error_message TEXT,
	processed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (file_hash)
);

CREATE INDEX ix_documents_file_name ON documents (file_name);

CREATE TABLE pages (
	id SERIAL NOT NULL,
	document_id INTEGER NOT NULL,
	page_number INTEGER NOT NULL,
	text TEXT NOT NULL,
	extraction_method VARCHAR(8) NOT NULL,
	char_count INTEGER NOT NULL,
	ocr_confidence FLOAT,
	PRIMARY KEY (id),
	CONSTRAINT uq_pages_document_page UNIQUE (document_id, page_number),
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

-- ======================================================================
-- MySQL / MariaDB (utf8mb4)
-- ======================================================================

CREATE TABLE documents (
	id INTEGER NOT NULL AUTO_INCREMENT,
	file_name VARCHAR(255) NOT NULL,
	file_path VARCHAR(1024) NOT NULL,
	file_hash VARCHAR(64) NOT NULL,
	page_count INTEGER NOT NULL,
	ocr_page_count INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	error_message TEXT,
	processed_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (file_hash)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_documents_file_name ON documents (file_name);

CREATE TABLE pages (
	id INTEGER NOT NULL AUTO_INCREMENT,
	document_id INTEGER NOT NULL,
	page_number INTEGER NOT NULL,
	text LONGTEXT NOT NULL,
	extraction_method VARCHAR(8) NOT NULL,
	char_count INTEGER NOT NULL,
	ocr_confidence FLOAT,
	PRIMARY KEY (id),
	CONSTRAINT uq_pages_document_page UNIQUE (document_id, page_number),
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
