
import re
from collections import Counter
from uuid import UUID

from backend.db import get_connection
from backend.embeddings import generate_embeddings


# Common words that don't help distinguish documents.
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by",
    "can", "could", "do", "does", "for", "from",
    "how", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "our", "should", "that",
    "the", "their", "them", "there", "these",
    "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "will", "with",
    "would", "you", "your", "according",
    "document", "please", "answer", "question",
    "list", "every", "all", "include", "including",
    "step", "steps", "order", "original",
}


def tokenize(text: str) -> list[str]:
    """
    Extract meaningful words for lightweight lexical matching.

    Apply simple normalization for common plural and
    verb endings without requiring another dependency.
    """
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())

    tokens = []

    for word in words:
        if word in STOP_WORDS:
            continue

        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 5 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ed"):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s"):
            word = word[:-1]

        if word and word not in STOP_WORDS:
            tokens.append(word)

    return tokens


def lexical_relevance(question: str, content: str) -> float:
    """
    Calculate how well a chunk matches important query words.

    Rewards coverage of query terms, with a small bonus for
    repeated matches. Repetition is capped so long chunks
    don't automatically dominate.
    """
    query_tokens = set(tokenize(question))

    if not query_tokens:
        return 0.0

    content_counts = Counter(tokenize(content))

    matched = query_tokens.intersection(content_counts)

    coverage = len(matched) / len(query_tokens)

    frequency_bonus = sum(
        min(content_counts[token], 3) - 1
        for token in matched
    )

    frequency_bonus = min(
        frequency_bonus / max(len(query_tokens) * 2, 1),
        1.0,
    )

    return round(
        0.85 * coverage + 0.15 * frequency_bonus,
        4,
    )


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
    top_k: int = 5,
    document_id: UUID | None = None,
) -> list[dict]:
    """
    Hybrid retrieval:
    1. Retrieve candidate chunks using pgvector.
    2. Score their lexical relevance to the question.
    3. Combine semantic and lexical scores.
    4. Return the highest-ranked chunks.

    Keeps the same response structure expected by
    main.py, llm.py, and the React frontend.
    """

    query_embedding = generate_embeddings([question])[0]

    if len(query_embedding) != 384:
        raise ValueError(
            "Expected a 384-dimensional query embedding."
        )

    vector = "[" + ",".join(map(str, query_embedding)) + "]"

    # Retrieve more candidates than we ultimately return.
    # This allows lexical reranking to promote relevant
    # chunks that weren't in the original top five.
    candidate_limit = max(20, top_k * 4)

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
                JOIN documents d
                    ON d.id = c.document_id
                WHERE (
                    %s::uuid IS NULL
                    OR d.id = %s::uuid
                )
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    vector,
                    document_id,
                    document_id,
                    vector,
                    candidate_limit,
                ),
            )

            rows = cursor.fetchall()

    candidates = []

    for row in rows:
        semantic_score = float(row[5])

        lexical_score = lexical_relevance(
            question,
            row[4],
        )

        # Preserve the semantic signal while giving
        # meaningful query terms some influence.
        combined_score = (
            0.65 * semantic_score
            + 0.35 * lexical_score
        )

        candidates.append(
            {
                "document_id": str(row[0]),
                "filename": row[1],
                "page_number": row[2],
                "document_chunk_index": row[3],
                "text": row[4],
                "score": round(semantic_score, 4),
                "lexical_score": lexical_score,
                "combined_score": round(combined_score, 4),
            }
        )

    candidates.sort(
        key=lambda item: (
            item["combined_score"],
            item["score"],
        ),
        reverse=True,
    )

    selected = candidates[:top_k]

    return [
        {
            "chunk_index": rank,
            "document_chunk_index": item[
                "document_chunk_index"
            ],
            "document_id": item["document_id"],
            "filename": item["filename"],
            "page_number": item["page_number"],
            "text": item["text"],
            "score": item["score"],
        }
        for rank, item in enumerate(selected)
    ]
