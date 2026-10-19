
from unittest.mock import patch
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient

from backend.main import app

@pytest.fixture
def client():
    # Creating TestClient without entering its context manager
    # avoids running the app's lifespan startup hook.
    # All repository and AI operations are mocked separately.
    return TestClient(app)



def make_pdf(text="This is a sample test document."):
    """Create a small PDF entirely in memory."""
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    data = pdf.tobytes()
    pdf.close()
    return data


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_reject_non_pdf_upload(client):
    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "notes.txt",
                b"Not a PDF",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Only PDF files are supported."
    )


def test_reject_oversized_pdf(client):
    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "large.pdf",
                b"x" * (10 * 1024 * 1024 + 1),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "PDF must be 10 MB or smaller."
    )


def test_reject_invalid_pdf(client):
    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "broken.pdf",
                b"not a real PDF",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unable to process this PDF."
    )


def test_reject_pdf_without_readable_text(client):
    pdf = fitz.open()
    pdf.new_page()
    blank_pdf = pdf.tobytes()
    pdf.close()

    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "blank.pdf",
                blank_pdf,
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "No readable text found in the PDF."
    )


def test_upload_valid_pdf(client):
    fake_id = uuid4()

    with (
        patch(
            "backend.main.generate_embeddings",
            return_value=[[0.1, 0.2, 0.3]],
        ),
        patch(
            "backend.main.save_document",
            return_value=fake_id,
        ) as mock_save,
    ):
        response = client.post(
            "/documents/upload",
            files={
                "file": (
                    "sample.pdf",
                    make_pdf(),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200

    data = response.json()
    assert data["filename"] == "sample.pdf"
    assert data["pages"] == 1
    assert data["total_chunks"] >= 1
    assert data["status"] == "processed"

    mock_save.assert_called_once()


def test_list_documents(client):
    fake_documents = [
        {
            "id": str(uuid4()),
            "filename": "handbook.pdf",
            "pages": 5,
            "total_chunks": 12,
        }
    ]

    with patch(
        "backend.main.list_documents",
        return_value=fake_documents,
    ):
        response = client.get("/documents")

    assert response.status_code == 200
    assert response.json()["documents"] == fake_documents


def test_delete_document_success(client):
    document_id = uuid4()

    with patch(
        "backend.main.delete_document",
        return_value=True,
    ) as mock_delete:
        response = client.delete(
            f"/documents/{document_id}"
        )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["document_id"] == str(document_id)

    mock_delete.assert_called_once_with(document_id)


def test_delete_document_not_found(client):
    document_id = uuid4()

    with patch(
        "backend.main.delete_document",
        return_value=False,
    ):
        response = client.delete(
            f"/documents/{document_id}"
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_search_documents(client):
    document_id = uuid4()

    fake_results = [
        {
            "document_id": str(document_id),
            "filename": "handbook.pdf",
            "page_number": 2,
            "chunk_index": 0,
            "text": "Employees may work from home one day per week.",
            "score": 0.91,
        }
    ]

    with patch(
        "backend.main.search_documents",
        return_value=fake_results,
    ) as mock_search:
        response = client.post(
            "/documents/search",
            json={
                "question": "How often can employees work from home?",
                "top_k": 5,
                "document_id": str(document_id),
            },
        )

    assert response.status_code == 200
    assert response.json()["total_results"] == 1
    assert response.json()["results"] == fake_results

    mock_search.assert_called_once()


def test_search_without_results(client):
    with patch(
        "backend.main.search_documents",
        return_value=[],
    ):
        response = client.post(
            "/documents/search",
            json={
                "question": "Unknown policy",
                "top_k": 5,
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "No matching document content found."
    )


def test_ask_uses_conversation_history(client):
    history = [
        {
            "role": "user",
            "content": (
                "How many days per week can employees work from home?"
            ),
        },
        {
            "role": "assistant",
            "content": "One day per week.",
        },
    ]

    rewritten = (
        "What is the advance notice period "
        "for working from home?"
    )

    fake_results = [
        {
            "document_id": str(uuid4()),
            "filename": "handbook.pdf",
            "page_number": 4,
            "chunk_index": 0,
            "text": (
                "Working from home must be requested "
                "two days in advance."
            ),
            "score": 0.92,
        }
    ]

    with (
        patch(
            "backend.main.resolve_follow_up",
            return_value=rewritten,
        ) as mock_resolve,
        patch(
            "backend.main.search_documents",
            return_value=fake_results,
        ) as mock_search,
        patch(
            "backend.main.answer_from_numbered_procedure",
            return_value=None,
        ),
        patch(
            "backend.main.generate_answer",
            return_value=(
                "Employees must request working from home "
                "two days in advance. [Source 1]"
            ),
        ),
    ):
        response = client.post(
            "/documents/ask",
            json={
                "question": "What about the notice period?",
                "history": history,
            },
        )

    assert response.status_code == 200

    data = response.json()

    assert data["resolved_question"] == rewritten
    assert "two days in advance" in data["answer"]
    assert data["sources"] == fake_results

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.kwargs["history"] == history

    assert (
        mock_search.call_args.kwargs["question"] == rewritten
    )
