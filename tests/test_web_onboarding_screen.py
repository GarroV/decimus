"""«Начало работы» и тур (D756) — уровень страниц: карточка, меню, данные тура, пометки.

Базы нет: двери опознания и чтения подменены. Что решается ядром (`onboarding.py`) — в
`test_web_onboarding.py`; здесь — что человек видит и что пишется его учётке.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_overview import снимок
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import web_own_profile
from src.db.errors import AccessError
from src.web import auth, home_board, onboarding_facts, sections
from src.web import onboarding as ob
from src.web import overview as overview_data
from src.web.texts import t

ПУТЬ = "/settings/onboarding"
ЗАГОЛОВКИ = {"Origin": СВОЙ}
#: Сама карточка (в меню учётки тоже есть слова «Начало работы»).
КАРТОЧКА = 'id="start"'

НЕТ = ob.Facts(
    bot_bound=False,
    claude_connected=False,
    people_added=False,
    first_inspection=False,
    space=ob.SpaceFacts(countries=True, units=False, checklist=True),
)
ВСЁ = ob.Facts(
    bot_bound=True,
    claude_connected=True,
    people_added=True,
    first_inspection=True,
    space=ob.SpaceFacts(True, True, True),
)


def _войти(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, facts: ob.Facts = НЕТ, **kw: Any
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    monkeypatch.setattr(onboarding_facts, "person_facts", lambda *_a, **_k: facts)
    monkeypatch.setattr(onboarding_facts, "bot_available", lambda: True)
    monkeypatch.setattr(overview_data, "load", lambda **_: снимок())
    monkeypatch.setattr(home_board, "kinds_for", lambda _who: ())
    with собрать(tenant=tenant, bot_username="decimus_bot", **kw).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _с_учёткой(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, **атрибуты: Any) -> None:
    def resolve(token: str) -> Учётка | None:
        if token != ТОКЕН:
            return None
        учётка = Учётка(tenant=tenant, role=role)
        for имя, значение in атрибуты.items():
            setattr(учётка, имя, значение)
        return учётка

    monkeypatch.setattr(auth, "resolve_session", resolve)


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _войти(monkeypatch, tenant="ARMENIA", role="admin")


@pytest.fixture
def ук(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _войти(monkeypatch, tenant="HQ", role="admin")


def _страница(client: FlaskClient, path: str = "/overview?lang=ru") -> str:
    ответ = client.get(path)
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def _конфиг(страница: str) -> dict[str, Any]:
    найдено = re.search(r"data-tour-config='([^']*)'", страница)
    assert найдено, "на странице нет данных тура"
    import html

    return json.loads(html.unescape(найдено.group(1)))


# ── карточка «Начало работы» ──────────────────────────────────────────────


def test_партнёру_на_главной_карточка_с_шагами_и_ожиданием_ук(партнёр: FlaskClient) -> None:
    страница = _страница(партнёр)

    assert КАРТОЧКА in страница
    assert t("onboarding.step.bot.title", "ru") in страница
    # Пиццерий в справочнике нет — это дело УК: «ждём», а не «сделайте».
    assert t("onboarding.state.waiting", "ru") in страница
    assert 'name="start" value="hide"' in страница


def test_карточка_вместо_напоминаний_стикерами_о_боте_и_claude(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(home_board, "kinds_for", lambda _who: (home_board.REVIEW,))
    from src.web import connect_reminder

    monkeypatch.setattr(connect_reminder, "missing", lambda: ("bot", "claude"))
    monkeypatch.setattr(home_board, "load_counts", lambda *_, **__: home_board.Counts(review=2))

    страница = _страница(партнёр)

    assert КАРТОЧКА in страница
    # Стикеры-напоминания (27.10.2026) те же шаги уже не дублируют; доска остаётся своим делом.
    assert 'hm-sticker__title">' + t("home.board.bot_connect.title", "ru", count=1) not in страница
    assert (
        'hm-sticker__title">' + t("home.board.claude_connect.title", "ru", count=1) not in страница
    )
    assert 'hm-sticker__title">' + t("home.board.review.title", "ru", count=2) in страница


def test_всё_сделано_карточки_нет_а_по_ссылке_из_меню_есть(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for клиент in _войти(monkeypatch, tenant="ARMENIA", role="admin", facts=ВСЁ):
        assert КАРТОЧКА not in _страница(клиент)
        вручную = _страница(клиент, "/overview?lang=ru&start=1")
        assert КАРТОЧКА in вручную
        assert t("onboarding.all_done", "ru") in вручную


def test_скрытая_человеком_карточка_не_показывается(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _войти(monkeypatch, tenant="ARMENIA", role="admin"):
        _с_учёткой(monkeypatch, "ARMENIA", "admin", start_hidden_at=datetime.now(UTC))
        assert КАРТОЧКА not in _страница(клиент)
        вручную = _страница(клиент, "/overview?lang=ru&start=1")
        assert 'name="start" value="show"' in вручную


def test_управляющей_компании_карточки_нет_даже_по_ссылке(ук: FlaskClient) -> None:
    assert КАРТОЧКА not in _страница(ук, "/overview?lang=ru&start=1")


def test_при_просмотре_чужими_глазами_карточки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _войти(monkeypatch, tenant="ARMENIA", role="admin"):
        _с_учёткой(monkeypatch, "ARMENIA", "admin", is_peeking=True)
        assert КАРТОЧКА not in _страница(клиент)


# ── меню учётки и тур ─────────────────────────────────────────────────────


def test_в_меню_партнёра_начало_работы_и_тур(партнёр: FlaskClient) -> None:
    страница = _страница(партнёр)

    assert t("menu.start", "ru") in страница and "start=1" in страница
    assert "data-tour-start" in страница


def test_в_меню_ук_только_тур(ук: FlaskClient) -> None:
    страница = _страница(ук)

    assert t("menu.start", "ru") not in страница
    assert "data-tour-start" in страница


def test_данные_тура_партнёр_видит_без_лишнего_и_с_пометкой_автозапуска(
    партнёр: FlaskClient,
) -> None:
    конфиг = _конфиг(_страница(партнёр))

    assert конфиг["autostart"] is True
    ключи = [шаг["key"] for шаг in конфиг["steps"]]
    assert ключи[0] == "welcome" and ключи[-1] == "settings"
    assert {"group-work", "tabbar", "search", "bell", "menu"} <= set(ключи)
    assert конфиг["doneUrl"].endswith(ПУТЬ)


def test_тур_уже_виденный_сам_не_открывается(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _войти(monkeypatch, tenant="ARMENIA", role="admin"):
        _с_учёткой(monkeypatch, "ARMENIA", "admin", tour_seen_at=datetime.now(UTC))
        assert _конфиг(_страница(клиент))["autostart"] is False


def test_у_ук_тур_есть_но_сам_не_открывается(ук: FlaskClient) -> None:
    assert _конфиг(_страница(ук))["autostart"] is False


def test_автозапуск_только_на_главной(партнёр: FlaskClient) -> None:
    ответ = партнёр.get("/нет-такой-страницы?lang=ru")  # шапка и тур те же, а это не «Главная»

    assert ответ.status_code == 404
    assert _конфиг(ответ.get_data(as_text=True))["autostart"] is False


def test_тур_не_зовёт_в_разделы_которых_роли_нет(партнёр: FlaskClient) -> None:
    текст = json.dumps(_конфиг(_страница(партнёр))["steps"], ensure_ascii=False)

    assert t("section.osb.title", "ru") not in текст
    assert t("section.calendar.title", "ru") in текст or "calendar" not in {
        s.key for s in sections.visible_sections(Учётка(tenant="ARMENIA", role="admin"))
    }


# ── пометки: POST /settings/onboarding ────────────────────────────────────


@pytest.fixture
def записи(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    журнал: list[dict[str, Any]] = []

    def set_onboarding(token: str, *, tour_seen: bool = False, start: str | None = None) -> bool:
        журнал.append({"token": token, "tour_seen": tour_seen, "start": start})
        return True

    monkeypatch.setattr(web_own_profile, "set_onboarding", set_onboarding)
    return журнал


def test_пометка_тура_пишется_своей_сессией_и_отвечает_без_тела(
    партнёр: FlaskClient, записи: list[dict[str, Any]]
) -> None:
    ответ = партнёр.post(
        ПУТЬ, data={"tour": "1"}, headers={**ЗАГОЛОВКИ, "X-Requested-With": "fetch"}
    )

    assert ответ.status_code == 204
    assert записи == [{"token": ТОКЕН, "tour_seen": True, "start": None}]


def test_скрыть_карточку_формой_возвращает_на_главную(
    партнёр: FlaskClient, записи: list[dict[str, Any]]
) -> None:
    ответ = партнёр.post(ПУТЬ, data={"start": "hide", "next": "/overview"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 302 and ответ.headers["Location"].endswith("/overview")
    assert записи == [{"token": ТОКЕН, "tour_seen": False, "start": "hide"}]


def test_чужая_страница_пометку_не_пишет(
    партнёр: FlaskClient, записи: list[dict[str, Any]]
) -> None:
    ответ = партнёр.post(ПУТЬ, data={"tour": "1"}, headers={"Origin": "https://evil.example"})

    assert ответ.status_code == 403 and записи == []


def test_незнакомое_слово_карточки_отказ_и_ничего_не_пишется(
    партнёр: FlaskClient, записи: list[dict[str, Any]]
) -> None:
    ответ = партнёр.post(ПУТЬ, data={"start": "delete"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 400 and записи == []


def test_открытый_редирект_через_next_закрыт(
    партнёр: FlaskClient, записи: list[dict[str, Any]]
) -> None:
    ответ = партнёр.post(
        ПУТЬ, data={"start": "hide", "next": "//evil.example/x"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 302 and "evil.example" not in ответ.headers["Location"]


def test_база_отказала_тур_получает_503_а_не_тишину(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def сбой(*_a: object, **_k: object) -> bool:
        raise AccessError("двойник: база молчит")

    monkeypatch.setattr(web_own_profile, "set_onboarding", сбой)

    ответ = партнёр.post(
        ПУТЬ, data={"tour": "1"}, headers={**ЗАГОЛОВКИ, "X-Requested-With": "fetch"}
    )

    assert ответ.status_code == 503


# ── открытое демо: карточки нет, тур есть, пометка — в куке ───────────────


def test_в_демо_карточки_нет_тур_открывается_и_помнится_в_куке(
    monkeypatch: pytest.MonkeyPatch, записи: list[dict[str, Any]]
) -> None:
    for клиент in _войти(monkeypatch, tenant="demo", role="admin", demo=True, ui_lang="en"):
        страница = _страница(клиент, "/overview?lang=en")
        assert КАРТОЧКА not in страница
        assert _конфиг(страница)["autostart"] is True

        ответ = клиент.post(
            ПУТЬ, data={"tour": "1"}, headers={**ЗАГОЛОВКИ, "X-Requested-With": "fetch"}
        )

        assert ответ.status_code == 204 and записи == []
        assert "decimus_demo_tour=1" in ответ.headers.get("Set-Cookie", "")
        assert _конфиг(_страница(клиент, "/overview?lang=en"))["autostart"] is False
