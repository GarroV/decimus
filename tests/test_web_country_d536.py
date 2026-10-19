"""Экран «Страны» (D536): алфавит, сворачивание, «Мои страны», настройки страны для админа."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_country import (
    данные,
    открыть,
    с_таблицей,
    с_точкой,
    строка_таблицы,
)
from test_web_country import стенд as база_стенд  # noqa: F401
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import ratings_read, web_own_profile
from src.web import auth, country_filter, country_settings, partner_spaces
from src.web import country as cn

ЗАГОЛОВКИ = {"Origin": СВОЙ}
СТРАНЫ = (("TR", 30), ("GE", 3), ("AM", 1))


@pytest.fixture
def стенд(база_стенд: FlaskClient) -> FlaskClient:  # noqa: F811
    return база_стенд


def колонка(страница: str) -> str:
    """Список колонки выбора — без блока «Мои страны» над ним (в нём тоже есть адреса)."""
    return страница.split('class="pk-rail__list"', 1)[1].split("</aside>", 1)[0]


# ── порядок: по алфавиту названия, а не по числу пиццерий ──────────────────


def test_страны_в_колонке_по_алфавиту_названия_а_не_по_числу_пиццерий(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    рейка = колонка(открыть(стенд, monkeypatch, данные(), "/country/GE"))
    # По-русски: Армения, Грузия, Турция. По числу пиццерий было бы TR, GE, AM.
    места = [рейка.index(f"/country/{код}") for код in ("AM", "GE", "TR")]
    assert места == sorted(места)


def test_порядок_следует_за_языком_экрана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: (("TR", 30), ("GE", 3), ("AM", 1)))
    # По-английски: Armenia, Georgia, Türkiye/Turkey — порядок тот же, но считается по английскому.
    рейка = колонка(открыть(стенд, monkeypatch, данные(), "/country/GE?lang=en"))
    assert [рейка.index(f"/country/{к}") for к in ("AM", "GE", "TR")] == sorted(
        рейка.index(f"/country/{к}") for к in ("AM", "GE", "TR")
    )


def test_вход_без_страны_открывает_первую_по_алфавиту(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    просили: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        просили.append(str(kw["code"]))
        return данные()

    monkeypatch.setattr(cn, "load", load)
    assert стенд.get("/country").status_code == 200
    assert просили == ["AM"]


# ── сворачивание: повторное нажатие на выбранную страну ────────────────────


def test_выбранная_страна_сворачивается_повторным_нажатием(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    с_таблицей(monkeypatch, строка_таблицы())
    развёрнута = колонка(открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE"))
    assert "Батуми-1" in развёрнута and 'aria-expanded="true"' in развёрнута
    # Ссылка выбранной строки ведёт на свёрнутое состояние…
    строка_ge = next(ч for ч in развёрнута.split("<a ") if "/country/GE" in ч and "is-on" in ч)
    assert "fold=1" in строка_ge
    # …а там пиццерий в колонке нет, строка помнит «свёрнуто», и следующее нажатие развернёт.
    свёрнута = колонка(открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE?fold=1"))
    assert "Батуми-1" not in свёрнута and 'aria-expanded="false"' in свёрнута
    строка_ge = next(ч for ч in свёрнута.split("<a ") if "/country/GE" in ч and "is-on" in ч)
    assert "fold=1" not in строка_ge


def test_выбранная_пиццерия_держит_список_раскрытым_даже_при_fold(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    с_таблицей(monkeypatch, строка_таблицы())
    рейка = колонка(открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE?unit=u-1&fold=1"))
    assert "Батуми-1" in рейка


def test_нажатие_на_другую_страну_не_несёт_fold(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    рейка = колонка(открыть(стенд, monkeypatch, данные(), "/country/GE?fold=1"))
    ссылка_am = next(ч for ч in рейка.split("<a ") if "/country/AM" in ч)
    assert "fold" not in ссылка_am


# ── справа: у страны — проверки страны, у пиццерии — её проверки ───────────


def test_у_страны_под_статистикой_список_её_проверок(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    вид = данные()
    справа = открыть(стенд, monkeypatch, вид, "/country/GE").split("</aside>", 1)[1]
    assert справа.index("cn-facts") < справа.index("pk-tiles") < справа.index("slist__rows")
    assert f"inspection={вид.snapshot.inspections[0].id}" in справа


def test_шапка_держит_период_в_строке_названия_а_сведения_отдельными_блоками(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    с_таблицей(
        monkeypatch,
        строка_таблицы(),
        строка_таблицы(key="u-2", name="X-2", unit_id="u-2", partner="ИП Лотос"),
    )
    справа = открыть(стенд, monkeypatch, с_точкой(данные()), "/country/GE").split("</aside>", 1)[1]
    строка_названия = справа.split('class="cn-facts"', 1)[0]
    assert "speriod" in строка_названия and "cn-head__actions" in строка_названия
    факты = справа.split('class="cn-facts"', 1)[1].split("</dl>", 1)[0]
    assert факты.count("cn-fact__label") >= 2 and "cn-chip" in факты and "cn-badge" in факты
    assert "ООО Ромашка" in факты and "ИП Лотос" in факты


# ── «Мои страны»: сужает и сохраняется ─────────────────────────────────────


def test_сохранённый_отбор_оставляет_в_колонке_только_выбранные(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    monkeypatch.setattr(country_filter, "saved", lambda: ("GE", "AM"))
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    рейка = колонка(страница)
    assert "/country/AM" in рейка and "/country/GE" in рейка and "/country/TR" not in рейка
    assert "2 из 3" in страница  # подпись «Мои страны» говорит, что отбор действует


def test_отбор_не_прячет_открытую_адресом_страну(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    monkeypatch.setattr(country_filter, "saved", lambda: ("AM",))
    список = колонка(открыть(стенд, monkeypatch, данные(), "/country/GE"))
    assert "/country/GE" in список and "/country/AM" in список and "/country/TR" not in список


def test_отбор_без_пересечения_с_охватом_не_применяется(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    monkeypatch.setattr(country_filter, "saved", lambda: ("JP",))
    список = колонка(открыть(стенд, monkeypatch, данные(), "/country/GE"))
    assert all(f"/country/{к}" in список for к in ("AM", "GE", "TR"))


class Профиль:
    """Двойник профиля: что записали в `web_users.country_filter`."""

    def __init__(self) -> None:
        self.записано: list[tuple[str, tuple[str, ...]]] = []

    def __call__(self, token: str, countries: tuple[str, ...]) -> bool:
        self.записано.append((token, countries))
        return True


@pytest.fixture
def профиль(monkeypatch: pytest.MonkeyPatch) -> Профиль:
    двойник = Профиль()
    monkeypatch.setattr(web_own_profile, "set_country_filter", двойник)
    return двойник


def test_отбор_сохраняется_в_профиль_и_ведёт_обратно_на_экран(
    стенд: FlaskClient, профиль: Профиль
) -> None:
    ответ = стенд.post(
        "/country/filter",
        data={"countries": ["ge", "AM", "мусор"], "next": "/country/GE?unit=u-1"},
        headers=ЗАГОЛОВКИ,
    )
    assert ответ.status_code == 302 and ответ.headers["Location"].endswith("/country/GE?unit=u-1")
    assert профиль.записано == [(ТОКЕН, ("GE", "AM"))]


def test_кластер_одной_кнопкой_ставит_его_страны(
    стенд: FlaskClient, профиль: Профиль, monkeypatch: pytest.MonkeyPatch
) -> None:
    строки = [
        ratings_read.CountryRow(код, код, код, None, True, кластер)
        for код, кластер in (("GE", "CAUCASUS"), ("AM", "CAUCASUS"), ("TR", "TR"))
    ]
    monkeypatch.setattr(ratings_read, "countries", lambda: tuple(строки))
    стенд.post(
        "/country/filter", data={"cluster": "CAUCASUS", "next": "/country"}, headers=ЗАГОЛОВКИ
    )
    assert профиль.записано == [(ТОКЕН, ("AM", "GE"))]


def test_все_страны_снимает_отбор(стенд: FlaskClient, профиль: Профиль) -> None:
    стенд.post("/country/filter", data={"reset": "1", "next": "/country"}, headers=ЗАГОЛОВКИ)
    assert профиль.записано == [(ТОКЕН, ())]


def test_отбор_из_чужого_источника_отказ(стенд: FlaskClient, профиль: Профиль) -> None:
    ответ = стенд.post(
        "/country/filter", data={"countries": ["GE"]}, headers={"Origin": "https://evil.example"}
    )
    assert ответ.status_code == 403 and профиль.записано == []


def test_отбор_человека_приезжает_с_его_сессией(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сохранённый в профиле отбор действует при следующем заходе без всяких параметров в адресе."""
    monkeypatch.setattr(cn, "countries", lambda **_: СТРАНЫ)
    monkeypatch.setattr(
        auth,
        "resolve_session",
        lambda token: (
            Учётка(tenant="default", role="admin", country_filter=("TR",))
            if token == ТОКЕН
            else None
        ),
    )
    список = колонка(открыть(стенд, monkeypatch, данные(), "/country/TR"))
    assert "/country/TR" in список and "/country/AM" not in список and "/country/GE" not in список


def test_партнёру_отбор_не_расширяет_охват(
    стенд: FlaskClient, профиль: Профиль, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.web.auth.reach_of",
        lambda tenant: __import__("src.db.reach", fromlist=["Reach"]).Reach(tenant, None, ("GE",)),
    )
    стенд.post(
        "/country/filter", data={"countries": ["GE", "TR"], "next": "/country"}, headers=ЗАГОЛОВКИ
    )
    assert профиль.записано[-1][1] == ("GE",)


# ── «Настройки страны» — только администратору ─────────────────────────────


def _стенд_роли(monkeypatch: pytest.MonkeyPatch, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role=role)
    monkeypatch.setattr(cn, "countries", lambda **_: (("GE", 1),))
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def админ(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд_роли(monkeypatch, "admin")


@pytest.fixture
def девелопер(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд_роли(monkeypatch, "developer")


def test_кнопка_настроек_страны_у_админа(
    админ: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "Настройки страны" in открыть(админ, monkeypatch, данные(), "/country/GE")


def test_остальным_кнопки_настроек_нет_и_панель_по_адресу_не_открывается(
    девелопер: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "Настройки страны" not in открыть(девелопер, monkeypatch, данные(), "/country/GE")
    страница = открыть(девелопер, monkeypatch, данные(), "/country/GE?settings=1")
    i = страница.find("country/GE/settings")
    assert i < 0, страница[max(0, i - 300) : i + 100]
    assert 'class="sdrawer"' not in страница


def test_панель_настроек_открывается_на_этом_же_экране(
    админ: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.db.spaces import SpaceRow

    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (SpaceRow("HQ", "УК", (), 3), SpaceRow("LOTOS", "Лотос", (), 1)),
    )
    страница = открыть(админ, monkeypatch, данные(), "/country/GE?settings=1")
    assert "data-drawer" in страница and "/country/GE/settings/developer" in страница
    assert "/country/GE/settings/space" in страница and "Лотос" in страница
    # Список проверок и плитки остаются на месте: экран тот же.
    assert "pk-tiles" in страница


def test_девелопера_сохраняет_админ_через_справочник_рейтингов(
    админ: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    записано: list[tuple[Any, ...]] = []

    def запись(code: str, developer: str | None, *, actor: str) -> bool:
        записано.append((code, developer, actor))
        return True

    monkeypatch.setattr(ratings_read, "set_developer", запись)
    ответ = админ.post(
        "/country/GE/settings/developer", data={"developer": " Иван "}, headers=ЗАГОЛОВКИ
    )
    assert (
        ответ.status_code == 302
        and "settings=1" in ответ.headers["Location"]
        and "saved=ok" in ответ.headers["Location"]
    )
    assert записано == [("GE", "Иван", "director")]


def test_партнёра_страны_закрепляет_админ_тем_же_способом_что_экран_людей(
    админ: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    позвали: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        partner_spaces,
        "add_countries",
        lambda space, codes: позвали.append((space, codes)) or codes,
    )
    ответ = админ.post("/country/GE/settings/space", data={"space": "LOTOS"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and "saved=ok" in ответ.headers["Location"]
    assert позвали == [("LOTOS", ("GE",))]


@pytest.mark.parametrize("путь", ["/country/GE/settings/developer", "/country/GE/settings/space"])
def test_остальным_ролям_адреса_настроек_закрыты_и_ничего_не_пишут(
    девелопер: FlaskClient, monkeypatch: pytest.MonkeyPatch, путь: str
) -> None:
    записано: list[Any] = []
    monkeypatch.setattr(ratings_read, "set_developer", lambda *a, **k: записано.append(a) or True)
    monkeypatch.setattr(partner_spaces, "add_countries", lambda *a: записано.append(a) or ())
    ответ = девелопер.post(путь, data={"developer": "X", "space": "LOTOS"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code in (403, 404) and записано == []


def test_отказ_сохранения_говорит_словами(
    админ: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratings_read, "set_developer", lambda *a, **k: False)
    ответ = админ.post("/country/GE/settings/developer", data={"developer": "X"}, headers=ЗАГОЛОВКИ)
    assert "saved=failed" in ответ.headers["Location"]
    monkeypatch.setattr(partner_spaces, "overview", lambda: ())
    assert "Не сохранилось" in открыть(
        админ, monkeypatch, данные(), "/country/GE?settings=1&saved=failed"
    )


def test_модуль_настроек_знает_свои_исходы() -> None:
    assert country_settings.SAVED == "ok" and country_settings.FAILED == "failed"
