
import pytest

from backend.chunking import split_text


def test_empty_text():
    assert split_text("") == []


def test_short_text():
    assert split_text(
        "Hello world",
        chunk_size=100,
        overlap=20
    ) == ["Hello world"]


def test_long_text_creates_multiple_chunks():
    text = "A" * 1200

    chunks = split_text(
        text,
        chunk_size=500,
        overlap=100
    )

    assert len(chunks) == 3
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_chunk_overlap():
    text = "".join(str(i % 10) for i in range(100))

    chunks = split_text(
        text,
        chunk_size=40,
        overlap=10
    )

    assert chunks[0][-10:] == chunks[1][:10]


def test_invalid_chunk_size():
    with pytest.raises(ValueError):
        split_text("hello", chunk_size=0)


def test_invalid_overlap():
    with pytest.raises(ValueError):
        split_text(
            "hello",
            chunk_size=100,
            overlap=100
        )
