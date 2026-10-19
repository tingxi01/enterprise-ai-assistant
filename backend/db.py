
import os

import psycopg
from dotenv import load_dotenv


load_dotenv()


def get_connection():
    """
    Connect to the PostgreSQL database.
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg.connect(database_url)


def initialize_database():
    """
    Create the database tables if they do not exist.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Enable vector support
            cursor.execute("""
                CREATE EXTENSION IF NOT EXISTS vector;
            """)

            # Store uploaded document metadata
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    filename TEXT NOT NULL,

                    page_count INTEGER NOT NULL,

                    uploaded_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );
            """)

            # Store document chunks and embeddings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id BIGSERIAL PRIMARY KEY,

                    document_id UUID NOT NULL
                        REFERENCES documents(id)
                        ON DELETE CASCADE,

                    page_number INTEGER NOT NULL,

                    chunk_index INTEGER NOT NULL,

                    content TEXT NOT NULL,

                    embedding VECTOR(384) NOT NULL,

                    UNIQUE(document_id, chunk_index)
                );
            """)

            # Speed up document-specific queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                    idx_chunks_document_id
                ON document_chunks(document_id);
            """)

        connection.commit()

    print("Database initialized successfully.")


if __name__ == "__main__":
    initialize_database()
