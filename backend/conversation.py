
"""Resolve conversational follow-ups into standalone search questions."""

import re

import requests

from backend.llm import MODEL_NAME, OLLAMA_URL


FOLLOW_UP_PATTERN = re.compile(
    r"^(?:and\b|what about\b|how about\b|also\b|"
    r"what if\b|does (?:that|it|this)\b|"
    r"is (?:that|it|this)\b|can (?:they|i|we|it)\b|"
    r"when (?:does|can|should) (?:it|that|they)\b|"
    r"why (?:is|does|do) (?:it|that|they)\b)",
    flags=re.IGNORECASE,
)

REFERENTIAL_PATTERN = re.compile(
    r"\b(?:it|that|this|those|they|them|their|its|same)\b",
    flags=re.IGNORECASE,
)


def needs_context(question: str) -> bool:
    """Identify questions likely to depend on earlier messages."""
    words = question.split()

    if FOLLOW_UP_PATTERN.search(question):
        return True

    return (
        len(words) <= 9
        and bool(REFERENTIAL_PATTERN.search(question))
    )


def resolve_follow_up(
    question: str,
    history: list[dict],
) -> str:
    """
    Convert an ambiguous follow-up into a standalone question.

    Example:
        Previous: How many days can employees work from home?
        Current: What about the notice period?

        Resolved:
        What is the advance notice period for working from home?

    History is temporary and is not written to the database.
    """

    if not history or not needs_context(question):
        return question

    recent = history[-6:]

    transcript = "\n".join(
        f"{turn['role'].upper()}: {turn['content'][:1200]}"
        for turn in recent
        if turn.get("role") in {"user", "assistant"}
    )

    if not transcript:
        return question

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite the latest user's question as a "
                            "standalone question for searching documents. "
                            "Resolve references using the conversation, "
                            "preserving the user's intent. "
                            "Do not answer the question. "
                            "Do not include facts, citations, explanations, "
                            "labels, or document excerpts. "
                            "Return only one question."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"CONVERSATION:\n{transcript}\n\n"
                            f"LATEST QUESTION:\n{question}"
                        ),
                    },
                ],
                "options": {
                    "temperature": 0,
                    "num_predict": 96,
                },
            },
            timeout=(5, 30),
        )

        response.raise_for_status()
        payload = response.json()

        if payload.get("done_reason") == "length":
            return question

        rewritten = (
            payload.get("message", {})
            .get("content", "")
            .strip()
        )

        rewritten = rewritten.strip('"\'` ')

        if (
            not rewritten
            or len(rewritten) > 350
            or "\n" in rewritten
            or "<think>" in rewritten
            or "[Source" in rewritten
        ):
            return question

        return rewritten

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ):
        return question
