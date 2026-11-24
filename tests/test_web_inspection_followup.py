# ruff: noqa: F811 — fixture imported from test_web_app
"""Подпись дополнения читаема и при внутреннем UUID-логине новой учётки."""

from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401
from web_harness import Учётка

from src.web import auth
from src.web import inspection_followup as work
from src.web import inspections as data


@pytest.mark.parametrize(
    ("name", "email", "login", "expected"),
    [
        (" Olivia Hart ", "olivia@example.org", "u-internal", "Olivia Hart"),
        ("  ", "olivia@example.org", "u-internal", "olivia@example.org"),
        (None, None, "legacy-auditor", "legacy-auditor"),
        ("A" * 220, "olivia@example.org", "u-internal", "A" * 200),
    ],
)
def test_readable_author(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    name: str | None,
    email: str | None,
    login: str,
    expected: str,
) -> None:
    account = Учётка(login=login, display_name=name, email=email)
    monkeypatch.setattr(auth, "current_account", lambda: account)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))
    written: dict[str, Any] = {}

    def append(_inspection: str, **values: Any) -> str:
        written.update(values)
        return "entry"

    monkeypatch.setattr(work.store, "append", append)
    response = стенд.post(
        "/inspections/11111111-1111-1111-1111-111111111111/work?lang=ru",
        data={"body": "Работы выполнены"},
        headers={"Origin": "http://localhost"},
    )
    assert response.status_code == 303
    assert written["author"] == expected
