"""Экран «Обучение» (D578, #906): доступ, охват партнёра, пустое состояние, вывод цифр.

База не нужна: чтение снимка подменено на границе `src/db/training_read.py`. Живой путь
через настоящую базу — `tests/test_db_learning_schema.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import training_read
from src.db.reach import Reach
from src.domain.training_metrics import Counters

DAY = date(2026, 10, 20)


def _c(assigned: int, completed: int, **kw: int) -> Counters:
    return Counters(assigned=assigned, completed=completed, people_total=10, people_trained=4, **kw)


UNITS = (
    training_read.UnitTotals("d-ro-1", "Brasov-1", "RO", True, _c(100, 10, overdue=3)),
    training_read.UnitTotals("d-ro-2", "Iasi-1", "RO", True, _c(100, 50)),
    training_read.UnitTotals("d-am-1", "Gyumri-1", "AM", True, _c(50, 25)),
    training_read.UnitTotals("d-ro-9", "Bucharest-12", "RO", False, _c(40, 4)),
)
COURSES = (
    training_read.CourseTotals("k1", "Кассир", _c(30, 15, time_sum=1800, time_n=3)),
    training_read.CourseTotals("k2", "Пиццамейкер", _c(70, 7)),
)


@pytest.fixture
def чтения(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    asked: dict[str, list[object]] = {"units": [], "courses": []}

    def units(on_date: date, countries: object) -> tuple[training_read.UnitTotals, ...]:
        asked["units"].append(countries)
        return tuple(u for u in UNITS if countries is None or u.country_code in countries)

    def courses(on_date: date, countries: object, **kw: object) -> tuple:
        asked["courses"].append((countries, kw))
        return COURSES

    monkeypatch.setattr(training_read, "unit_totals", units)
    monkeypatch.setattr(training_read, "course_totals", courses)
    return asked


def _войти(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant: str = "HQ",
    role: str | None = None,
    countries: tuple[str, ...] | None = None,
    loaded: bool = True,
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    # Оснастка по умолчанию — «загрузки не было»; снимок ставится после неё, а не до.
    if loaded:
        monkeypatch.setattr(training_read, "snapshot_date", lambda: DAY)
    if countries is not None:
        monkeypatch.setattr(
            "src.web.auth.reach_of", lambda t: Reach(tenant=t, tenants=None, countries=countries)
        )
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def ук(monkeypatch: pytest.MonkeyPatch, чтения: dict) -> Iterator[FlaskClient]:
    yield from _войти(monkeypatch, role="admin")


def test_сеть_считается_из_сумм_сопоставленных_пиццерий(ук: FlaskClient) -> None:
    page = ук.get("/training").get_data(as_text=True)
    # (10 + 50 + 25) / (100 + 100 + 50) = 34,0%; несопоставленная Bucharest-12 не в счёте.
    assert "34.0%" in page
    assert "Данные на 20.10.2026" in page


def test_проценты_не_среднее_процентов(ук: FlaskClient) -> None:
    page = ук.get("/training/RO").get_data(as_text=True)
    # Румыния: (10 + 50) / 200 = 30,0%, а не среднее 10% и 50% по пиццериям с весами иначе.
    assert "30.0%" in page


def test_страна_раскрывается_пиццериями_и_худшая_сверху(ук: FlaskClient) -> None:
    page = ук.get("/training/RO").get_data(as_text=True)
    assert "pk-item--sub" in page
    table = page.split("tr-table", 1)[1]
    assert table.index("Brasov-1") < table.index("Iasi-1")


def test_несопоставленные_показаны_отдельным_блоком(ук: FlaskClient) -> None:
    page = ук.get("/training").get_data(as_text=True)
    assert "Не сопоставлены" in page and "Bucharest-12" in page
    assert "tr-table--lost" in page


def test_пиццерия_выбирается_адресом_и_курсы_читаются_по_её_подразделению(
    ук: FlaskClient, чтения: dict
) -> None:
    page = ук.get("/training/RO?unit=d-ro-1").get_data(as_text=True)
    assert "Brasov-1" in page and "10.0%" in page
    assert чтения["courses"][-1][1] == {"department": "d-ro-1"}


def test_курсы_страны_читаются_по_стране(ук: FlaskClient, чтения: dict) -> None:
    ук.get("/training/RO")
    assert чтения["courses"][-1][1] == {"country": "RO"}


def test_время_на_курс_словами(ук: FlaskClient) -> None:
    assert "10 мин" in ук.get("/training/RO").get_data(as_text=True)  # 1800 с / 3 = 10 мин


def test_неизвестная_страна_404(ук: FlaskClient) -> None:
    assert ук.get("/training/ZZ").status_code == 404


def test_английский_язык(ук: FlaskClient) -> None:
    page = ук.get("/training/RO?lang=en").get_data(as_text=True)
    assert "Data as of 20.10.2026" in page and "Trained" in page


def test_пункт_меню_в_группе_статистики_рядом_с_рейтингами(ук: FlaskClient) -> None:
    page = ук.get("/training").get_data(as_text=True)
    assert 'href="/training"' in page and "Обучение" in page


def test_пустое_состояние_без_загрузки(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _войти(monkeypatch, role="admin", loaded=False):
        page = client.get("/training").get_data(as_text=True)
        assert "Данные из iSpring ещё не загружены" in page
        assert "Ключи ставит главный администратор" in page


def test_пустое_состояние_зовёт_главного_админа_к_ключам(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _войти(monkeypatch, role="superadmin", loaded=False):
        page = client.get("/training").get_data(as_text=True)
        assert 'href="/users/connections"' in page


def test_сбой_чтения_говорит_словами_а_не_500(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db.errors import LearningError

    def broken() -> date:
        raise LearningError("нет базы")

    for client in _войти(monkeypatch, role="admin"):
        monkeypatch.setattr(training_read, "snapshot_date", broken)
        response = client.get("/training")
        assert response.status_code == 200
        assert "не прочитались" in response.get_data(as_text=True)


@pytest.mark.parametrize("role", ["guest"])
def test_гость_видит_экран(monkeypatch: pytest.MonkeyPatch, чтения: dict, role: str) -> None:
    for client in _войти(monkeypatch, role=role):
        assert client.get("/training").status_code == 200


def test_партнёр_видит_только_свои_страны(monkeypatch: pytest.MonkeyPatch, чтения: dict) -> None:
    for client in _войти(monkeypatch, tenant="GE", role="admin", countries=("AM",)):
        page = client.get("/training").get_data(as_text=True)
        assert "Армения" in page and "Румыния" not in page and "Brasov-1" not in page
        assert чтения["units"][-1] == ("AM",)  # охват ушёл в чтение, а не отфильтрован на экране
        assert "Bucharest-12" not in page


def test_чужая_страна_у_партнёра_тот_же_404_и_до_чтения_не_доходит(
    monkeypatch: pytest.MonkeyPatch, чтения: dict
) -> None:
    for client in _войти(monkeypatch, tenant="GE", role="admin", countries=("AM",)):
        assert client.get("/training/RO").status_code == 404
        assert client.get("/training/ZZ").status_code == 404
    assert чтения["units"] == []


def test_без_входа_экран_закрыт(monkeypatch: pytest.MonkeyPatch, чтения: dict) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        response = client.get("/training")
        assert response.status_code in (302, 401)
        assert "Brasov-1" not in response.get_data(as_text=True)


def test_контролю_экран_закрыт_он_ведёт_только_рейтинги(
    monkeypatch: pytest.MonkeyPatch, чтения: dict
) -> None:
    for client in _войти(monkeypatch, role="control"):
        assert client.get("/training").status_code == 404
