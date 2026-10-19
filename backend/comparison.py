
import re


def is_comparison_question(question: str) -> bool:
    """Detect questions asking to compare two things."""
    return bool(
        re.search(
            r"\b(difference|differences|compare|comparison|versus|vs\.?)\b",
            question,
            flags=re.IGNORECASE,
        )
    )


def build_comparison_context(
    question: str,
    retrieved_chunks: list[dict],
) -> str | None:
    """
    Build a structured context for comparison questions.

    Preserve each retrieved excerpt with its original source
    number so citations remain consistent with the UI.
    """
    if not is_comparison_question(question):
        return None

    if not retrieved_chunks:
        return None

    sections = []

    for index, chunk in enumerate(retrieved_chunks, start=1):
        sections.append(
            f"[Source {index}]\n"
            f"Document: {chunk['filename']}\n"
            f"Page: {chunk['page_number']}\n"
            f"Evidence:\n{chunk['text']}"
        )

    return "\n\n".join(sections)
