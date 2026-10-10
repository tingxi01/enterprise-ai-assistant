
from backend.embeddings import generate_embeddings


def semantic_search(
    query: str,
    chunks: list[str],
    chunk_embeddings: list[list[float]],
    top_k: int = 3
) -> list[dict]:
    """Search using previously generated document embeddings."""

    if not query.strip() or not chunks or top_k <= 0:
        return []

    if len(chunks) != len(chunk_embeddings):
        raise ValueError(
            "Chunks and embeddings must have matching lengths."
        )

    # Generate an embedding for the question only.
    query_vector = generate_embeddings([query])[0]

    results = []

    for index, chunk_vector in enumerate(chunk_embeddings):

        # Vectors are normalized by generate_embeddings().
        score = sum(
            a * b
            for a, b in zip(query_vector, chunk_vector)
        )

        results.append({
            "chunk_index": index,
            "text": chunks[index],
            "score": round(float(score), 4)
        })

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return results[:top_k]
