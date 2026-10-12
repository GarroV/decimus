"""Аудитория маршрута: умолчание «закрыто» для партнёра (аудит 12.10, F-004).

Проверка стоит и на сборке приложения (`route_audience.check_audiences`), и здесь:
тест держит сам реестр, а поведенческая половина — что заслон по отметке
действительно закрывает партнёру маршрут, которого нет ни в одном списке.
Приложение собирается оснасткой веба без базы.
"""

from __future__ import annotations

import pytest
from web_harness import войти, подменить_двери, собрать

from src.domain.tenants import HQ_TENANT
from src.web import route_audience
from src.web.errors import SectionRegistryError
from src.web.route_audience import (
    ALL_SPACES,
    HQ_ONLY,
    Audience,
    audience_of,
    check_audiences,
)

PARTNER = "ge"
#: Страница-заглушка «Календарь»: без данных и без базы, раздел не `hq_only`.
OPEN_PAGE = "/calendar"


def _hello() -> str:
    return "ok"


def _app(monkeypatch: pytest.MonkeyPatch, tenant: str = HQ_TENANT):
    подменить_двери(monkeypatch, tenant=tenant, role="admin")
    return собрать(tenant=tenant)


def test_every_endpoint_has_an_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    names = {rule.endpoint for rule in app.url_map.iter_rules()}
    unmarked = sorted(name for name in names if audience_of(name) is None)
    assert not unmarked, f"маршруты без отметки аудитории (src/web/route_audience.py): {unmarked}"
    check_audiences(app)


def test_unmarked_endpoint_fails_with_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    app.add_url_rule("/zzz-new", endpoint="zzz_new", view_func=_hello)
    with pytest.raises(SectionRegistryError, match="нет отметки аудитории: zzz_new"):
        check_audiences(app)


def test_mark_of_missing_endpoint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    monkeypatch.setattr(route_audience, "HQ_ONLY", HQ_ONLY | {"ghost_endpoint"})
    with pytest.raises(SectionRegistryError, match="которых в приложении нет: ghost_endpoint"):
        check_audiences(app)


def test_endpoint_in_two_audiences_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    monkeypatch.setattr(route_audience, "HQ_ONLY", HQ_ONLY | {"overview"})
    with pytest.raises(SectionRegistryError, match="двух аудиториях сразу: overview"):
        check_audiences(app)


def test_all_spaces_under_hq_only_section_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    # `country` — маршрут `/country/<code>`, раздел «Страна» только для УК.
    monkeypatch.setattr(route_audience, "HQ_ONLY", HQ_ONLY - {"country"})
    monkeypatch.setattr(route_audience, "ALL_SPACES", ALL_SPACES | {"country"})
    with pytest.raises(SectionRegistryError, match="под разделом только для УК: country"):
        check_audiences(app)


def test_partner_gets_404_on_unmarked_endpoint_and_hq_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for tenant, expected in ((PARTNER, 404), (HQ_TENANT, 200)):
        app = _app(monkeypatch, tenant)
        app.add_url_rule("/zzz-new", endpoint="zzz_new", view_func=_hello)
        client = app.test_client()
        assert войти(client).status_code == 302
        assert client.get("/zzz-new").status_code == expected, tenant


def test_partner_passes_on_all_spaces_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, PARTNER)
    app.add_url_rule("/zzz-open", endpoint="zzz_open", view_func=_hello)
    monkeypatch.setattr(route_audience, "ALL_SPACES", ALL_SPACES | {"zzz_open"})
    client = app.test_client()
    assert войти(client).status_code == 302
    assert client.get("/zzz-open").status_code == 200
    assert client.get(OPEN_PAGE).status_code == 200


def test_partner_gets_404_on_hq_only_endpoint_even_outside_hq_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, PARTNER)
    app.add_url_rule("/zzz-hq", endpoint="zzz_hq", view_func=_hello)
    monkeypatch.setattr(route_audience, "HQ_ONLY", HQ_ONLY | {"zzz_hq"})
    client = app.test_client()
    assert войти(client).status_code == 302
    assert client.get("/zzz-hq").status_code == 404
    assert audience_of("zzz_hq") is Audience.HQ_ONLY
