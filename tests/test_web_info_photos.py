# ruff: noqa: F811
"""Info-owned frames retain ownership, visibility and accepted read-only semantics."""

from __future__ import annotations

from dataclasses import replace

import pytest
from flask.testing import FlaskClient
from test_web_acceptance import админ, стенд  # noqa: F401
from test_web_information_section import _mixed, _section

from src.db.errors import DbError
from src.db.models import InfoRow
from src.db.previews import FindingShots
from src.web import inspections as data


@админ
@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("path", ["/inspections/x", "/inspections?inspection=x"])
def test_info_owned_photos_are_separate_and_read_only(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, lang: str, path: str
) -> None:
    detail = _mixed(monkeypatch, on_review=False)
    detail = replace(
        detail, info=(InfoRow("INF01", "<script>private caption</script>"), InfoRow("INF06", ""))
    )
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: detail)
    calls = []

    def photos(inspection_id, *, reach):
        calls.append((inspection_id, reach))
        return {
            "INF01": FindingShots(("info-photo",), 1),
            "INF06": FindingShots(("photo-only",), 0),
        }

    monkeypatch.setattr(data, "load_info_previews", photos)
    response = стенд.get(f"{path}{'&' if '?' in path else '?'}lang={lang}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    information = _section(html, "data-information")
    violations = _section(html, "data-violations")
    assert len(calls) == 1
    assert 'data-info-photos="INF01"' in information
    assert 'data-info-photos="INF06"' in information
    assert "info-photo" not in violations and "photo-only" not in violations
    assert "measurement-photo" in information and "advice-photo" in information
    assert 'class="ov-card__count">5</div>' in information
    assert "data-zoom" in information and "data-findings-toggle" in information
    assert "<script>private caption</script>" not in html
    assert "&lt;script&gt;private caption&lt;/script&gt;" in information
    assert "/delete" not in information and "/revise" not in information


@админ
@pytest.mark.parametrize("unavailable", [False, True])
def test_missing_info_photos_do_not_render_empty_gallery(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, unavailable: bool
) -> None:
    _mixed(monkeypatch)

    def photos(*_a, **_k):
        if unavailable:
            raise DbError("synthetic unavailable")
        return {"INF01": FindingShots((), 2)}

    monkeypatch.setattr(data, "load_info_previews", photos)
    response = стенд.get("/inspections/x?lang=en")
    assert response.status_code == 200
    information = _section(response.get_data(as_text=True), "data-information")
    assert "data-info-photos=" not in information
    assert "The team works well together" in information
    expected = (
        "Photos for the findings cannot be shown right now: the database did not answer."
        if unavailable
        else "Photos unavailable: 2"
    )
    assert expected in information
