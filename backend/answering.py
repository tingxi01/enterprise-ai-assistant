
import re


PROCEDURE_WORDS = {
    "how",
    "steps",
    "step",
    "instructions",
    "instruction",
    "procedure",
    "process",
    "replace",
    "change",
    "edit",
    "upload",
    "publish",
    "set",
    "follow",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be",
    "can", "do", "does", "for", "from", "i",
    "in", "is", "it", "me", "my", "of", "on",
    "or", "the", "this", "to", "what", "when",
    "where", "which", "with", "you", "your",
    "canva", "template", "document", "according",
    "list", "all", "every", "six", "original",
    "order", "numbered", "exactly", "written",
}


def normalize_word(word: str) -> str:
    word = word.lower()

    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"

    if word.endswith("s") and len(word) > 3:
        return word[:-1]

    return word


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower())

    return {
        normalized
        for word in words
        if (normalized := normalize_word(word))
        not in STOP_WORDS
    }


def is_procedure_question(question: str) -> bool:
    words = keywords(question)

    return bool(words & PROCEDURE_WORDS)


def extract_numbered_procedure(text: str):
    """
    Extract one complete, sequential numbered procedure.

    Only accepts chunks containing one unambiguous list
    numbered 1, 2, 3, ... in order.

    Returns None if the text is incomplete, ambiguous,
    or contains multiple numbered lists.
    """

    matches = list(
        re.finditer(
            r"(?<!\w)(\d{1,2})\.\s+",
            text,
        )
    )

    if len(matches) < 3 or len(matches) > 15:
        return None

    numbers = [
        int(match.group(1))
        for match in matches
    ]

    expected_numbers = list(
        range(1, len(matches) + 1)
    )

    if numbers != expected_numbers:
        return None

    heading = text[:matches[0].start()].strip()

    # Only trust a concise heading directly preceding
    # the numbered procedure.
    if not heading or len(heading) > 100:
        return None

    steps = []

    for index, match in enumerate(matches):
        start = match.end()

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        step = text[start:end].strip()

        if not step:
            return None

        steps.append(
            f"{numbers[index]}. {step}"
        )

    return {
        "heading": heading,
        "steps": steps,
    }


def answer_from_numbered_procedure(
    question: str,
    retrieved_chunks: list[dict],
) -> str | None:
    """
    Return source-preserved numbered instructions
    when a matching, complete procedure is retrieved.

    Otherwise return None so the normal LLM can answer.
    """

    if not is_procedure_question(question):
        return None

    question_terms = keywords(question)

    candidates = []

    for index, chunk in enumerate(
        retrieved_chunks,
        start=1,
    ):
        procedure = extract_numbered_procedure(
            chunk["text"]
        )

        if procedure is None:
            continue

        heading_terms = keywords(
            procedure["heading"]
        )

        overlap = question_terms & heading_terms

        # Require a topic match to the procedure heading.
        # This prevents a photo question from returning
        # unrelated "EDITING LINKS" instructions.
        if not overlap:
            continue

        relevance = len(overlap) / max(
            len(heading_terms),
            1,
        )

        candidates.append(
            {
                "relevance": relevance,
                "similarity": chunk.get("score", 0),
                "source_number": index,
                "procedure": procedure,
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["relevance"],
            item["similarity"],
        ),
        reverse=True,
    )

    best = candidates[0]

    # Do not force a choice between equally relevant
    # but different procedures.
    if len(candidates) > 1:
        second = candidates[1]

        if (
            second["relevance"] == best["relevance"]
            and second["similarity"] == best["similarity"]
        ):
            return None

    procedure = best["procedure"]

    answer = (
        f"According to the {procedure['heading']} section:\n\n"
        + "\n".join(procedure["steps"])
        + f"\n\n[Source {best['source_number']}]"
    )

    return answer
