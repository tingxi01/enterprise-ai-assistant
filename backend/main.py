
from contextlib import asynccontextmanager
from uuid import UUID

import fitz
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.chunking import split_text
from backend.db import initialize_database
from backend.embeddings import generate_embeddings
from backend.llm import generate_answer
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
    version="0.2.0",
    lifespan=lifespan,
)


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=20)
    document_id: UUID | None = None


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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
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
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise HTTPException(
                    status_code=400,
                    detail="Password-protected PDFs are not supported.",
                )

            pages = [page.get_text() for page in pdf]

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

    # Keep page numbers associated with text chunks.
    numbered_chunks = []

    for page_number, page_text in enumerate(pages, start=1):
        page_chunks = split_text(
            text=page_text,
            chunk_size=500,
            overlap=100,
        )

        for chunk in page_chunks:
            numbered_chunks.append((page_number, chunk))

    if not numbered_chunks:
        raise HTTPException(
            status_code=422,
            detail="Unable to generate text chunks.",
        )

    try:
        embeddings = generate_embeddings(
            [content for _, content in numbered_chunks]
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
        "characters_extracted": sum(len(page) for page in pages),
        "total_chunks": len(numbered_chunks),
        "chunk_previews": [
            content for _, content in numbered_chunks[:3]
        ],
        "status": "processed",
    }


@app.get("/documents")
def get_documents():
    try:
        return {"documents": list_documents()}
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

    return {"status": "deleted", "document_id": str(document_id)}


def retrieve_context(request: SearchRequest):
    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    try:
        results = search_documents(
            question=request.question,
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
    results = retrieve_context(request)

    return {
        "question": request.question,
        "results": results,
        "total_results": len(results),
    }


@app.post("/documents/ask")
def ask_document(request: SearchRequest):
    results = retrieve_context(request)

    try:
        answer = generate_answer(
            question=request.question,
            retrieved_chunks=results,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to generate an AI answer.",
        ) from exc

    return {
        "question": request.question,
        "answer": answer,
        "sources": results,
        "model": "qwen3:4b",
    }
