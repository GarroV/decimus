"""D440: роли УК — таблица «роль × действие → можно / нельзя» по настоящим заслонам.

Ядро (права доступа): ошибка здесь не кричит. Гость, которому открыта одна запись,
молча меняет сеть; бизнес-девелопер с правом на методику молча правит оценку.
Поэтому таблица одна на весь продукт и прогоняется по настоящим заслонам:
маршрутам веба (`before_request` и проверки маршрутов), матрице MCP, правилу
пространства бота и правилу «кто кого ведёт». Двери базы подменены на границе
модуля и пишут вызовы: «можно» — это «дверь записи позвана», «нельзя» — отказ и
ни одного вызова.

Роли УК (D440): главный админ `superadmin`, админ `admin`, бизнес-девелопер
`developer` (вместо аудитора УК), контроль `control` (D420), гость `guest` — всё
на чтение. Сторона партнёра (`admin`, `auditor`) не менялась, и таблица держит это.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from test_web_app import ПУСТАЯ_СЕТЬ, карточка, шапка
from web_harness import СВОЙ, войти, охват_без_базы, подменить_двери, собрать
from werkzeug.routing import IntegerConverter

from src.bot.access import space_from
from src.db import bot_links
from src.db.bot_links import Binding, Standing
from src.domain.tenants import may_manage_ratings
from src.mcp.catalogue import (
    KIND_CHECKLIST,
    KIND_CHECKLIST_SOURCE,
    KIND_IMPORT,
    KIND_INSPECTIONS,
    KIND_RATINGS,
    KIND_RATINGS_READ,
    KIND_RETRACTION,
)
from src.mcp.policy import permits
from src.web import accounts, action_plans, auth, home_board, partner_spaces, revision
from src.web import country as country_data
from src.web import inspections as data
from src.web import overview as overview_data
from src.web import ratings as ratings_screen
from src.web.access_policy import grantable_roles, manages_spaces, may_grant, scope_of

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ID = "11111111-1111-1111-1111-111111111111"

УК_РОЛИ = ("superadmin", "admin", "developer", "control", "guest")
ПАРТНЁР = "GE"


# --- таблица: действие → кому в УК можно ---------------------------------------
#
# Одна строка на действие. Что не названо в строке, то нельзя: новая роль или
# новое действие, не внесённые сюда, видны как отказ, а не как тихий доступ.

#: Работать с сервисом в полном объёме: проверки, приёмка, снятие, перенос.
РАБОТАЮТ = {"superadmin", "admin", "developer"}
ТОЛЬКО_АДМИНЫ = {"superadmin", "admin"}

ДЕЙСТВИЯ_ВЕБА: dict[str, set[str]] = {
    # проверка: снятие / перенос / приёмка / правка записи
    "retract": РАБОТАЮТ,
    "move": РАБОТАЮТ,
    "accept": РАБОТАЮТ,
    "revise": РАБОТАЮТ,
    # главный чек-лист и неглавные: нужен настоящий стор, см. test_web_master_checklist.py
    # люди: завести сотрудника УК
    "user_add_developer": ТОЛЬКО_АДМИНЫ,
    # пространства партнёров и страны
    "space_add": ТОЛЬКО_АДМИНЫ,
}


def _двери(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Двери записи и чтения на границе модуля; пишут, кого звали."""
    зовы: dict[str, list[Any]] = {
        "retract_card": [],
        "accept_card": [],
        "move_card": [],
        "revise_card": [],
        "add": [],
        "space": [],
    }
    деталь = карточка(шапка(on_review=True, tenant_code="HQ", origin="field"))
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_: ())
    monkeypatch.setattr(overview_data, "load", lambda **_: ПУСТАЯ_СЕТЬ)
    monkeypatch.setattr(country_data, "countries", lambda **_: ())
    monkeypatch.setattr(action_plans.plans, "list_requests", lambda **_: action_plans.EMPTY)
    monkeypatch.setattr(ratings_screen, "render_summary", lambda *_a, **_k: "<p>сводка</p>")
    for имя in ("retract_card", "accept_card", "move_card"):

        def дверь(*_a: object, _имя: str = имя, **_k: object) -> SimpleNamespace:
            зовы[_имя].append(1)
            return SimpleNamespace(photos_purged=0)

        monkeypatch.setattr(data, имя, дверь)
    monkeypatch.setattr(revision, "revise_card", lambda *_a, **_k: зовы["revise_card"].append(1))

    def добавить(login: str, *, tenant: str, role: str = "auditor") -> accounts.Added:
        зовы["add"].append((tenant, role))
        return accounts.Added(login=login, role=role, password="одноразовый-пароль-24-знака")

    def завести(code: str, *, name: str, countries: tuple[str, ...]) -> Any:
        зовы["space"].append(code)
        return partner_spaces.SpaceRow(code=code, name=name, countries=countries, people=0)

    monkeypatch.setattr(accounts, "everyone", lambda *, tenant: ())
    monkeypatch.setattr(accounts, "spaces", lambda: ("GE", "HQ"))
    monkeypatch.setattr(accounts, "add", добавить)
    monkeypatch.setattr(partner_spaces, "create_partner_space", завести)
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (partner_spaces.SpaceRow("HQ", "", (), 0),),
    )
    monkeypatch.setattr(bot_links, "live_bindings", dict)
    monkeypatch.setattr(auth, "reach_of", охват_без_базы)
    return зовы


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    return _двери(monkeypatch)


def _войти(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _действие(client: FlaskClient, действие: str) -> Any:
    """Выполнить действие так, как его делает браузер: POST со своей страницы."""
    запросы: dict[str, tuple[str, dict[str, str]]] = {
        "retract": (f"/inspections/{ID}/retract", {"reason": "дубль"}),
        "move": (
            f"/inspections/{ID}/move",
            {"date": "2026-10-01", "unit": "u", "reason": "не та точка"},
        ),
        "accept": (f"/inspections/{ID}/accept", {}),
        "revise": (
            f"/inspections/{ID}/findings/f1/revise",
            {"code": "CLN05", "level": "D2", "text": "x"},
        ),
        "user_add_developer": (
            "/users/add",
            {"login": "newbie", "tenant": "HQ", "role": "developer"},
        ),
        "space_add": ("/users/spaces/add", {"code": "AM", "name": "Партнёр", "countries": "AM"}),
    }
    путь, форма = запросы[действие]
    return client.post(путь, data=форма, headers=ЗАГОЛОВКИ)


#: Что считается «дверь позвана»; для действий без двери записи — не 403 заслона.
_ДВЕРЬ = {
    "retract": "retract_card",
    "move": "move_card",
    "accept": "accept_card",
    "revise": "revise_card",
    "user_add_developer": "add",
    "space_add": "space",
}


def _допущен(ответ: Any, зовы: dict[str, list[Any]], действие: str) -> bool:
    дверь = _ДВЕРЬ.get(действие)
    if дверь is not None:
        return bool(зовы[дверь])
    return ответ.status_code not in (403, 404)


@pytest.mark.parametrize("действие", sorted(ДЕЙСТВИЯ_ВЕБА))
@pytest.mark.parametrize("роль", УК_РОЛИ)
def test_уК_роль_на_действие(
    monkeypatch: pytest.MonkeyPatch,
    зовы: dict[str, list[Any]],
    роль: str,
    действие: str,
) -> None:
    ожидание = роль in ДЕЙСТВИЯ_ВЕБА[действие]
    клиент = next(_войти(monkeypatch, tenant="HQ", role=роль))

    ответ = _действие(клиент, действие)

    assert _допущен(ответ, зовы, действие) is ожидание, (
        f"{роль}@HQ × {действие}: ожидалось {'можно' if ожидание else 'нельзя'}, "
        f"ответ {ответ.status_code}, вызовы {зовы}"
    )
    if not ожидание:
        assert ответ.status_code in (403, 404), ответ.status_code


# --- сторона партнёра не менялась ----------------------------------------------

ПАРТНЁР_НЕЛЬЗЯ = ("retract", "move", "user_add_developer", "space_add")


@pytest.mark.parametrize("действие", ПАРТНЁР_НЕЛЬЗЯ)
@pytest.mark.parametrize("роль", ["admin", "auditor"])
def test_партнёр_по_прежнему_не_может(
    monkeypatch: pytest.MonkeyPatch,
    зовы: dict[str, list[Any]],
    роль: str,
    действие: str,
) -> None:
    клиент = next(_войти(monkeypatch, tenant=ПАРТНЁР, role=роль))

    ответ = _действие(клиент, действие)

    assert not _допущен(ответ, зовы, действие), f"{роль}@{ПАРТНЁР} × {действие} прошёл"


def test_админ_партнёра_заводит_сотрудника_и_админа_как_раньше(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    клиент = next(_войти(monkeypatch, tenant=ПАРТНЁР, role="admin"))

    for роль in ("auditor", "admin"):
        ответ = клиент.post(
            "/users/add",
            data={"login": f"p-{роль}", "tenant": ПАРТНЁР, "role": роль},
            headers=ЗАГОЛОВКИ,
        )
        assert ответ.status_code == 200, ответ.data[:200]
    assert зовы["add"] == [(ПАРТНЁР, "auditor"), (ПАРТНЁР, "admin")]


def test_админ_партнёра_не_заводит_роли_уК(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    клиент = next(_войти(monkeypatch, tenant=ПАРТНЁР, role="admin"))

    for роль in ("developer", "guest", "superadmin", "control"):
        клиент.post(
            "/users/add",
            data={"login": "x", "tenant": ПАРТНЁР, "role": роль},
            headers=ЗАГОЛОВКИ,
        )

    assert зовы["add"] == []


def test_сотрудник_партнёра_не_вычитывает(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    клиент = next(_войти(monkeypatch, tenant=ПАРТНЁР, role="auditor"))

    ответ = _действие(клиент, "accept")

    assert ответ.status_code in (403, 404)
    assert зовы["accept_card"] == []


# --- кого админ УК ведёт на экране «Пользователи» ------------------------------


def test_админ_уК_назначает_админов_но_не_главного() -> None:
    охват = scope_of("admin", "HQ")
    assert охват is not None

    разрешено = {
        r
        for r in ("superadmin", "admin", "developer", "control", "guest", "osb")
        if may_grant(охват, tenant="HQ", role=r)
    }

    assert разрешено == {"admin", "developer", "control", "guest", "osb"}


def test_главный_админ_назначает_любые_роли_уК() -> None:
    охват = scope_of("superadmin", "HQ")
    assert охват is not None

    assert set(grantable_roles(охват, "HQ")) == {
        "superadmin",
        "admin",
        "developer",
        "control",
        "guest",
        "osb",
    }


def test_аудитора_в_уК_больше_нет() -> None:
    """D440: аудитор УК стал бизнес-девелопером; партнёрский аудитор остаётся."""
    охват = scope_of("superadmin", "HQ")
    assert охват is not None
    assert "auditor" not in grantable_roles(охват, "HQ")
    assert "auditor" in grantable_roles(охват, ПАРТНЁР)


@pytest.mark.parametrize("роль", ["developer", "guest", "control"])
def test_девелопер_гость_контроль_людей_уК_не_ведут(роль: str) -> None:
    охват = scope_of(роль, "HQ")

    assert охват is None or not manages_spaces(охват)
    if охват is not None:
        assert not any(
            may_grant(охват, tenant="HQ", role=r) for r in ("admin", "developer", "guest")
        )


@pytest.mark.parametrize("роль", ["developer", "guest"])
def test_девелопер_и_гость_не_ведут_пространства(роль: str) -> None:
    assert scope_of(роль, "HQ") is None


# --- рейтинги: загрузка — контроль и админы (D420), девелопер и гость читают ---


@pytest.mark.parametrize(
    ("роль", "можно"),
    [
        ("superadmin", True),
        ("admin", True),
        ("control", True),
        ("developer", False),
        ("guest", False),
        ("auditor", False),
    ],
)
def test_загрузка_рейтингов(роль: str, можно: bool) -> None:
    assert may_manage_ratings(роль, "HQ") is можно


# --- гость: всё на чтение ------------------------------------------------------

#: Дела самого человека, которые гость делает и без права на запись в сеть.
СВОИ_ДЕЛА_ГОСТЯ = {
    "/logout",
    "/settings/password",
    "/oauth/authorize",
    "/settings/claude-revoke",
    "/settings/claude-token",
    "/settings/claude-token-revoke",
    "/settings/sign-out-everywhere",
    # Свой профиль (D447): своя почта Google и свой язык сайта.
    "/settings/google-link",
    "/settings/google-unlink",
    "/settings/lang",
    # Свои уведомления (#1129, D604): отметка «прочитано» — дело самого человека, любой роли.
    "/settings/notifications/1/read",
    "/settings/notifications/read-all",
    # Свой постоянный отбор стран экрана «Страны» (D536) — настройка своей учётки, как язык.
    "/country/filter",
    # Подтверждение входа перед долгоживущим доступом — своя же учётка.
    "/settings/confirm",
    "/settings/confirm/google",
    "/settings/continue",
    # Свои способы входа (D463): ключи, приложение, резервные коды — доступны любой роли.
    "/settings/security/relogin",
    "/settings/security/passkey/options",
    "/settings/security/passkey/register",
    "/settings/security/passkey/x/delete",
    "/settings/security/totp/start",
    "/settings/security/totp/confirm",
    "/settings/security/totp/remove",
    "/settings/security/backup/generate",
    "/settings/security/prove",
}


def _записывающие(app: Flask) -> list[tuple[str, str]]:
    """Адреса записи приложения: (метод, путь с подставленными значениями)."""
    найдены: list[tuple[str, str]] = []
    for правило in app.url_map.iter_rules():
        методы = (правило.methods or set()) - {"GET", "HEAD", "OPTIONS"}
        if not методы:
            continue
        значения = {
            имя: (1 if isinstance(правило._converters[имя], IntegerConverter) else "x")
            for имя in правило.arguments
        }
        _, путь = правило.build(значения)  # type: ignore[misc]
        найдены.extend((метод, путь) for метод in sorted(методы))
    return найдены


def test_гость_не_пишет_ни_одним_адресом(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="guest")
    приложение = собрать(tenant="HQ")
    открыты = auth.OPEN_ENDPOINTS
    пропущено: list[str] = []
    with приложение.test_client() as client:
        assert войти(client).status_code == 302
        for метод, путь in _записывающие(приложение):
            соответствие = приложение.url_map.bind("localhost").match(путь, method=метод)
            if соответствие[0] in открыты or путь in СВОИ_ДЕЛА_ГОСТЯ or путь == "/login":
                continue
            ответ = client.open(путь, method=метод, data={"a": "b"}, headers=ЗАГОЛОВКИ)
            # Скрытый экран ключей API 404 отвечает всем, кроме суперадмина.
            ждём = 404 if путь.startswith("/users/connections") else 403
            if ответ.status_code != ждём:
                пропущено.append(f"{метод} {путь} -> {ответ.status_code}")
    assert not пропущено, "гостю открыта запись: " + "; ".join(пропущено)
    assert all(не_звали == [] for не_звали in зовы.values())


@pytest.mark.parametrize("путь", ["/overview", "/inspections", "/country", "/ratings"])
def test_гость_читает_сеть(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]], путь: str
) -> None:
    клиент = next(_войти(monkeypatch, tenant="HQ", role="guest"))

    assert клиент.get(путь).status_code == 200


@pytest.mark.parametrize("путь", ["/admin", "/actions"])
def test_гость_не_видит_методику_и_действия_уК(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]], путь: str
) -> None:
    клиент = next(_войти(monkeypatch, tenant="HQ", role="guest"))

    assert клиент.get(путь).status_code == 404


@pytest.mark.parametrize(
    "путь", ["/overview", "/inspections", "/country", "/ratings", "/admin", "/actions"]
)
def test_девелопер_читает_всё_что_читал_аудитор(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]], путь: str
) -> None:
    клиент = next(_войти(monkeypatch, tenant="HQ", role="developer"))

    assert клиент.get(путь).status_code == 200


def test_гостю_на_карточке_проверки_нет_кнопок_действий(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    клиент = next(_войти(monkeypatch, tenant="HQ", role="guest"))

    страница = клиент.get(f"/inspections/{ID}").get_data(as_text=True)

    for маркер in ("/retract", "/accept", "/move", "/revise", "/letter/draft"):
        assert маркер not in страница, f"гостю показана кнопка {маркер}"


def test_девелоперу_на_карточке_действия_видны(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    клиент = next(_войти(monkeypatch, tenant="HQ", role="developer"))

    страница = клиент.get(f"/inspections/{ID}").get_data(as_text=True)

    assert "/accept" in страница


# --- доска «Главной» -----------------------------------------------------------


def test_у_гостя_доски_нет_а_девелопер_вычитывает() -> None:
    assert home_board.kinds_for(home_board.Who("guest", "HQ")) == ()
    assert home_board.REVIEW in home_board.kinds_for(home_board.Who("developer", "HQ"))


# --- MCP через OAuth -----------------------------------------------------------

ВСЕ_ВИДЫ = (
    KIND_INSPECTIONS,
    KIND_CHECKLIST_SOURCE,
    KIND_CHECKLIST,
    KIND_IMPORT,
    KIND_RATINGS_READ,
    KIND_RATINGS,
    KIND_RETRACTION,
)
ЧТЕНИЕ_УК = frozenset({KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_RATINGS_READ})
МАТРИЦА_MCP: dict[tuple[str, str], frozenset[str]] = {
    ("HQ", "superadmin"): frozenset(ВСЕ_ВИДЫ) - {KIND_RETRACTION},
    ("HQ", "admin"): frozenset(ВСЕ_ВИДЫ) - {KIND_RETRACTION},
    ("HQ", "developer"): ЧТЕНИЕ_УК | {KIND_CHECKLIST, KIND_IMPORT},  # загрузка — D567
    ("HQ", "control"): frozenset({KIND_RATINGS_READ, KIND_RATINGS}),
    # Гость: только чтение проверок и рейтингов; методики и загрузок нет.
    ("HQ", "guest"): frozenset({KIND_INSPECTIONS, KIND_RATINGS_READ}),
    # Аудитора в УК больше нет: если строка всё же осталась — закрыто.
    ("HQ", "auditor"): frozenset(),
    # Админ партнёра ведёт методику своего пространства и в Claude (D460).
    ("GE", "admin"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_RATINGS_READ}
    ),
    ("GE", "auditor"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_RATINGS_READ}
    ),
}


@pytest.mark.parametrize(("тенант", "роль"), sorted(МАТРИЦА_MCP))
@pytest.mark.parametrize("вид", ВСЕ_ВИДЫ)
def test_mcp_роль_на_вид(тенант: str, роль: str, вид: str) -> None:
    ожидание = вид in МАТРИЦА_MCP[(тенант, роль)]

    assert permits(роль, тенант, вид) is ожидание, (
        f"{роль}@{тенант} × {вид}: ожидалось {'да' if ожидание else 'нет'}"
    )


# --- бот и мини-апп: гость не начинает проверку --------------------------------


def _положение(роль: str, тенант: str) -> Standing:
    return Standing.live(Binding(7, "u", "who", тенант, _сейчас(), роль))  # type: ignore[call-arg]


def _сейчас() -> datetime:
    return datetime.now(UTC)


@pytest.mark.parametrize(
    ("роль", "тенант", "ожидание"),
    [
        ("developer", "HQ", "HQ"),
        ("admin", "HQ", "HQ"),
        ("superadmin", "HQ", "HQ"),
        # Поле закрыто контролю (D420) и гостю (D440): проверок они не проводят.
        ("control", "HQ", None),
        ("guest", "HQ", None),
        ("auditor", "GE", "GE"),
        ("admin", "GE", "GE"),
    ],
)
def test_бот_пускает_по_роли(роль: str, тенант: str, ожидание: str | None) -> None:
    пространство = space_from(7, _положение(роль, тенант), roster=None)

    assert пространство == ожидание, f"{роль}@{тенант}: бот дал {пространство!r}"
