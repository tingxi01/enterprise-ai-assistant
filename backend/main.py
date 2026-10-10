
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
import fitz

from backend.chunking import split_text
from backend.embeddings import generate_embeddings
from backend.search import semantic_search


# --------------------------------------------------
# Application Configuration
# --------------------------------------------------

app = FastAPI(
    title="Enterprise AI Assistant",
    description="Backend API for an AI-powered enterprise knowledge assistant",
    version="0.1.0"
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# --------------------------------------------------
# Temporary Document Storage
# --------------------------------------------------

# These variables temporarily store one uploaded document.
# They will be replaced with a database in the future.

document_chunks: list[str] = []
document_embeddings: list[list[float]] = []


# --------------------------------------------------
# Request Models
# --------------------------------------------------

class SearchRequest(BaseModel):
    question: str
    top_k: int = Field(default=3, ge=1, le=20)


# --------------------------------------------------
# Basic Endpoints
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Welcome to Enterprise AI Assistant!",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# --------------------------------------------------
# PDF Upload and Processing
# --------------------------------------------------

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):

    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported."
        )

    # Read file with size limit
    pdf_bytes = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF must be 10 MB or smaller."
        )

    # Step 1: Extract text from PDF
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:

            if pdf.needs_pass:
                raise HTTPException(
                    status_code=400,
                    detail="Password-protected PDFs are not supported."
                )

            page_count = len(pdf)

            extracted_text = "\n".join(
                page.get_text() for page in pdf
            )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Unable to process this PDF."
        ) from exc

    # Step 2: Check extracted text
    if not extracted_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No readable text found in the PDF."
        )

    # Step 3: Split document into chunks
    chunks = split_text(
        text=extracted_text,
        chunk_size=500,
        overlap=100
    )

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="Unable to generate text chunks."
        )

    # Step 4: Generate embeddings once
    try:
        new_embeddings = generate_embeddings(chunks)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate document embeddings."
        ) from exc

    # Step 5: Verify embedding count
    if len(new_embeddings) != len(chunks):
        raise HTTPException(
            status_code=500,
            detail="Embedding count does not match chunk count."
        )

    # Step 6: Store document data in memory
    # Replace both only after processing succeeds.
    document_chunks.clear()
    document_chunks.extend(chunks)

    document_embeddings.clear()
    document_embeddings.extend(new_embeddings)

    return {
        "filename": file.filename,
        "pages": page_count,
        "characters_extracted": len(extracted_text),
        "total_chunks": len(chunks),
        "chunk_previews": chunks[:3],
        "status": "processed"
    }


# --------------------------------------------------
# Semantic Document Search
# --------------------------------------------------

@app.post("/documents/search")
def search_document(request: SearchRequest):

    if not document_chunks or not document_embeddings:
        raise HTTPException(
            status_code=404,
            detail="No document uploaded yet."
        )

    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    try:
        results = semantic_search(
            query=request.question,
            chunks=document_chunks,
            chunk_embeddings=document_embeddings,
            top_k=request.top_k
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Semantic search failed."
        ) from exc

    return {
        "question": request.question,
        "results": results,
        "total_results": len(results)
    }
