"""The inspection UI asks for a plan for every violation, independently of grade."""

from dataclasses import replace

import pytest
from test_web_app import карточка, шапка
from web_harness import войти, подменить_двери, собрать

from src.web import action_plans
from src.web import inspections as data
from src.web.texts import t


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("missing_country", [False, True])
@pytest.mark.parametrize(
    ("level", "grade", "needed"),
    [
        ("D1", "A", True),
        ("D1", "B", True),
        ("D1", "C", True),
        ("D2", "B", True),
        ("D3", "D", True),
        ("D0", "A", False),
        ("R", "A", False),
    ],
)
def test_card_plan_hint_uses_violation_counts_not_grade(
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
    missing_country: bool,
    level: str,
    grade: str,
    needed: bool,
) -> None:
    head = шапка(tenant_code="HQ", grade=grade, findings_count=1)
    base = карточка(head)
    detail = replace(base, counts={level: 1}, findings=(replace(base.findings[0], level=level),))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: detail)
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(action_plans, "card_plan", lambda *_a: (None, True))
    monkeypatch.setattr(action_plans, "unit_without_country", lambda *_a: missing_country)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        response = client.get(f"/inspections/{head.id}?lang={lang}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    if needed and missing_country:
        assert t("card.plan.no_country", lang) in html
        assert t("card.plan.request_submit", lang) not in html
        return
    assert t("card.plan.no_country", lang) not in html
    expected = "card.plan.request_hint_needed" if needed else "card.plan.request_hint"
    unexpected = "card.plan.request_hint" if needed else "card.plan.request_hint_needed"
    assert t(expected, lang) in html
    assert t(unexpected, lang) not in html
