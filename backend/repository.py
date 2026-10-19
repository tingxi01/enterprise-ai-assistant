
from uuid import UUID

from backend.db import get_connection
from backend.embeddings import generate_embeddings


def save_document(
    filename: str,
    pages: list[str],
    chunks: list[tuple[int, str]],
    embeddings: list[list[float]],
) -> str:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk and embedding counts do not match.")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documents (filename, page_count)
                VALUES (%s, %s)
                RETURNING id
                """,
                (filename, len(pages)),
            )

            document_id = cursor.fetchone()[0]

            for index, ((page_number, content), embedding) in enumerate(
                zip(chunks, embeddings)
            ):
                if len(embedding) != 384:
                    raise ValueError("Expected a 384-dimensional embedding.")

                vector = "[" + ",".join(map(str, embedding)) + "]"

                cursor.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id,
                        page_number,
                        chunk_index,
                        content,
                        embedding
                    )
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    (
                        document_id,
                        page_number,
                        index,
                        content,
                        vector,
                    ),
                )

        connection.commit()

    return str(document_id)


def list_documents() -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id, d.filename, d.page_count,
                       d.uploaded_at, COUNT(c.id)
                FROM documents d
                LEFT JOIN document_chunks c
                    ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.uploaded_at DESC
                """
            )

            return [
                {
                    "id": str(row[0]),
                    "filename": row[1],
                    "pages": row[2],
                    "uploaded_at": row[3].isoformat(),
                    "total_chunks": row[4],
                }
                for row in cursor.fetchall()
            ]


def delete_document(document_id: UUID) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM documents WHERE id = %s",
                (document_id,),
            )
            deleted = cursor.rowcount > 0

        connection.commit()

    return deleted


def search_documents(
    question: str,
    top_k: int = 3,
    document_id: UUID | None = None,
) -> list[dict]:
    query_embedding = generate_embeddings([question])[0]

    if len(query_embedding) != 384:
        raise ValueError("Expected a 384-dimensional query embedding.")

    vector = "[" + ",".join(map(str, query_embedding)) + "]"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    d.id,
                    d.filename,
                    c.page_number,
                    c.chunk_index,
                    c.content,
                    1 - (c.embedding <=> %s::vector) AS score
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE (%s::uuid IS NULL OR d.id = %s::uuid)
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    vector,
                    document_id,
                    document_id,
                    vector,
                    top_k,
                ),
            )

            rows = cursor.fetchall()

    return [
        {
            # Number each retrieved source consistently for the LLM
            # and the existing React interface.
            "chunk_index": rank,
            "document_chunk_index": row[3],
            "document_id": str(row[0]),
            "filename": row[1],
            "page_number": row[2],
            "text": row[4],
            "score": round(float(row[5]), 4),
        }
        for rank, row in enumerate(rows)
    ]
