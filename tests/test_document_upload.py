import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import Course
from app.adapters.document_parser import PdfDocumentParser, PowerPointDocumentParser


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "rag-import"


class DocumentUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "document-upload.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.previous_database_url = os.environ.get("APP_DATABASE_URL")
        self.previous_embedding_enabled = os.environ.get("RAG_EMBEDDING_ENABLED")
        os.environ["APP_DATABASE_URL"] = self.database_url
        os.environ["RAG_EMBEDDING_ENABLED"] = "false"
        Base.metadata.create_all(get_engine(self.database_url))
        self.course_id = self._seed_course("Upload Course")

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        if self.previous_database_url is None:
            os.environ.pop("APP_DATABASE_URL", None)
        else:
            os.environ["APP_DATABASE_URL"] = self.previous_database_url
        if self.previous_embedding_enabled is None:
            os.environ.pop("RAG_EMBEDDING_ENABLED", None)
        else:
            os.environ["RAG_EMBEDDING_ENABLED"] = self.previous_embedding_enabled
        self.temp_dir.cleanup()

    def test_upload_text_markdown_pdf_docx_and_pptx_create_documents(self) -> None:
        with TestClient(create_app()) as client:
            cases = [
                ("note.txt", b"BFS queue and DFS stack upload text.", "text/plain", "plain_text", "text"),
                ("note.md", b"# BFS and DFS\nBFS queue, DFS stack.", "text/markdown", "markdown", "markdown"),
                (
                    "rag-import-bfs-dfs-test.pdf",
                    (SAMPLE_DIR / "rag-import-bfs-dfs-test.pdf").read_bytes(),
                    "application/pdf",
                    "pdf",
                    "pdf",
                ),
                (
                    "rag-import-bfs-dfs-test.docx",
                    (SAMPLE_DIR / "rag-import-bfs-dfs-test.docx").read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "docx",
                    "docx",
                ),
                (
                    "lecture.pptx",
                    _pptx_with_slide_texts(["Slide one: BFS", "Slide two: DFS"]),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "pptx",
                    "pptx",
                ),
            ]

            for filename, content, content_type, parser_name, source_type in cases:
                response = client.post(
                    f"/api/v1/courses/{self.course_id}/documents/upload",
                    files={"file": (filename, content, content_type)},
                    data={"title": filename},
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertGreaterEqual(payload["chunk_count"], 1)
                self.assertEqual(payload["document"]["parser_name"], parser_name)
                self.assertEqual(payload["document"]["source_type"], source_type)
                self.assertEqual(payload["document"]["file_name"], filename)
                self.assertEqual(payload["document"]["visibility"], "course")

    def test_upload_unsupported_and_oversized_files_return_400(self) -> None:
        with TestClient(create_app()) as client:
            unsupported = client.post(
                f"/api/v1/courses/{self.course_id}/documents/upload",
                files={"file": ("bad.exe", b"not a document", "application/octet-stream")},
            )
            self.assertEqual(unsupported.status_code, 400)
            self.assertIn("Unsupported document", unsupported.text)

            legacy_ppt = client.post(
                f"/api/v1/courses/{self.course_id}/documents/upload",
                files={"file": ("legacy.ppt", b"legacy binary presentation", "application/vnd.ms-powerpoint")},
            )
            self.assertEqual(legacy_ppt.status_code, 400)
            self.assertIn(".pptx", legacy_ppt.text)

            too_large = client.post(
                f"/api/v1/courses/{self.course_id}/documents/upload",
                files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
            )
            self.assertEqual(too_large.status_code, 400)
            self.assertIn("too large", too_large.text)

    def test_json_paste_ingestion_still_works(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post(
                f"/api/v1/courses/{self.course_id}/documents",
                json={
                    "title": "paste.md",
                    "source_type": "markdown",
                    "content": "# Paste path\nBFS queue and DFS stack.",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["document"]["source_type"], "markdown")

    def test_upload_scanned_pdf_uses_ocr_parser_result(self) -> None:
        with patch.object(PdfDocumentParser, "_ocr_scanned_pdf", return_value=["[Page 1]\nOCR recognized BFS"]):
            with TestClient(create_app()) as client:
                response = client.post(
                    f"/api/v1/courses/{self.course_id}/documents/upload",
                    files={"file": ("scan.pdf", _blank_pdf(), "application/pdf")},
                )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["document"]["parser_name"], "pdf")
        self.assertIn("OCR recognized BFS", response.json()["chunks"][0]["content"])

    def _seed_course(self, title: str) -> int:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title=title, description="docs", is_demo=False)
            session.add(course)
            session.commit()
            return course.id
        finally:
            session.close()


class DocumentParserTests(unittest.TestCase):
    def test_pptx_parser_orders_double_digit_slides_numerically(self) -> None:
        sections = PowerPointDocumentParser().parse_bytes(
            _pptx_with_slide_texts([f"Slide {index}" for index in range(1, 11)])
        )

        self.assertEqual(sections[1], "[Slide 2]\nSlide 2")
        self.assertEqual(sections[9], "[Slide 10]\nSlide 10")

    def test_scanned_pdf_uses_ocr_only_when_no_native_text_exists(self) -> None:
        parser = PdfDocumentParser()
        fake_reader = _FakePdfReader(["", ""])
        with patch("app.adapters.document_parser.PdfReader", return_value=fake_reader), patch.object(
            parser, "_ocr_scanned_pdf", return_value=["[Page 1]\nOCR text"]
        ) as ocr:
            sections = parser.parse_bytes(b"scanned-pdf")

        self.assertEqual(sections, ["[Page 1]\nOCR text"])
        ocr.assert_called_once_with(b"scanned-pdf")

    def test_native_text_pdf_does_not_invoke_ocr(self) -> None:
        parser = PdfDocumentParser()
        fake_reader = _FakePdfReader(["Native PDF text"])
        with patch("app.adapters.document_parser.PdfReader", return_value=fake_reader), patch.object(
            parser, "_ocr_scanned_pdf"
        ) as ocr:
            sections = parser.parse_bytes(b"native-pdf")

        self.assertEqual(sections, ["[Page 1]\nNative PDF text"])
        ocr.assert_not_called()

    def test_scanned_pdf_raises_actionable_error_when_tesseract_is_unavailable(self) -> None:
        parser = PdfDocumentParser()
        with patch("app.adapters.document_parser.PdfReader", return_value=_FakePdfReader([""])), patch.object(
            parser, "_ocr_scanned_pdf", side_effect=ValueError("OCR requires Tesseract. Install Tesseract and configure TESSERACT_CMD if it is not on PATH.")
        ):
            with self.assertRaisesRegex(ValueError, "Tesseract"):
                parser.parse_bytes(b"scanned-pdf")


class _FakePdfPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _FakePdfReader:
    def __init__(self, page_texts: list[str]) -> None:
        self.pages = [_FakePdfPage(text) for text in page_texts]


def _pptx_with_slide_texts(slide_texts: list[str]) -> bytes:
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        for index, text in enumerate(slide_texts, start=1):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>{text}</a:t></p:sld>',
            )
    return payload.getvalue()


def _blank_pdf() -> bytes:
    payload = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(payload)
    return payload.getvalue()


if __name__ == "__main__":
    unittest.main()
