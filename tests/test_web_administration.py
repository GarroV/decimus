"""Раздел «Администрирование» (D639) и состояние подключений (D638, #1251) — без базы.

Двери базы подменены на границе модуля. Проверяется поверхность: кому раздел виден и
открыт, что вид `view.administration` совпадает со вкладками роли, старый адрес
вкладки перенаправляет, «Проверить сейчас» пробует и пишет исход, а цвета строк
выводятся из фактов.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import api_access, dodois_logins, health_store, model_key, ratings_sync
from src.domain.health import LoadFacts, ProbeRow
from src.domain.permissions import MATRIX, SIDE_HQ, role_may
from src.health import checks
from src.web import (
    accounts,
    administration,
    country,
    country_summary,
    journal_screen,
    partner_spaces,
    usage_screen,
)
from src.web import ratings as ratings_screen

РАЗДЕЛ = "/administration"
СЕЙЧАС = datetime.now(UTC)


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    monkeypatch.setattr(api_access, "list_tokens", lambda: ())
    monkeypatch.setattr(model_key, "status", lambda: None)
    записано: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        health_store,
        "probes",
        lambda: {
            "openai": ProbeRow("green", "health.reason.ok", СЕЙЧАС - timedelta(minutes=5)),
            "pointer": ProbeRow("red", "health.reason.rejected", СЕЙЧАС - timedelta(minutes=5)),
        },
    )
    monkeypatch.setattr(
        health_store,
        "loads",
        lambda: {
            "aggregators": LoadFacts(СЕЙЧАС - timedelta(hours=2), False, "glovo: 503"),
            "maps": LoadFacts(СЕЙЧАС - timedelta(hours=2), True, None),
            "learning": None,
            "sheet": None,
        },
    )
    monkeypatch.setattr(dodois_logins, "list_logins", lambda: ())
    monkeypatch.setattr(dodois_logins, "list_invites", lambda limit=30: ())
    monkeypatch.setattr(
        health_store,
        "record",
        lambda code, light, reason, at: записано.append((code, light, reason)),
    )
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        client.записано = записано  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.mark.parametrize(("side", "role"), sorted(MATRIX))
def test_вид_раздела_ровно_у_ролей_с_вкладками(side: str, role: str) -> None:
    tenant = "HQ" if side == SIDE_HQ else "RS"
    учётка = SimpleNamespace(role=role, tenant=tenant)
    assert role_may(role, tenant, "view.administration") == bool(administration.tabs_for(учётка)), (
        f"{side}/{role}: вид раздела и вкладки расходятся"
    )


def test_главный_админ_видит_раздел_и_состояние(главный: FlaskClient) -> None:
    ответ = главный.get(f"{РАЗДЕЛ}?tab=connections")
    page = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert 'class="sadmin__nav"' in page
    assert "Состояние подключений" in page
    # Итог — худший цвет: красный ключ Pointer и упавший сбор агрегаторов.
    assert "shealth__summary--red" in page
    assert "Не работает: 2" in page
    assert "Сбой: glovo: 503" in page
    # Плитки разложены по группам; оба Pointer — в «Рейтингах», ключ и сбор подписаны.
    системное = page.index("Системное: хранилище")
    рейтинги = page.index("Рейтинги и оценки")
    assert системное < page.index("Хранилище кадров") < рейтинги
    assert рейтинги < page.index("Pointer — ключ") < page.index("Pointer — ночной сбор")
    # Ключи — на «Ключах и API» (D650); со статуса пробуемых ключей ведёт «Ключ».
    assert 'id="service-keys"' not in page and "Доступ к API Decimus" not in page
    for код in ("openai", "pointer", "ispring"):
        assert f'href="{РАЗДЕЛ}?tab=keys&amp;key={код}#service-keys"' in page, код
    assert page.count("?tab=keys&amp;key=") == 3, "ссылка «Ключ» только у ключей"
    # Пункт меню у главного админа есть.
    assert f'href="{РАЗДЕЛ}?lang=' in page


def test_раздел_без_вкладки_открывает_первую(главный: FlaskClient) -> None:
    assert главный.get(РАЗДЕЛ).status_code == 200


def test_неизвестная_вкладка_404(главный: FlaskClient) -> None:
    assert главный.get(f"{РАЗДЕЛ}?tab=nope").status_code == 404


def test_старый_адрес_вкладки_перенаправляет(главный: FlaskClient) -> None:
    ответ = главный.get("/users?tab=connections&service=1")
    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith(f"{РАЗДЕЛ}?tab=connections&service=1")


# --- шаг 2 (D640): вкладки по ролям, старый адрес, меню

#: Вкладки роли в порядке столбца. Пусто — раздела у роли нет.
ВКЛАДКИ = {
    ("HQ", "superadmin"): [
        "people",
        "spaces",
        "countries",
        "ratings",
        "journal",
        "usage",
        "connections",
        "keys",
        "dodois",
    ],
    ("HQ", "admin"): ["people", "spaces", "countries", "ratings", "usage"],
    ("HQ", "control"): ["people", "ratings"],
    ("GE", "admin"): ["people", "spaces"],
    ("HQ", "developer"): [],
    ("HQ", "guest"): [],
    ("HQ", "osb"): ["countries"],
    ("GE", "auditor"): [],
}


def _без_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вкладка «Люди» читает перечень из базы: подменяем пустым — тест про вкладки."""
    monkeypatch.setattr(accounts, "everyone", lambda **_: ())
    monkeypatch.setattr(accounts, "spaces", lambda: ())
    monkeypatch.setattr(partner_spaces, "overview", lambda: ())
    monkeypatch.setattr(country, "countries", lambda **_: ())
    monkeypatch.setattr(country_summary, "developers_of", lambda _codes: ({}, {}, False))


def _рейтинги_без_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вкладка «Рейтинги» читает справочники и таблицу контроля: подменяем пустым."""
    monkeypatch.setattr(ratings_screen.read, "countries", lambda: ())
    monkeypatch.setattr(ratings_screen.read, "imports", lambda: ())
    monkeypatch.setattr(ratings_screen.read, "open_issues", lambda: ())
    monkeypatch.setattr(ratings_screen.read, "hard_rules", lambda: ())
    monkeypatch.setattr(ratings_screen.read, "settings", dict)
    monkeypatch.setattr(ratings_screen.read, "layout_rows", lambda: ())
    monkeypatch.setattr(ratings_sync, "states", lambda: ())
    monkeypatch.setattr(ratings_sync, "open_request", lambda: None)


def _вкладки_на_странице(страница: str) -> list[str]:
    return re.findall(r'class="sadmin__tab[^"]*" href="/administration\?tab=(\w+)', страница)


@pytest.mark.parametrize(("tenant", "role"), sorted(ВКЛАДКИ))
def test_каждая_роль_видит_ровно_свои_вкладки(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    _без_базы(monkeypatch)
    ждём = ВКЛАДКИ[(tenant, role)]
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.get(РАЗДЕЛ)
        if not ждём:
            assert ответ.status_code in (403, 404), f"{tenant}/{role}: раздел открылся"
            меню = client.get("/settings").get_data(as_text=True)
            assert f'href="{РАЗДЕЛ}?lang=' not in меню, f"{tenant}/{role}: пункт меню виден"
            continue
        assert ответ.status_code == 200, f"{tenant}/{role}"
        assert _вкладки_на_странице(ответ.get_data(as_text=True)) == ждём
        # Каждая вкладка роли открывается, чужая — нет.
        for вкладка in ("ratings", "journal", "usage", "connections", "keys", "dodois"):
            открылась = client.get(f"{РАЗДЕЛ}?tab={вкладка}")
            if вкладка not in ждём:
                assert открылась.status_code == 404, f"{tenant}/{role}: {вкладка} открылась"


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "superadmin"), ("HQ", "admin")])
def test_вкладки_без_подзаголовков_групп(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    _без_базы(monkeypatch)
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        страница = client.get(РАЗДЕЛ).get_data(as_text=True)
        assert "sadmin__group" not in страница
        assert "Журнал и расход" not in страница
        # Что во вкладке, говорит её название, а не подпись над ней.
        assert ">Люди и доступ</a>" in страница


@pytest.mark.parametrize(
    ("старый", "новый"),
    [
        ("/users", "/administration?tab=people"),
        ("/users?person=me", "/administration?tab=people&person=me"),
        ("/users?q=petr&off=1&lang=en", "/administration?tab=people&q=petr&off=1&lang=en"),
        ("/users?q=%D0%B0%26b", "/administration?tab=people&q=%D0%B0%26b"),
        ("/users?tab=spaces&space_code=GE", "/administration?tab=spaces&space_code=GE"),
        ("/users?tab=journal&view=actions", "/administration?tab=journal&view=actions"),
        ("/users?tab=usage&from=2026-10-01", "/administration?tab=usage&from=2026-10-01"),
    ],
)
def test_старый_адрес_людей_ведёт_в_раздел_с_тем_же_запросом(
    главный: FlaskClient, старый: str, новый: str
) -> None:
    ответ = главный.get(старый)
    assert ответ.status_code == 302
    assert ответ.headers["Location"] == новый


@pytest.mark.parametrize(
    ("tenant", "role"), [("HQ", "developer"), ("HQ", "guest"), ("GE", "auditor")]
)
def test_без_вкладок_старый_адрес_ведёт_в_настройки(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.get("/users?person=me&lang=en")
        assert ответ.status_code == 302
        assert ответ.headers["Location"] == "/settings?lang=en"


@pytest.mark.parametrize(("tenant", "role"), sorted(ВКЛАДКИ))
def test_пункта_пользователи_в_меню_нет_ни_у_кого(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        меню = client.get("/settings").get_data(as_text=True)
        assert 'href="/users?lang=' not in меню, f"{tenant}/{role}"
        assert (f'href="{РАЗДЕЛ}?lang=' in меню) == bool(ВКЛАДКИ[(tenant, role)]), (
            f"{tenant}/{role}"
        )


def test_админ_партнёра_видит_только_своё_пространство(monkeypatch: pytest.MonkeyPatch) -> None:
    _без_базы(monkeypatch)
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (
            partner_spaces.SpaceRow("GE", "Партнёр Г", ("GE",), 2),
            partner_spaces.SpaceRow("AM", "Партнёр А", ("AM",), 2),
            partner_spaces.SpaceRow("HQ", "", (), 4),
        ),
    )
    for client in _стенд(monkeypatch, tenant="GE", role="admin"):
        страница = client.get(f"{РАЗДЕЛ}?tab=spaces").get_data(as_text=True)
        assert "Партнёр Г" in страница
        assert "Партнёр А" not in страница
        assert "Ваше пространство" in страница


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "admin"), ("HQ", "control"), ("GE", "admin")])
def test_журнал_чужой_роли_404_база_не_спрошена(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        assert client.get(f"{РАЗДЕЛ}?tab=journal").status_code == 404


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "control"), ("GE", "admin")])
def test_расход_чужой_роли_404(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        assert client.get(f"{РАЗДЕЛ}?tab=usage").status_code == 404


def test_проверить_сейчас_пробует_и_пишет(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checks, "run_probe", lambda code: ("green", "health.reason.ok"))
    ответ = главный.post(f"{РАЗДЕЛ}/connections/health/openai/check", headers={"Origin": СВОЙ})
    assert ответ.status_code == 200
    assert главный.записано == [("openai", "green", "health.reason.ok")]  # type: ignore[attr-defined]
    assert "Проверено: OpenAI" in ответ.get_data(as_text=True)


def test_проверить_сейчас_только_пробуемое(главный: FlaskClient) -> None:
    for code in ("maps", "backup", "nope"):
        ответ = главный.post(f"{РАЗДЕЛ}/connections/health/{code}/check", headers={"Origin": СВОЙ})
        assert ответ.status_code == 404, code


def test_проверить_сейчас_чужому_происхождению_отказ(главный: FlaskClient) -> None:
    ответ = главный.post(
        f"{РАЗДЕЛ}/connections/health/openai/check", headers={"Origin": "https://evil.example"}
    )
    assert ответ.status_code == 403


def test_проверить_сейчас_не_главному_404(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        ответ = client.post(f"{РАЗДЕЛ}/connections/health/openai/check", headers={"Origin": СВОЙ})
        assert ответ.status_code == 404


# --- каркас вкладки (D653): шапка с заголовком, список без таблицы ---------------------------

#: Вкладки-списки: строки `srow` в `slist`, таблиц нет (`docs/12-web-admin.md`, «Каркас вкладки»).
ВКЛАДКИ_СПИСКОМ = ("countries", "keys", "dodois")


@pytest.mark.parametrize("вкладка", [tab.key for tab in administration.TABS])
def test_каждая_вкладка_с_шапкой_каркаса(monkeypatch: pytest.MonkeyPatch, вкладка: str) -> None:
    """Ломали: «Dodo IS» без `h1.shead__title` и с `<table>` — не как «Страны» и «Ключи»."""
    _без_базы(monkeypatch)
    monkeypatch.setattr(usage_screen, "_read", lambda *_a, **_k: ())
    monkeypatch.setattr(journal_screen.journals, "read_actions", lambda *_a, **_k: ())
    monkeypatch.setattr(journal_screen.journals, "read_logins", lambda *_a, **_k: ())
    monkeypatch.setattr(journal_screen.journals, "journal_people", lambda *_a, **_k: ())
    _рейтинги_без_базы(monkeypatch)
    client = next(_стенд(monkeypatch, tenant="HQ", role="superadmin"))
    ответ = client.get(f"{РАЗДЕЛ}?tab={вкладка}")
    assert ответ.status_code == 200, вкладка
    html = ответ.get_data(as_text=True)
    assert re.search(r'<h1 class="shead__title">[^<]+</h1>', html), (
        f"вкладка {вкладка}: нет h1.shead__title (каркас: шапка с названием вкладки)"
    )
    if вкладка in ВКЛАДКИ_СПИСКОМ:
        assert "<table" not in html, f"вкладка {вкладка}: список — это slist/srow, не таблица"


# --- вкладка «Рейтинги» (D654, #1251, шаг 3) -------------------------------------------------

#: Роли с правом `ratings.manage` и без него (`domain/tenants.may_manage_ratings`).
РЕЙТИНГИ_МОГУТ = [("HQ", "superadmin"), ("HQ", "admin"), ("HQ", "control")]
РЕЙТИНГИ_НЕ_МОГУТ = [("GE", "admin"), ("HQ", "developer"), ("HQ", "guest"), ("HQ", "osb")]


@pytest.mark.parametrize(("tenant", "role"), РЕЙТИНГИ_МОГУТ)
def test_рейтинги_видны_тем_у_кого_ratings_manage(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    _без_базы(monkeypatch)
    _рейтинги_без_базы(monkeypatch)
    client = next(_стенд(monkeypatch, tenant=tenant, role=role))
    ответ = client.get(f"{РАЗДЕЛ}?tab=ratings")
    assert ответ.status_code == 200
    assert "ratings" in _вкладки_на_странице(client.get(РАЗДЕЛ).get_data(as_text=True))


@pytest.mark.parametrize(("tenant", "role"), РЕЙТИНГИ_НЕ_МОГУТ)
def test_рейтинги_без_права_404(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str) -> None:
    _без_базы(monkeypatch)
    _рейтинги_без_базы(monkeypatch)
    client = next(_стенд(monkeypatch, tenant=tenant, role=role))
    assert client.get(f"{РАЗДЕЛ}?tab=ratings").status_code == 404
    assert client.get(f"{РАЗДЕЛ}?tab=ratings&block=rules").status_code == 404


def test_рейтинги_блок_открывает_панель_неизвестный_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _рейтинги_без_базы(monkeypatch)
    client = next(_стенд(monkeypatch, tenant="HQ", role="control"))
    список = client.get(f"{РАЗДЕЛ}?tab=ratings").get_data(as_text=True)
    assert "sdrawer" not in список and 'id="ratings-rules"' in список
    панель = client.get(f"{РАЗДЕЛ}?tab=ratings&block=rules").get_data(as_text=True)
    assert "sdrawer" in панель and 'action="/ratings/hard-rules' in панель
    assert client.get(f"{РАЗДЕЛ}?tab=ratings&block=nope").status_code == 404


def test_старый_адрес_загрузок_ведёт_во_вкладку(monkeypatch: pytest.MonkeyPatch) -> None:
    client = next(_стенд(monkeypatch, tenant="HQ", role="control"))
    ответ = client.get("/ratings/imports?lang=en")
    assert ответ.status_code == 302
    assert ответ.headers["Location"] == "/administration?tab=ratings&lang=en"
