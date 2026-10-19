
from unittest.mock import MagicMock, patch

from backend.conversation import needs_context, resolve_follow_up


def test_standalone_question_does_not_need_context():
    question = "How many days per week can employees work from home?"

    assert needs_context(question) is False


def test_follow_up_question_needs_context():
    assert needs_context("What about the notice period?") is True
    assert needs_context("How about the approval process?") is True


def test_no_history_keeps_original_question():
    question = "What about the notice period?"

    result = resolve_follow_up(question, [])

    assert result == question


def test_follow_up_uses_conversation_history():
    history = [
        {
            "role": "user",
            "content": (
                "How many days per week can employees "
                "work from home?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Employees can work from home "
                "one day per week."
            ),
        },
    ]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": (
                "What is the advance notice period "
                "for working from home?"
            )
        },
        "done_reason": "stop",
    }

    with patch(
        "backend.conversation.requests.post",
        return_value=mock_response,
    ) as mock_post:
        result = resolve_follow_up(
            "What about the notice period?",
            history,
        )

    assert result == (
        "What is the advance notice period "
        "for working from home?"
    )

    mock_post.assert_called_once()

    payload = mock_post.call_args.kwargs["json"]

    assert "work from home" in (
        payload["messages"][1]["content"].lower()
    )


def test_standalone_question_skips_rewriting():
    history = [
        {
            "role": "user",
            "content": "What is the annual leave entitlement?",
        },
        {
            "role": "assistant",
            "content": "Employees receive annual leave.",
        },
    ]

    with patch("backend.conversation.requests.post") as mock_post:
        result = resolve_follow_up(
            "How many days per week can employees work from home?",
            history,
        )

    assert result == (
        "How many days per week can employees work from home?"
    )

    mock_post.assert_not_called()
