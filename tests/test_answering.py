
from backend.answering import (
    answer_from_numbered_procedure,
    is_procedure_question,
)


def test_password_frequency_is_not_a_procedure():
    question = "How often must users change their password?"

    assert is_procedure_question(question) is False


def test_frequency_question_skips_numbered_extraction():
    irrelevant_source = {
        "text": (
            "Security Policy: "
            "1. Change your phone number "
            "2. Report a forgotten password "
            "3. Notify the registry about new responsibilities"
        ),
        "score": 0.9,
    }

    answer = answer_from_numbered_procedure(
        question="How often must users change their password?",
        retrieved_chunks=[irrelevant_source],
    )

    assert answer is None


def test_instruction_question_still_detected():
    assert is_procedure_question(
        "How do I change my password?"
    ) is True
