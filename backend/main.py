
from fastapi import FastAPI, UploadFile, File, HTTPException
from backend.chunking import split_text
import fitz

app = FastAPI(
    title="Enterprise AI Assistant",
    description="Backend API for an AI-powered enterprise knowledge assistant",
    version="0.1.0"
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@app.get("/")
def home():
    return {
        "message": "Welcome to Enterprise AI Assistant!",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported."
        )

    pdf_bytes = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF must be 10 MB or smaller."
        )

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
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Unable to process this PDF."
        )

    chunks = split_text(
        text=extracted_text,
        chunk_size=500,
        overlap=100
    )

    return {
        "filename": file.filename,
        "pages": page_count,
        "characters_extracted": len(extracted_text),
        "total_chunks": len(chunks),
        "chunk_previews": chunks[:3],
        "status": "processed"
    }
