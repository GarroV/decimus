"""A mail subject belongs in its header; saved human text stays intact."""

import pytest

from src.report.letter_markup import subject_and_body, to_plain
from src.web.google_mail import GoogleMailError, letter_message


@pytest.mark.parametrize("prefix", ["Тема", "Subject", "SUBJECT", "тема"])
def test_leading_subject_is_separated_from_both_mail_alternatives(prefix: str) -> None:
    raw = f"<b>{prefix}: Human-edited result</b>\n\nHello!\n<b>87.0%</b>\nFull comment."
    subject, body = subject_and_body(raw, fallback="Generic subject")
    message = letter_message(to="partner@example.com", subject=subject, body=body)
    assert str(message["Subject"]) == "Human-edited result"
    plain = message.get_body(preferencelist=("plain",))
    rich = message.get_body(preferencelist=("html",))
    assert plain is not None and rich is not None
    assert plain.get_content().strip() == "Hello!\n87.0%\nFull comment."
    assert "Human-edited result" not in rich.get_content()
    assert "<b>87.0%</b>" in rich.get_content()


def test_inline_formatting_crossing_the_subject_survives() -> None:
    subject, body = subject_and_body(
        "<b>Тема: Изменённая тема\n\nТекст <i>человека</i></b>", fallback="Fallback"
    )
    assert subject == "Изменённая тема"
    assert body == "<b>Текст <i>человека</i></b>"


def test_open_link_crossing_header_survives_with_its_destination() -> None:
    subject, body = subject_and_body(
        '<a href="https://example.com/report">Subject: Report\n\nRead report</a>',
        fallback="Fallback",
    )
    assert subject.startswith("Report")
    assert body == '<a href="https://example.com/report">Read report</a>'


@pytest.mark.parametrize("raw", ["Hello!\nSubject: Keep this line", "Subject:\n\nHello!", "Hello!"])
def test_no_leading_subject_keeps_human_body_exactly(raw: str) -> None:
    assert subject_and_body(raw, fallback="Fallback") == ("Fallback", raw)


def test_leading_blank_lines_and_empty_formatting_do_not_enter_body() -> None:
    assert subject_and_body("\n<b></b>\nSubject: Result\n\nHello!", fallback="Fallback") == (
        "Result",
        "Hello!",
    )


def test_header_looking_body_content_cannot_add_recipients() -> None:
    subject, body = subject_and_body(
        "Subject: Result\nBcc: other@example.com\nHello!", fallback="Fallback"
    )
    message = letter_message(to="partner@example.com", subject=subject, body=body)
    assert str(message["Subject"]) == "Result"
    assert "Bcc" not in message
    assert "Bcc: other@example.com" in to_plain(body)


def test_subject_alone_cannot_create_an_empty_draft() -> None:
    subject, body = subject_and_body("Subject: Result", fallback="Fallback")
    with pytest.raises(GoogleMailError):
        letter_message(to="partner@example.com", subject=subject, body=body)
