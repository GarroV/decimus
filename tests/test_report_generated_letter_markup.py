"""Generated letters emphasise findings/results without changing or trusting their text."""

import pytest

from src.report import letter_markup


@pytest.mark.parametrize(
    ("result", "subject"),
    [
        ("Итоговая оценка — C (87%).", "Тема: Проверка"),
        ("The final grade is C (87%).", "Subject: Inspection"),
    ],
)
def test_generated_letter_has_safe_emphasis_and_lossless_plain_text(
    result: str, subject: str
) -> None:
    text = (
        f"{subject}\n\n{result}\nДата: 2026-10-30\n\n"
        "Что зафиксировали:\n— D1: 4.\n\n— Зона:\n"
        "• R&D и t<5°C, <script>alert(1)</script>\n"
        "• Полное второе замечание.\n"
    )
    markup = letter_markup.from_generated(text)
    assert letter_markup.sanitize(markup) == markup
    assert letter_markup.to_plain(markup) == text
    assert f"<b>{subject}</b>" in markup
    assert "<b>87%</b>" in markup
    assert "<b>2026-10-30</b>" in markup
    assert "<b>— Зона:</b>" in markup
    assert "<b>• R&amp;D" in markup
    assert "<script>" not in markup
    assert "<b>• Полное второе замечание.</b>" in markup
    assert "<b>" in letter_markup.to_email_html(markup)


def test_plain_text_conversion_stays_plain_for_other_document_types() -> None:
    text = "Subject: note\n• 87% <literal>"
    assert "<b>" not in letter_markup.from_plain(text)
