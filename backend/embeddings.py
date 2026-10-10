
from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model():
    """Load the embedding model once and reuse it."""
    return SentenceTransformer("all-MiniLM-L6-v2")


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Convert document chunks into numerical vectors."""
    if not texts:
        return []

    model = get_model()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True
    )

    return embeddings.tolist()
