"""Вкладка «Подключения» (D425): кто пройдёт, что отбивается и как показывается ключ — без базы.

Слой базы `api_access` и справочник стран подменены на границе модуля: здесь
проверяется поверхность — заслон по роли и происхождению, один показ ключа,
отказы формы без записи. Настоящая база и сам API с выданным ключом —
`tests/test_db_connections.py`.

Заслон — ядро безопасности: каждая проверка прогонялась на сломанной копии
(проверка убрана — тест падает с названием роли и адреса).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import api_access
from src.db import ratings_read as ratings
from src.db.errors import AccessError

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВКЛАДКА = "/users?tab=connections"
КЛЮЧ = "ключ-который-покажем-один-раз-0123456789abcdef"
НОВЫЙ_КЛЮЧ = "новый-ключ-после-перевыпуска-fedcba9876543210"
ИМЯ = "Свод-Swarm"

#: (пространство, роль) → ждём ли доступ. Главный админ УК — единственный.
РОЛИ = [
    ("HQ", "admin"),
    ("HQ", "control"),
    ("HQ", "auditor"),
    ("GE", "admin"),
    ("GE", "auditor"),
]


class Склад:
    """Двойник `api_access`: что звали и что у кого записано."""

    def __init__(self) -> None:
        сейчас = datetime.now(UTC)
        self.tokens = [
            api_access.TokenRow(
                id=1,
                consumer="swarm",
                scopes=("ratings:scores", "inspections:list"),
                issued_at=сейчас - timedelta(days=3),
                issued_by="director",
                revoked_at=None,
                revoked_by=None,
                title=ИМЯ,
                contact="ops@example.org",
                expires_at=None,
                countries=None,
                last_used_at=сейчас - timedelta(hours=2),
                calls_week=42,
                errors_week=3,
            ),
            api_access.TokenRow(
                id=2,
                consumer="old-bi",
                scopes=("maps:ratings",),
                issued_at=сейчас - timedelta(days=40),
                issued_by="director",
                revoked_at=сейчас - timedelta(days=1),
                revoked_by="director",
                title="Старый BI",
            ),
        ]
        self.зовы: list[tuple[str, Any]] = []
        self.следующий = 3

    def пишущие_зовы(self) -> list[str]:
        return [имя for имя, _ in self.зовы if имя in {"issue", "update", "reissue", "revoke"}]

    def list_tokens(self) -> list[api_access.TokenRow]:
        return list(self.tokens)

    def issue(self, consumer: str, scopes: tuple[str, ...], **kw: Any) -> api_access.IssuedApiToken:
        self.зовы.append(("issue", (consumer, scopes, kw)))
        выпущен = api_access.IssuedApiToken(self.следующий, consumer, scopes, КЛЮЧ)
        self.tokens.append(
            api_access.TokenRow(
                id=self.следующий,
                consumer=consumer,
                scopes=scopes,
                issued_at=datetime.now(UTC),
                issued_by=kw["by"],
                revoked_at=None,
                revoked_by=None,
                title=kw["title"],
                contact=kw["contact"],
                expires_at=kw["expires_at"],
                countries=kw["countries"],
            )
        )
        self.следующий += 1
        return выпущен

    def update(self, token_id: int, scopes: tuple[str, ...], **kw: Any) -> bool:
        self.зовы.append(("update", (token_id, scopes, kw)))
        return any(t.id == token_id and t.revoked_at is None for t in self.tokens)

    def reissue(self, token_id: int, *, by: str) -> api_access.IssuedApiToken | None:
        self.зовы.append(("reissue", (token_id, by)))
        живой = next((t for t in self.tokens if t.id == token_id and t.revoked_at is None), None)
        if живой is None:
            return None
        return api_access.IssuedApiToken(token_id + 100, живой.consumer, живой.scopes, НОВЫЙ_КЛЮЧ)

    def revoke(self, token_id: int, *, by: str) -> bool:
        self.зовы.append(("revoke", (token_id, by)))
        return any(t.id == token_id and t.revoked_at is None for t in self.tokens)

    def usage(self, token_id: int, *, days: int) -> list[api_access.DayUsage]:
        return [api_access.DayUsage(datetime.now(UTC).date(), 5, 1)]

    def recent_log(self, token_id: int, *, limit: int) -> list[api_access.LogLine]:
        return [api_access.LogLine(datetime.now(UTC), "/api/v1/inspections", 200)]


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> Склад:
    склад = Склад()
    for имя in ("list_tokens", "issue", "update", "reissue", "revoke", "usage", "recent_log"):
        monkeypatch.setattr(api_access, имя, getattr(склад, имя))
    monkeypatch.setattr(
        ratings, "countries", lambda: tuple(SimpleNamespace(code=c) for c in ("GE", "AM", "RS"))
    )
    return склад


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, ui_lang: str = "ru"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ", ui_lang=ui_lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


def _форма(**поля: Any) -> dict[str, Any]:
    return {"title": "Новый сервис", "code": "bi-board", "scope": ["ratings:scores"], **поля}


# --- кто пройдёт ---------------------------------------------------------------------------


def test_главный_админ_видит_вкладку_и_сервисы(главный: FlaskClient) -> None:
    ответ = главный.get(ВКЛАДКА)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert ИМЯ in html and "swarm" in html and "42 обращ. / 3 ошиб." in html
    assert html.index(ИМЯ) < html.index("Старый BI"), "отозванные — ниже живых"
    assert "Подключить сервис" in html


def test_вкладка_на_английском(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> None:
    for клиент in _стенд(monkeypatch, tenant="HQ", role="superadmin", ui_lang="en"):
        html = клиент.get(ВКЛАДКА).get_data(as_text=True)
        assert "Connect a service" in html and "42 calls / 3 errors" in html
        assert "Подключить" not in html


def test_вкладка_в_шапке_людей_только_у_главного_админа(
    monkeypatch: pytest.MonkeyPatch, склад: Склад
) -> None:
    for клиент in _стенд(monkeypatch, tenant="HQ", role="superadmin"):
        assert "tab=connections" in клиент.get("/users").get_data(as_text=True)
    for клиент in _стенд(monkeypatch, tenant="HQ", role="admin"):
        assert "tab=connections" not in клиент.get("/users").get_data(as_text=True)


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_остальным_экрана_нет_на_чтение(
    monkeypatch: pytest.MonkeyPatch, склад: Склад, tenant: str, role: str
) -> None:
    for клиент in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = клиент.get(ВКЛАДКА)
        assert ответ.status_code == 404, (
            f"{role}@{tenant} открыл «Подключения»: {ответ.status_code}"
        )
        assert ИМЯ not in ответ.get_data(as_text=True)


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
@pytest.mark.parametrize(
    "адрес",
    ["/users/connections/issue"]
    + [f"/users/connections/1/{д}" for д in ("update", "reissue", "revoke")],
)
def test_остальным_и_записи_нет_и_в_базу_ничего_не_уходит(
    monkeypatch: pytest.MonkeyPatch, склад: Склад, tenant: str, role: str, адрес: str
) -> None:
    for клиент in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = клиент.post(адрес, data=_форма(), headers=ЗАГОЛОВКИ)
        assert ответ.status_code == 404, (
            f"{role}@{tenant} достучался до {адрес}: {ответ.status_code}"
        )
        # Без своего Origin — тот же 404: роль проверяется раньше происхождения.
        assert клиент.post(адрес, data=_форма()).status_code == 404
    assert склад.пишущие_зовы() == []


def test_анониму_вход_а_не_экран(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ").test_client() as клиент:
        for ответ in (
            клиент.get(ВКЛАДКА),
            клиент.post("/users/connections/issue", data=_форма(), headers=ЗАГОЛОВКИ),
        ):
            assert ответ.status_code == 302 and "login" in ответ.headers["Location"]
    assert склад.пишущие_зовы() == []


@pytest.mark.parametrize(
    "адрес",
    ["/users/connections/issue"]
    + [f"/users/connections/1/{д}" for д in ("update", "reissue", "revoke")],
)
def test_отправка_без_своего_origin_отказ_и_без_записи(
    главный: FlaskClient, склад: Склад, адрес: str
) -> None:
    без_заголовка = главный.post(адрес, data=_форма())
    чужой = главный.post(адрес, data=_форма(), headers={"Origin": "https://evil.example"})
    assert (без_заголовка.status_code, чужой.status_code) == (403, 403), адрес
    assert склад.пишущие_зовы() == []


# --- выдача: ключ один раз -----------------------------------------------------------------


def test_ключ_показан_один_раз_и_не_кэшируется(
    главный: FlaskClient, склад: Склад, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        ответ = главный.post(
            "/users/connections/issue",
            data=_форма(contact="a@b.c", countries="ge", expires="2099-01-01"),
            headers=ЗАГОЛОВКИ,
        )
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert html.count(КЛЮЧ) == 1, "ключ должен стоять на странице ровно один раз"
    assert "no-store" in ответ.headers["Cache-Control"]
    assert "private" in ответ.headers["Cache-Control"]
    assert "Больше мы его не покажем" in html and "Скопировать" in html
    assert КЛЮЧ not in caplog.text, "ключ попал в журнал"
    assert КЛЮЧ not in str(ответ.headers), "ключ уехал в заголовки"
    повтор = главный.get(ВКЛАДКА + "&service=3")
    assert КЛЮЧ not in повтор.get_data(as_text=True)


def test_выдача_передаёт_базе_проверенное_и_логин_вошедшего(
    главный: FlaskClient, склад: Склад
) -> None:
    главный.post(
        "/users/connections/issue",
        data=_форма(
            contact=" ops@x.y ",
            scope=["maps:ratings", "ratings:scores"],
            countries="ge  AM",
            expires="2099-01-01",
        ),
        headers=ЗАГОЛОВКИ,
    )
    (имя, (код, права, kw)) = склад.зовы[-1]
    assert имя == "issue" and код == "bi-board"
    assert права == ("maps:ratings", "ratings:scores")
    assert kw["by"] == "director" and kw["title"] == "Новый сервис" and kw["contact"] == "ops@x.y"
    assert kw["countries"] == ("GE", "AM")
    assert kw["expires_at"] == datetime(2099, 1, 1, 23, 59, 59, tzinfo=UTC)


@pytest.mark.parametrize(
    ("поля", "текст"),
    [
        ({"scope": []}, "Отметьте хотя бы одно право"),
        ({"scope": ["ratings:write"]}, "Такого права нет"),
        ({"code": "Bad Code"}, "Код: латиница"),
        ({"countries": "GE ZZ"}, "Неизвестная страна: ZZ"),
        ({"expires": str(date.today() - timedelta(days=1))}, "Срок не раньше завтрашнего дня"),
        ({"expires": date.today().isoformat()}, "Срок не раньше завтрашнего дня"),
        ({"title": "  "}, "Назовите сервис"),
    ],
)
def test_отказ_формы_строкой_над_формой_без_записи_и_с_сохранённым_вводом(
    главный: FlaskClient, склад: Склад, поля: dict[str, Any], текст: str
) -> None:
    ответ = главный.post(
        "/users/connections/issue",
        data=_форма(contact="сохрани-меня", **поля),
        headers=ЗАГОЛОВКИ,
    )
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 400
    assert текст in html, f"нет понятной строки отказа: {текст!r}"
    assert "сохрани-меня" in html, "введённое потеряно"
    assert КЛЮЧ not in html
    assert склад.пишущие_зовы() == [], f"отказ формы дошёл до базы: {поля}"


def test_справочник_стран_не_ответил_ничего_не_записано(
    главный: FlaskClient, склад: Склад, monkeypatch: pytest.MonkeyPatch
) -> None:
    def упал() -> Any:
        raise AccessError("нет базы")

    monkeypatch.setattr(ratings, "countries", упал)
    ответ = главный.post("/users/connections/issue", data=_форма(countries="GE"), headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 503
    assert "Не удалось сверить страны" in ответ.get_data(as_text=True)
    assert склад.пишущие_зовы() == []


def test_отказ_перечня_не_выдаётся_за_пустой_список(
    monkeypatch: pytest.MonkeyPatch, склад: Склад
) -> None:
    def упал() -> Any:
        raise AccessError("нет базы")

    monkeypatch.setattr(api_access, "list_tokens", упал)
    for клиент in _стенд(monkeypatch, tenant="HQ", role="superadmin"):
        html = клиент.get(ВКЛАДКА).get_data(as_text=True)
        assert "Не удалось прочитать список" in html
        assert "Сервисов пока нет" not in html


# --- карточка, правка, перевыпуск, отзыв ---------------------------------------------------


def test_карточка_показывает_дни_и_последние_запросы(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА + "&service=1").get_data(as_text=True)
    assert "Обращения за 14 дней" in html and "/api/v1/inspections" in html
    assert 'name="scope" value="ratings:scores" checked' in html
    assert 'name="scope" value="maps:ratings" checked' not in html


def test_правка_передаёт_права_страны_срок(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post(
        "/users/connections/1/update",
        data=_форма(scope=["ratings:scores"], countries="RS", expires="2099-05-05", contact=""),
        headers=ЗАГОЛОВКИ,
    )
    assert ответ.status_code == 200 and "Сохранено" in ответ.get_data(as_text=True)
    (имя, (номер, права, kw)) = склад.зовы[-1]
    assert (имя, номер, права) == ("update", 1, ("ratings:scores",))
    assert kw["countries"] == ("RS",) and kw["contact"] is None
    assert kw["title"] == "Новый сервис"


def test_правка_с_ошибкой_не_пишет_и_держит_ввод(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post(
        "/users/connections/1/update",
        data=_форма(scope=[], title="Переименован"),
        headers=ЗАГОЛОВКИ,
    )
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 400 and "Отметьте хотя бы одно право" in html
    assert "Переименован" in html
    assert склад.пишущие_зовы() == []


def test_отозванный_ключ_не_правится(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post("/users/connections/2/update", data=_форма(), headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 409 and склад.пишущие_зовы() == []


def test_перевыпуск_показывает_новый_ключ_один_раз(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post("/users/connections/1/reissue", headers=ЗАГОЛОВКИ)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and html.count(НОВЫЙ_КЛЮЧ) == 1
    assert "no-store" in ответ.headers["Cache-Control"]
    assert склад.зовы[-1] == ("reissue", (1, "director"))
    assert НОВЫЙ_КЛЮЧ not in главный.get(ВКЛАДКА + "&service=1").get_data(as_text=True)


def test_отзыв_с_логином_вошедшего(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post("/users/connections/1/revoke", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 200
    assert f"Ключ «{ИМЯ}» отозван" in ответ.get_data(as_text=True)
    assert склад.зовы[-1] == ("revoke", (1, "director"))


def test_отзыв_отозванного_или_чужого_номера_отказ(главный: FlaskClient) -> None:
    assert главный.post("/users/connections/2/revoke", headers=ЗАГОЛОВКИ).status_code == 409
    assert главный.post("/users/connections/999/reissue", headers=ЗАГОЛОВКИ).status_code == 409


def test_отзыв_и_перевыпуск_подтверждаются_на_странице_без_confirm(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА + "&service=1").get_data(as_text=True)
    assert "Да, отозвать" in html and "Да, перевыпустить" in html
    assert "confirm(" not in html
