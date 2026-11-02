"""Real login/POST/redirect/GET with persisted adapter boundary replaced."""

from datetime import UTC, datetime

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import action_plans, service_settings
from src.db.errors import DbError
from src.domain import features
from src.domain.permissions import Actor, can
from src.settings_read import BooleanSetting, SettingsUnavailable

PATH = "/administration/plans/settings"


@pytest.fixture
def store(monkeypatch):
    values = {"saved": None, "writes": [], "reads": 0}
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")

    def read(key):
        values["reads"] += 1
        return values["saved"]

    def save(enabled, *, actor):
        values["writes"].append((enabled, actor))
        now = datetime.now(UTC)
        values["saved"] = BooleanSetting(enabled, now, actor, now)

    monkeypatch.setattr(features, "read_boolean", read)
    monkeypatch.setattr(service_settings, "set_action_plans", save)
    monkeypatch.setattr(
        action_plans, "list_requests", lambda **kw: action_plans.PlanList((), False)
    )
    return values


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_manual_on_off_flow_and_audit(monkeypatch, store, role):
    calls = подменить_двери(monkeypatch, tenant="HQ", role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for value, enabled in [("1", True), ("0", False), ("1", True)]:
            response = client.post(PATH, data={"enabled": value}, headers={"Origin": СВОЙ})
            assert response.status_code == 303
            before = store["reads"]
            page = client.get(response.headers["Location"])
            assert page.status_code == 200
            assert store["reads"] - before == 1, "one snapshot per render, not N+1 connects"
            html = page.get_data(as_text=True)
            assert (f'value="{value}" selected') in html
            assert features.action_plans_enabled() is enabled
            assert bool(can(Actor("HQ", "admin"), "plan.manage")) is enabled
        actions = [r for r in calls["action_journal"] if r["action"] == "action_plan_setting"]
        assert len(actions) == 3
        assert {a["outcome"] for a in actions} == {"303"}
        assert store["writes"] == [(True, "director"), (False, "director"), (True, "director")]


@pytest.mark.parametrize(
    ("tenant", "role"),
    [
        ("HQ", "developer"),
        ("HQ", "control"),
        ("HQ", "osb"),
        ("HQ", "guest"),
        ("RS", "admin"),
    ],
)
def test_other_roles_cannot_read_or_toggle(monkeypatch, store, tenant, role):
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert client.get("/administration?tab=plans").status_code == 404
        assert client.post(PATH, data={"enabled": "1"}, headers={"Origin": СВОЙ}).status_code in {
            403,
            404,
        }
    assert store["writes"] == []


def test_origin_validation_input_and_failed_save(monkeypatch, store):
    calls = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for headers in [{}, {"Origin": "https://foreign.invalid"}]:
            assert client.post(PATH, data={"enabled": "1"}, headers=headers).status_code == 403
        assert (
            client.post(PATH, data={"enabled": "garbage"}, headers={"Origin": СВОЙ}).status_code
            == 400
        )
        assert not store["writes"]

        def fail(*args, **kwargs):
            raise DbError("unavailable")

        monkeypatch.setattr(service_settings, "set_action_plans", fail)
        failed = client.post(PATH, data={"enabled": "1"}, headers={"Origin": СВОЙ})
        assert failed.status_code == 503
        assert "Настройка не сохранена" in failed.get_data(as_text=True)
        assert calls["action_journal"][-1]["outcome"] == "503"


def test_read_failure_is_bounded_and_bilingual_ui(monkeypatch, store):
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    reads = []

    def broken(key):
        reads.append(key)
        raise SettingsUnavailable("unavailable")

    monkeypatch.setattr(features, "read_boolean", broken)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for lang, expected in [
            ("ru", "Настройку не удалось прочитать"),
            ("en", "The setting could not be read"),
        ]:
            before = len(reads)
            response = client.get("/administration?tab=plans&lang=" + lang)
            assert response.status_code == 200
            assert expected in response.get_data(as_text=True)
            assert len(reads) - before == 1


def test_english_post_keeps_language(monkeypatch, store):
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        html = client.get("/administration?tab=plans&lang=en").get_data(as_text=True)
        assert "/administration/plans/settings?lang=en" in html
        response = client.post(PATH + "?lang=en", data={"enabled": "1"}, headers={"Origin": СВОЙ})
        assert response.status_code == 303
        assert "lang=en" in response.headers["Location"]
        page = client.get(response.headers["Location"]).get_data(as_text=True)
        assert "Action-plan settings" in page
