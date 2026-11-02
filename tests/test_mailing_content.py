"""Template variables cannot evaluate expressions, hide missing data or inject headers."""

import pytest

from src.domain import mailing_content as mc


@pytest.mark.parametrize("kind", mc.KINDS)
@pytest.mark.parametrize("lang", mc.LANGS)
def test_defaults_render_only_given_facts(kind: str, lang: str) -> None:
    heading, body = mc.render(kind, *mc.defaults(kind, lang), mc.sample(kind))
    assert heading and body and "{" not in body


@pytest.mark.parametrize(
    "body",
    ["{unknown}", "{unit.__class__}", "{unit[0]}", "{unit!r}", "{unit:>5}", "{", "", "x\x00"],
)
def test_invalid_templates_rejected(body: str) -> None:
    with pytest.raises(ValueError):
        mc.check("plan", "Plan {unit}", body)


def test_header_does_not_accept_multiline_variables_or_values() -> None:
    with pytest.raises(ValueError):
        mc.check("document", "{document_body}", "{title}")
    with pytest.raises(ValueError):
        mc.render("plan", "{unit}", "{due}", {"unit": "one\r\nBcc: other@example.com"})


def test_html_stays_plain_text_before_the_existing_sanitizer() -> None:
    assert (
        mc.render("plan", "Plan", "{unit}", {"unit": "<script>bad()</script>"})[1]
        == "<script>bad()</script>"
    )


@pytest.mark.parametrize("lang", mc.LANGS)
def test_inspection_builtin_preview_subject_matches_existing_actual_gmail(lang: str) -> None:
    from src.web.google_mail import draft_subject

    values = mc.sample("inspection")
    subject, _ = mc.render("inspection", *mc.defaults("inspection", lang), values)
    assert subject == draft_subject(city=values["city"], date=values["date"], lang=lang)
