"""«Где нужно проверить» (D399): отбор точек и охват.

Блок переехал с «Главной» (D418), затем с «Проверок» в «Календарь» (D466), а с
«Календаря» снят (D497, «пока скрой»): модуль ждёт своего экрана.
Сторожится:
кто попадает в ряд и в каком порядке, что чтение идёт в охвате вошедшего, что
пустой блок не показывается, а отказ базы называется строкой, а не тишиной.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, шапка
from web_harness import войти, подменить_двери, собрать

from src.db.errors import DbError
from src.db.reach import Reach
from src.web import inspections as data
from src.web import to_inspect
from src.web.texts import t


def t_ru(ключ: str) -> str:
    return t(ключ, "ru")


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(
        data, "load_registry", lambda **_: data.Registry((шапка(unit_name="Белград-1"),), True)
    )
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _блок(*имена: str, ещё: int = 0, отказ: bool = False) -> to_inspect.Block:
    точки = tuple(
        to_inspect.ToCheck(имя, f"u-{n}", "RS", "", date(2026, 7, 1) if n % 2 else None)
        for n, имя in enumerate(имена)
    )
    return to_inspect.Block(units=точки, more=ещё, failed=отказ)


def test_отбирает_точки_без_проверок_за_период() -> None:
    """Проверенные за период не попадают; ни разу не проверенные — первыми, затем давнее всех."""
    # Arrange
    строки = [
        ("Свежая", "c1", date(2026, 9, 20), 1),
        ("Давняя", "c2", date(2026, 3, 1), 0),
        ("Недавняя", "c3", date(2026, 8, 1), 0),
        ("Новая", "c4", None, 0),
        ("Чужая страна", "c5", None, 0),
    ]
    гео = {n: ("RS", "") for n, *_ in строки} | {"Чужая страна": ("GE", "")}

    # Act
    ждут, ещё = to_inspect.pick_units(строки, geo=гео, ids={}, country="RS")

    # Assert
    assert [т.unit for т in ждут] == ["Новая", "Давняя", "Недавняя"]
    assert ещё == 0


def test_ряд_ограничен_остаток_числом() -> None:
    строки = [(f"П-{n:02d}", "", None, 0) for n in range(to_inspect.TO_CHECK_TOP + 3)]

    ждут, ещё = to_inspect.pick_units(строки, geo={}, ids={})

    assert len(ждут) == to_inspect.TO_CHECK_TOP and ещё == 3


def test_отбор_по_городу_и_части_названия() -> None:
    строки = [("Белград-1", "", None, 0), ("Белград-2", "", None, 0), ("Нови-Сад-1", "", None, 0)]
    гео = {
        "Белград-1": ("RS", "beograd"),
        "Белград-2": ("RS", "beograd"),
        "Нови-Сад-1": ("RS", "ns"),
    }

    ждут, _ = to_inspect.pick_units(строки, geo=гео, ids={}, city="beograd", query="2")

    assert [т.unit for т in ждут] == ["Белград-2"]


class _База:
    """Слой базы, запоминающий охват и окно, с которыми его позвали."""

    def __init__(self) -> None:
        self.звал: dict[str, object] = {}

    def unit_geography(self, **kw: object) -> dict[str, tuple[str, str]]:
        return {"Н": ("GE", "")}

    def unit_ids(self, **kw: object) -> dict[str, str]:
        return {}

    def unit_last_inspections(self, **kw: object) -> list[tuple[str, str, date | None, int]]:
        self.звал = kw
        return [("Н", "c", None, 0)]


def test_читается_в_охвате_вошедшего_и_в_периоде_реестра(monkeypatch: pytest.MonkeyPatch) -> None:
    """Партнёр получает точки только своего охвата: запрос зовут с его `reach` и окном реестра."""
    # Arrange
    база = _База()
    monkeypatch.setattr(to_inspect, "queries", база)
    партнёр = Reach(tenant="GE", tenants=None, countries=("GE",))

    # Act
    блок = to_inspect.load(reach=партнёр, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))

    # Assert
    assert база.звал["reach"] == партнёр
    assert (база.звал["date_from"], база.звал["date_to"]) == (date(2026, 9, 1), date(2026, 9, 30))
    assert [т.unit for т in блок.units] == ["Н"]


def test_отказ_базы_блок_называет_а_не_прячет(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class Отказ(_База):
        def unit_geography(self, **kw: object) -> dict[str, tuple[str, str]]:
            raise DbError("нет связи")

    monkeypatch.setattr(to_inspect, "queries", Отказ())

    # Act
    блок = to_inspect.load(reach=Reach("HQ", None, None), date_from=None, date_to=None)

    # Assert
    assert блок.failed and блок.shown


def test_проверки_показывают_блок_с_отбором_экрана(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D501: блок вернулся на «Проверки», период и отбор — те же, что у «Принятых»."""
    # Arrange
    спросили: list[dict[str, object]] = []
    имена = [f"Точка-{n}" for n in range(to_inspect.TO_CHECK_TOP + 2)]
    monkeypatch.setattr(to_inspect, "load", lambda **kw: спросили.append(kw) or _блок(*имена))

    # Act
    страница = стенд.get("/inspections?from=2026-09-01&to=2026-09-30&country=RS&q=xy").get_data(
        as_text=True
    )

    # Assert
    assert t_ru("registry.tocheck.title") in страница
    assert all(имя in страница for имя in имена)
    assert "и ещё 2" in страница
    assert (спросили[0]["date_from"], спросили[0]["date_to"]) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert (спросили[0]["country"], спросили[0]["query"]) == ("RS", "xy")


def test_проверки_пустой_блок_одна_строка(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(to_inspect, "load", lambda **_: to_inspect.Block())

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert t_ru("registry.tocheck.empty") in страница


def test_проверки_отказ_блока_называется_строкой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(to_inspect, "load", lambda **_: to_inspect.Block(failed=True))

    страница = стенд.get("/inspections").get_data(as_text=True)

    assert t_ru("registry.tocheck.failed") in страница
