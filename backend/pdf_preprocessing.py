
import re

import fitz


def extract_ordered_page_text(page: fitz.Page) -> str:
    """
    Extract PDF text while preserving simple numbered procedures.

    Uses word coordinates to separate instructions that appear
    side by side, such as steps 2 and 3 in a two-column layout.

    Falls back to PyMuPDF's sorted text extraction when a
    clear, unique numbered sequence cannot be detected.
    """

    fallback = page.get_text("text", sort=True)
    words = page.get_text("words", sort=True)

    anchors = []

    for word in words:
        match = re.fullmatch(r"(\d{1,2})\.", word[4])

        if match:
            anchors.append({
                "number": int(match.group(1)),
                "x": word[0],
                "y": word[1],
                "word": word,
            })

    numbers = [anchor["number"] for anchor in anchors]

    # Avoid rearranging unrelated lists or ambiguous pages.
    if (
        len(numbers) < 3
        or len(set(numbers)) != len(numbers)
        or sorted(numbers) != list(range(1, len(numbers) + 1))
    ):
        return fallback

    anchors.sort(key=lambda item: item["number"])

    # The page's first numbered item marks the beginning of
    # the procedure. Keep any preceding heading separately.
    first_y = min(anchor["y"] for anchor in anchors)

    heading_words = [
        word for word in words
        if word[1] < first_y - 3
    ]

    groups = {
        anchor["number"]: []
        for anchor in anchors
    }

    anchor_word_ids = {
        (anchor["word"][0], anchor["word"][1],
         anchor["word"][4])
        for anchor in anchors
    }

    for word in words:
        x, y = word[0], word[1]

        if y < first_y - 3:
            continue

        word_id = (word[0], word[1], word[4])

        if word_id in anchor_word_ids:
            continue

        # Find the most recent row of numbered steps.
        preceding = [
            anchor for anchor in anchors
            if anchor["y"] <= y + 3
        ]

        if not preceding:
            continue

        latest_y = max(anchor["y"] for anchor in preceding)

        same_row = [
            anchor for anchor in preceding
            if abs(anchor["y"] - latest_y) <= 4
        ]

        # When two steps share a row, allocate words to the
        # nearest step column rather than mixing the columns.
        selected = min(
            same_row,
            key=lambda anchor: abs(x - anchor["x"]),
        )

        groups[selected["number"]].append(word)

    def words_to_text(items):
        if not items:
            return ""

        items = sorted(items, key=lambda w: (round(w[1] / 4), w[0]))
        return " ".join(str(w[4]) for w in items).strip()

    output = []

    heading = words_to_text(heading_words)

    if heading:
        output.append(heading)

    for anchor in anchors:
        step_text = words_to_text(groups[anchor["number"]])

        if not step_text:
            return fallback

        output.append(
            f"{anchor['number']}. {step_text}"
        )

    return "\n".join(output)
