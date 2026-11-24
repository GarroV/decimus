"""Удаление разрешено только главному админу и не выходит за выбранное пространство."""

from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_users_scope import (
    ЗАГОЛОВКИ,
)
from test_web_users_scope import (
    админ_уК as админ_уК,
)
from test_web_users_scope import (
    база as база,
)
from test_web_users_scope import (
    главный as главный,
)

from src.db import user_deletion


@pytest.mark.parametrize("action", ["delete", "cancel-deletion"])
def test_only_superadmin(
    админ_уК: FlaskClient, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    def forbidden_call(*args: Any) -> bool:
        pytest.fail("non-superadmin reached the deletion writer")

    monkeypatch.setattr(user_deletion, "schedule", forbidden_call)
    monkeypatch.setattr(user_deletion, "cancel", forbidden_call)
    response = админ_уК.post(
        f"/users/{action}", data={"login": "gia", "tenant": "GE"}, headers=ЗАГОЛОВКИ
    )
    assert response.status_code == 403


def test_selected_space_cannot_be_forged(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = []
    monkeypatch.setattr(user_deletion, "schedule", lambda *args: called.append(args))
    response = главный.post(
        "/users/delete?tab=spaces&space_code=GE",
        data={"login": "anahit", "tenant": "AM"},
        headers=ЗАГОЛОВКИ,
    )
    assert response.status_code == 403
    assert called == []


def test_superadmin_deletes_database_target(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = []
    monkeypatch.setattr(user_deletion, "schedule", lambda *args: called.append(args) or True)
    response = главный.post(
        "/users/delete?tab=spaces&space_code=GE",
        data={"login": "gia", "tenant": "GE"},
        headers=ЗАГОЛОВКИ,
    )
    assert response.status_code == 200
    assert called[0][1] == "id-gia"
