"""Колокольчик и красные точки (#1129, D604, D614) — уровень страниц.

Базы нет: чтение и отметки `src.db.notifications` подменены двойником, который, как
настоящий запрос, выбирает строки по ключу учётки. Ядро здесь — доступ и «ничего
наружу»: веб спрашивает базу только про учётку СВОЕЙ сессии (никакой параметр запроса
не называет чужую), чужие строки не попадают ни в список, ни в точки, а отметка по
чужому номеру ничего не меняет. Остальное — что человек видит: точка на колокольчике и
на пункте раздела, фраза на языке интерфейса, открытие страницы с адресом уведомления
гасит точку.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient
from web_harness import ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import notifications as store
from src.web import auth
from src.web.notifications import link_matches_page

СВОЙ = "22222222-2222-2222-2222-222222222222"  # ключ учётки `Учётка` из web_harness
ЧУЖОЙ = "99999999-9999-9999-9999-999999999999"
ORIGIN = {"Origin": "http://localhost"}
КОГДА = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def _строка(номер: int, kind: str, link: str, **params: str) -> store.Notification:
    return store.Notification(
        id=номер,
        kind=kind,
        link=link,
        params={"subject": "Тема", "by": "vera", **params},
        created_at=КОГДА,
        read_at=None,
    )


class Двойник:
    """Таблица `notifications` в памяти: каждое чтение и отметка — только по ключу учётки."""

    def __init__(self) -> None:
        self.строки: dict[str, list[store.Notification]] = {СВОЙ: [], ЧУЖОЙ: []}
        self.спрашивали: list[str] = []

    def unread_count(self, user: str) -> int:
        self.спрашивали.append(user)
        return sum(1 for s in self.строки.get(user, []) if s.is_unread)

    def list_for(self, user: str, limit: int = 100, *, unread_only: bool = False) -> list:  # type: ignore[type-arg]
        self.спрашивали.append(user)
        found = self.строки.get(user, [])
        return [s for s in found if s.is_unread or not unread_only][:limit]

    def _отметить(self, user: str, годится: object) -> int:
        число = 0
        for i, s in enumerate(self.строки.get(user, [])):
            if s.is_unread and годится(s):  # type: ignore[operator]
                self.строки[user][i] = store.Notification(
                    s.id, s.kind, s.link, s.params, s.created_at, КОГДА
                )
                число += 1
        return число

    def mark_read(self, user: str, notification_id: int) -> bool:
        return self._отметить(user, lambda s: s.id == notification_id) > 0

    def mark_read_by_link(self, user: str, link: str) -> int:
        return self._отметить(user, lambda s: s.link == link)

    def mark_all_read(self, user: str) -> int:
        return self._отметить(user, lambda s: True)


@pytest.fixture
def таблица(monkeypatch: pytest.MonkeyPatch) -> Двойник:
    двойник = Двойник()
    for имя in ("unread_count", "list_for", "mark_read", "mark_read_by_link", "mark_all_read"):
        monkeypatch.setattr(store, имя, getattr(двойник, имя))
    return двойник


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch, таблица: Двойник) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(tenant="HQ", role="admin") if token == ТОКЕН else None,
        )
        yield client


def _страница(клиент: FlaskClient, путь: str = "/settings") -> str:
    return клиент.get(путь).get_data(as_text=True)


# ── Доступ: только своё ───────────────────────────────────────────────


def test_в_списке_только_свои_уведомления(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_returned", "/actions?id=1", subject="Моё")]
    таблица.строки[ЧУЖОЙ] = [_строка(2, "rx_returned", "/actions?id=2", subject="Чужое")]

    ответ = клиент.get("/settings/notifications")

    текст = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "«Моё»" in текст
    assert "Чужое" not in текст
    assert set(таблица.спрашивали) == {СВОЙ}


def test_параметр_запроса_не_называет_чужую_учётку(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[ЧУЖОЙ] = [_строка(2, "rx_returned", "/actions?id=2", subject="Чужое")]

    for запрос in (f"?user={ЧУЖОЙ}", f"?user_id={ЧУЖОЙ}", f"?id={ЧУЖОЙ}"):
        текст = клиент.get("/settings/notifications" + запрос).get_data(as_text=True)

        assert "Чужое" not in текст
    assert set(таблица.спрашивали) == {СВОЙ}


def test_чужое_не_отмечается_по_номеру(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[ЧУЖОЙ] = [_строка(2, "rx_returned", "/actions?id=2")]

    ответ = клиент.post("/settings/notifications/2/read", headers=ORIGIN)

    assert ответ.status_code == 204
    assert таблица.строки[ЧУЖОЙ][0].is_unread, "чужое уведомление отмечено прочитанным"


def test_отметка_с_чужой_страницы_отказ(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_returned", "/actions?id=1")]

    ответ = клиент.post("/settings/notifications/1/read", headers={"Origin": "http://evil.example"})

    assert ответ.status_code in (400, 403)
    assert таблица.строки[СВОЙ][0].is_unread


def test_без_входа_ни_списка_ни_отметки(monkeypatch: pytest.MonkeyPatch, таблица: Двойник) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as аноним:
        список = аноним.get("/settings/notifications")
        отметка = аноним.post("/settings/notifications/1/read", headers=ORIGIN)

    assert список.status_code in (302, 401, 403)
    assert отметка.status_code in (302, 401, 403)
    assert таблица.спрашивали == []


# ── Что видит человек ────────────────────────────────────────────────


def test_без_непрочитанного_точек_нет(клиент: FlaskClient) -> None:
    страница = _страница(клиент)

    assert "data-bell" in страница
    assert "notif-dot" not in страница
    assert 'class="bell__dot" aria-hidden="true" hidden' in страница


def test_непрочитанное_зажигает_колокольчик_и_пункт_раздела(
    клиент: FlaskClient, таблица: Двойник
) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_requested", "/osb?id=77")]

    страница = _страница(клиент)

    assert 'class="bell__dot" aria-hidden="true">' in страница, "колокольчик без точки"
    assert страница.count('class="notif-dot"') >= 1, "пункт «ОСБ» без точки"
    assert "Уведомления: есть новые" in страница
    # Точка стоит именно на пункте «ОСБ», а не на соседних.
    пункт_осб = страница.split('href="/osb?lang=ru"')[1].split("</a>")[0]
    assert "notif-dot" in пункт_осб


def test_точка_чужого_уведомления_не_горит(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[ЧУЖОЙ] = [_строка(2, "rx_requested", "/osb?id=77")]

    assert "notif-dot" not in _страница(клиент)


def test_фраза_на_языке_интерфейса_и_без_разметки_в_параметрах(
    клиент: FlaskClient, таблица: Двойник
) -> None:
    таблица.строки[СВОЙ] = [
        _строка(1, "rx_returned", "/actions?id=1", subject="<b>Тема</b>", by="vera")
    ]

    ru = клиент.get("/settings/notifications?lang=ru").get_data(as_text=True)

    assert "vera вернул предписание «&lt;b&gt;Тема&lt;/b&gt;» на доработку" in ru
    assert "<b>Тема</b>" not in ru


def test_незнакомый_вид_не_роняет_список(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "kind_from_the_future", "/overview")]

    ответ = клиент.get("/settings/notifications")

    assert ответ.status_code == 200
    assert "Новое событие" in ответ.get_data(as_text=True)


def test_открытие_страницы_с_адресом_уведомления_гасит_его(
    клиент: FlaskClient, таблица: Двойник
) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_returned", "/settings")]

    страница = _страница(клиент, "/settings?lang=ru")

    assert not таблица.строки[СВОЙ][0].is_unread
    assert "notif-dot" not in страница, "страница нарисована до отметки"


def test_другая_страница_уведомление_не_гасит(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_returned", "/actions?tab=prescriptions&id=9")]

    _страница(клиент, "/settings")

    assert таблица.строки[СВОЙ][0].is_unread


def test_отметить_всё_гасит_только_своё(клиент: FlaskClient, таблица: Двойник) -> None:
    таблица.строки[СВОЙ] = [_строка(1, "rx_returned", "/a"), _строка(2, "rx_approved", "/b")]
    таблица.строки[ЧУЖОЙ] = [_строка(3, "rx_approved", "/c")]

    ответ = клиент.post("/settings/notifications/read-all", headers=ORIGIN)

    assert ответ.status_code == 204
    assert not any(s.is_unread for s in таблица.строки[СВОЙ])
    assert таблица.строки[ЧУЖОЙ][0].is_unread


def test_отказ_базы_страницу_не_роняет(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.db.errors import AccessError

    def сломано(user: str) -> int:
        raise AccessError("двойник: база молчит")

    monkeypatch.setattr(store, "unread_count", сломано)

    ответ = клиент.get("/settings")

    assert ответ.status_code == 200
    assert "notif-dot" not in ответ.get_data(as_text=True)


# ── Совпадение адреса страницы и уведомления ─────────────────────────


@pytest.mark.parametrize(
    ("link", "path", "args", "ожидается"),
    [
        ("/osb?id=7", "/osb", {"id": ["7"]}, True),
        ("/osb?id=7", "/osb", {"id": ["7"], "lang": ["en"], "country": ["GE"]}, True),
        ("/osb?id=7", "/osb", {"id": ["8"]}, False),
        ("/osb?id=7", "/osb", {}, False),
        ("/osb?id=7", "/actions", {"id": ["7"]}, False),
        ("/overview", "/overview", {"lang": ["ru"]}, True),
        ("/actions?tab=prescriptions&id=7", "/actions", {"id": ["7"]}, False),
    ],
)
def test_адрес_страницы_и_уведомления(
    link: str, path: str, args: dict[str, list[str]], ожидается: bool
) -> None:
    assert link_matches_page(link, path, args) is ожидается
