
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

import fitz
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.answering import answer_from_numbered_procedure
from backend.chunking import split_text
from backend.conversation import resolve_follow_up
from backend.db import initialize_database
from backend.embeddings import generate_embeddings
from backend.llm import MODEL_NAME, generate_answer
from backend.pdf_preprocessing import extract_ordered_page_text
from backend.repository import (
    delete_document,
    list_documents,
    save_document,
    search_documents,
)


MAX_FILE_SIZE = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Enterprise AI Assistant",
    description="AI-powered enterprise knowledge assistant",
    version="0.3.0",
    lifespan=lifespan,
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: UUID | None = None
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=6,
    )


@app.get("/")
def home():
    return {
        "message": "Welcome to Enterprise AI Assistant!",
        "status": "running",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    if (
        not file.filename
        or not file.filename.lower().endswith(".pdf")
    ):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported.",
        )

    pdf_bytes = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF must be 10 MB or smaller.",
        )

    try:
        with fitz.open(
            stream=pdf_bytes,
            filetype="pdf",
        ) as pdf:
            if pdf.needs_pass:
                raise HTTPException(
                    status_code=400,
                    detail="Password-protected PDFs are not supported.",
                )

            pages = [
                extract_ordered_page_text(page)
                for page in pdf
            ]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Unable to process this PDF.",
        ) from exc

    if not any(page.strip() for page in pages):
        raise HTTPException(
            status_code=422,
            detail="No readable text found in the PDF.",
        )

    numbered_chunks = []

    for page_number, page_text in enumerate(
        pages,
        start=1,
    ):
        page_chunks = split_text(
            text=page_text,
            chunk_size=500,
            overlap=100,
        )

        for chunk in page_chunks:
            numbered_chunks.append(
                (page_number, chunk)
            )

    if not numbered_chunks:
        raise HTTPException(
            status_code=422,
            detail="Unable to generate text chunks.",
        )

    try:
        embeddings = generate_embeddings(
            [
                content
                for _, content in numbered_chunks
            ]
        )

        document_id = save_document(
            filename=file.filename,
            pages=pages,
            chunks=numbered_chunks,
            embeddings=embeddings,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to process or save document.",
        ) from exc

    return {
        "id": document_id,
        "filename": file.filename,
        "pages": len(pages),
        "characters_extracted": sum(
            len(page) for page in pages
        ),
        "total_chunks": len(numbered_chunks),
        "chunk_previews": [
            content
            for _, content in numbered_chunks[:3]
        ],
        "status": "processed",
    }


@app.get("/documents")
def get_documents():
    try:
        return {
            "documents": list_documents()
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve documents.",
        ) from exc


@app.delete("/documents/{document_id}")
def remove_document(document_id: UUID):
    try:
        deleted = delete_document(document_id)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete document.",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    return {
        "status": "deleted",
        "document_id": str(document_id),
    }


def retrieve_context(
    request: SearchRequest,
    question: str | None = None,
):
    effective_question = (
        question
        if question is not None
        else request.question
    )

    if not effective_question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    try:
        results = search_documents(
            question=effective_question,
            top_k=request.top_k,
            document_id=request.document_id,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Document search failed.",
        ) from exc

    if not results:
        raise HTTPException(
            status_code=404,
            detail="No matching document content found.",
        )

    return results


@app.post("/documents/search")
def search_document(request: SearchRequest):
    # History does not affect the search-only endpoint.
    results = retrieve_context(request)

    return {
        "question": request.question,
        "results": results,
        "total_results": len(results),
    }


@app.post("/documents/ask")
def ask_document(request: SearchRequest):
    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    # Resolve ambiguous conversational follow-ups.
    # One-shot questions continue through the original RAG path.
    resolved_question = resolve_follow_up(
        question=request.question,
        history=[
            turn.model_dump()
            for turn in request.history
        ],
    )

    print(
        f"[CONVERSATION] Original: {request.question!r} | "
        f"History turns: {len(request.history)} | "
        f"Resolved: {resolved_question!r}",
        flush=True,
    )

    results = retrieve_context(
        request,
        question=resolved_question,
    )

    try:
        # Return exact numbered instructions when possible.
        answer = answer_from_numbered_procedure(
            question=resolved_question,
            retrieved_chunks=results,
        )

        # Otherwise use Qwen2.5 to generate a grounded answer.
        if answer is None:
            answer = generate_answer(
                question=resolved_question,
                retrieved_chunks=results,
            )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to generate an AI answer.",
        ) from exc

    return {
        "question": request.question,
        "resolved_question": resolved_question,
        "answer": answer,
        "sources": results,
        "model": MODEL_NAME,
    }
