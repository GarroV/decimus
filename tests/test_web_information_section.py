# ruff: noqa: F811
"""Information belongs outside violations on both inspection surfaces."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from flask.testing import FlaskClient
from test_web_acceptance import _лист, _приёмка, админ, стенд  # noqa: F401
from test_web_app import ТЕНАНТ, карточка, шапка

from src.db.models import InfoRow, InspectionDetail
from src.db.previews import FindingShots
from src.report.info_titles import FOUND
from src.web import inspections as data


def _section(html: str, marker: str) -> str:
    section = re.search(rf"<section[^>]*{marker}[^>]*>(.*?)</section>", html, re.S)
    assert section is not None, marker
    return section.group(1)


def _mixed(monkeypatch: pytest.MonkeyPatch, *, on_review: bool = True) -> InspectionDetail:
    _приёмка(monkeypatch, ждёт=on_review)
    _лист(monkeypatch)
    detail = карточка(шапка(on_review=on_review, tenant_code=ТЕНАНТ))
    base = detail.findings[0]
    violations = tuple(
        replace(
            base,
            id=f"violation-{level}",
            n=n,
            level=level,
            text=f"Finding {level}",
            comment="Clean the named object" if level == "D1" else None,
        )
        for n, level in enumerate(("D1", "D2", "D3"), 1)
    )
    findings = (
        *violations,
        replace(
            base,
            id="measurement",
            n=4,
            level="D0",
            code="INF10",
            text="Freezer display: -22 C",
            reading_c=-22,
            comment=None,
        ),
        replace(
            base,
            id="advice",
            n=5,
            level="R",
            code="NOTE",
            text="Improve the delivery handoff",
            comment=None,
        ),
    )
    detail = replace(
        detail,
        inspection=replace(detail.inspection, findings_count=5),
        findings=findings,
        counts={"D1": 1, "D2": 1, "D3": 1, "D0": 1, "R": 1},
        info=(
            InfoRow("INF01", "The team works well together"),
            InfoRow("INF06", "Improve stock rotation"),
        ),
    )
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: detail)
    monkeypatch.setattr(
        data.info_titles,
        "titles",
        lambda *_a, **_k: (
            {"INF01": "Strengths", "INF06": "Areas for improvement"},
            FOUND,
        ),
    )
    monkeypatch.setattr(
        data,
        "load_previews",
        lambda *_a, **_k: {
            "measurement": FindingShots(shown=("measurement-photo",), missing=0),
            "advice": FindingShots(shown=("advice-photo",), missing=0),
        },
    )
    return detail


@админ
@pytest.mark.parametrize("path", ["/inspections/x", "/inspections?inspection=x"])
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_information_and_recommendations_are_not_violations(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    lang: str,
) -> None:
    _mixed(monkeypatch)
    joiner = "&" if "?" in path else "?"
    html = стенд.get(f"{path}{joiner}lang={lang}").get_data(as_text=True)
    violations = _section(html, "data-violations")
    information = _section(html, "data-information")

    for level in ("D1", "D2", "D3"):
        assert f"Finding {level}" in violations
        assert f"Finding {level}" not in information
    for text in (
        "Freezer display: -22 C",
        "Improve the delivery handoff",
        "The team works well together",
        "Improve stock rotation",
        "Clean the named object",
    ):
        assert text in information
        assert text not in violations
    for finding_id in ("measurement", "advice", "violation-D1", "violation-D2", "violation-D3"):
        assert html.count(f'data-finding="{finding_id}"') == 1
    for text in (
        "The team works well together",
        "Improve stock rotation",
        "Clean the named object",
    ):
        assert html.count(text) == 1
    assert "Strengths" in information and "Areas for improvement" in information
    assert ">D0<" not in html and ">R<" not in html
    assert 'class="ov-card__count">3</div>' in violations
    assert 'class="ov-card__count">5</div>' in information
    assert "measurement-photo" in information and "advice-photo" in information
    assert "data-findings-toggle" in information and "data-findings-toggle" not in violations
    assert "/findings/measurement/delete" in information
    assert "/findings/advice/delete" in information
    assert "/findings/measurement/revise" not in information
    assert "/findings/advice/revise" not in information


@админ
def test_accepted_information_is_read_only(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mixed(monkeypatch, on_review=False)
    html = стенд.get("/inspections/x").get_data(as_text=True)
    information = _section(html, "data-information")
    assert "measurement-photo" in information
    assert "data-del" not in information and "data-proofread-form" not in information
    assert "/delete" not in information and "/revise" not in information


@админ
def test_missing_feedback_is_not_invented_and_information_only_is_not_a_violation(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = _mixed(monkeypatch)
    detail = replace(detail, findings=(detail.findings[3],), info=(), counts={"D0": 1})
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: detail)
    html = стенд.get("/inspections/x?lang=en").get_data(as_text=True)
    violations = _section(html, "data-violations")
    information = _section(html, "data-information")
    assert "No violations were recorded." in violations
    assert 'class="ov-card__count">0</div>' in violations
    assert "Freezer display: -22 C" in information
    assert "The team works well together" not in html
    assert "Improve stock rotation" not in html
    assert "Clean the named object" not in html
