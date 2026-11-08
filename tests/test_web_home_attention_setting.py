"""Пиццерии в «Требует внимания» на главной — за настройкой сети, выкл по умолчанию (D728)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_web_overview import снимок
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import service_settings
from src.db.errors import DbError
from src.domain import features
from src.settings_read import BooleanSetting, SettingsUnavailable
from src.web import home_board
from src.web import overview as overview_data
from src.web.texts import t as _t

PATH = "/administration/home/settings"
ROWS = "критических нарушений: 2"


def _saved(enabled: bool) -> BooleanSetting:
    now = datetime.now(UTC)
    return BooleanSetting(enabled, now, "director", now)


@pytest.fixture
def store(monkeypatch):
    values = {"saved": None, "writes": []}
    monkeypatch.setattr(features, "read_boolean", lambda key: values["saved"])
    monkeypatch.setattr(
        service_settings,
        "set_home_attention_units",
        lambda enabled, *, actor: values["writes"].append((enabled, actor)),
    )
    return values


def _home(client, monkeypatch, data=None) -> str:
    monkeypatch.setattr(overview_data, "load", lambda **_: data or снимок())
    monkeypatch.setattr(home_board, "kinds_for", lambda _who: ())
    response = client.get("/overview?lang=ru")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_rows_hidden_by_default_and_card_gone(monkeypatch, store):
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        page = _home(client, monkeypatch)
    assert ROWS not in page
    assert _t("overview.attention.hint", "ru") not in page
    assert _t("home.attention.title", "ru") not in page  # D398: пустая карточка не показывается


def test_rows_shown_when_on(monkeypatch, store):
    store["saved"] = _saved(True)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        page = _home(client, monkeypatch)
    assert ROWS in page
    assert _t("home.attention.title", "ru") in page


def test_off_keeps_task_stickers(monkeypatch, store):
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(overview_data, "load", lambda **_: снимок())
        monkeypatch.setattr(home_board, "kinds_for", lambda _who: (home_board.REVIEW,))
        monkeypatch.setattr(home_board, "load_counts", lambda *_, **__: home_board.Counts(review=2))
        page = client.get("/overview?lang=ru").get_data(as_text=True)
    assert "Проверок ждут приёмки: 2" in page
    assert ROWS not in page


def test_unreadable_setting_is_off(monkeypatch):
    def broken(key):
        raise SettingsUnavailable("OperationalError")

    monkeypatch.setattr(features, "read_boolean", broken)
    assert features.home_attention_units_enabled() is False


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_admin_toggles_and_sees_tab(monkeypatch, store, role):
    подменить_двери(monkeypatch, tenant="HQ", role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for value in ("1", "0"):
            response = client.post(PATH, data={"attention_units": value}, headers={"Origin": СВОЙ})
            assert response.status_code == 303
        page = client.get("/administration?tab=home&lang=en")
        assert page.status_code == 200
        assert "Show pizzerias" in page.get_data(as_text=True)
    assert store["writes"] == [(True, "director"), (False, "director")]


@pytest.mark.parametrize(
    ("tenant", "role"),
    [("HQ", "developer"), ("HQ", "control"), ("HQ", "osb"), ("HQ", "guest"), ("RS", "admin")],
)
def test_other_roles_cannot_see_or_flip(monkeypatch, store, tenant, role):
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert client.get("/administration?tab=home").status_code == 404
        response = client.post(PATH, data={"attention_units": "1"}, headers={"Origin": СВОЙ})
        assert response.status_code in {403, 404}
    assert store["writes"] == []


def test_bad_value_foreign_origin_and_failed_save(monkeypatch, store):
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert client.post(PATH, data={"attention_units": "1"}).status_code == 403
        bad = client.post(PATH, data={"attention_units": "x"}, headers={"Origin": СВОЙ})
        assert bad.status_code == 400

        def fail(enabled, *, actor):
            raise DbError("unavailable")

        monkeypatch.setattr(service_settings, "set_home_attention_units", fail)
        failed = client.post(PATH, data={"attention_units": "1"}, headers={"Origin": СВОЙ})
        assert failed.status_code == 503
    assert store["writes"] == []
