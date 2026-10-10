
def split_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100
) -> list[str]:
    """
    Split text into overlapping chunks.

    Uses word boundaries when possible and falls back
    to character boundaries for very long words.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            "overlap must be between 0 and chunk_size"
        )

    text = " ".join(text.split())

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            space_index = text.rfind(" ", start + 1, end + 1)

            if space_index > start:
                end = space_index

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        next_start = max(start + 1, end - overlap)

        if text[next_start] != " ":
            previous_space = text.rfind(
                " ", next_start, end
            )

            if previous_space > start:
                next_start = previous_space + 1

        start = next_start

        while start < len(text) and text[start] == " ":
            start += 1

    return chunks
