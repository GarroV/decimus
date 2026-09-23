"""Экран «Обзор сети»: показывает записанное и молчит там, где данных нет.

Экран заведён по брифу на визуал (`docs/08-design-brief.md`, экран 01) и по
прототипу владельца (D188, D190). Он отвечает на один вопрос — куда смотреть
сегодня, — и потому собран вокруг поводов, а не вокруг красивых чисел.

ЧТО ЗДЕСЬ СТОРОЖИТСЯ, а что сознательно нет. Проверяется, что на экран
попадает ровно то, что лежит в снимке, и что блок без данных говорит об этом
словами. Не проверяется вёрстка: на неё нет способа написать тест, который
краснел бы по делу, — расхождение с прототипом ловится глазами и сверкой
экрана с эталоном.

ГЛАВНОЕ, ЧТО ЗДЕСЬ СТОРОЖИТСЯ, — молчание. Блок, под который нет данных,
обязан сказать об этом: исчезнувший блок читается как «здесь всё в порядке», а
это не то же самое, что «сюда никто не смотрел».
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ
from web_harness import войти, подменить_двери, собрать

from src.db.models import InspectionRow
from src.web import app as app_mod
from src.web import overview as ov

ПУСТО = ov.Overview(
    units_total=0,
    inspections=(),
    grades=(),
    average=None,
    comparable=True,
    comparability_note="",
    zone_losses=(),
    systemic=(),
    attention=(),
    problem_units=(),
)


def строка(unit: str, pct: float, grade: str, *, findings: int = 3) -> InspectionRow:
    return InspectionRow(
        id=f"11111111-2222-3333-4444-{abs(hash(unit)) % 10**12:012d}",
        tenant_code=ТЕНАНТ,
        unit_name=unit,
        chat_id=1,
        kind="planned",
        inspection_date=date(2026, 9, 20),
        report_lang="ru",
        checklist_version="2026.09",
        pct=pct,
        grade=grade,
        findings_count=findings,
        pushed_at="2026-09-20T10:00:00+00:00",
        auditor="Проверяющий",
        city="Белград",
        partner="",
        contact="",
        checklist_code="bizdev",
        retracted=None,
        retraction_reason=None,
    )


def снимок(**поля: object) -> ov.Overview:
    основа = {
        "units_total": 150,
        "inspections": (строка("Белград-1", 71.5, "D"), строка("Тбилиси-2", 95.5, "B")),
        "average": 83.5,
        "comparable": True,
        "comparability_note": "",
        "zone_losses": (
            ov.ZoneLoss(
                code="kitchen",
                name_ru="Кухня",
                name_en="Kitchen",
                loss=18.0,
                inspections=2,
                units=2,
                share=72.0,
            ),
        ),
        "systemic": (ov.Systemic(code="K-041", level="D1", records=5, units=4),),
        "attention": (
            ov.Attention(
                why="critical",
                unit="Белград-1",
                inspection_id="11111111-2222-3333-4444-000000000001",
                when=date(2026, 9, 20),
                detail="2",
                tone="err",
            ),
        ),
        "problem_units": (строка("Белград-1", 71.5, "D"),),
    }
    основа.update(поля)
    основа["grades"] = ov._grades(основа["inspections"])  # type: ignore[arg-type]
    return ov.Overview(**основа)  # type: ignore[arg-type]


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    """Приложение с подменённым снимком сети и вошедшим человеком."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def показать(client: FlaskClient, monkeypatch: pytest.MonkeyPatch, данные: ov.Overview) -> str:
    monkeypatch.setattr(app_mod.overview_data, "load", lambda **_: данные)
    ответ = client.get("/overview")
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def test_поводы_смотреть_сегодня_попадают_на_экран(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = показать(стенд, monkeypatch, снимок())

    # Assert — повод назван точкой и причиной, а не просто счётчиком.
    assert "Белград-1" in страница
    assert "критических нарушений: 2" in страница


def test_потери_по_зонам_показаны_именем_зоны_а_не_кодом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = показать(стенд, monkeypatch, снимок())

    # Assert — имя из снимка проверки, потеря — числом со знаком.
    assert "Кухня" in страница
    assert "−18.0" in страница


def test_системные_нарушения_названы_кодом_пункта(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Act
    страница = показать(стенд, monkeypatch, снимок())

    # Assert — код, класс и охват точек.
    assert "K-041" in страница
    assert "D1" in страница
    assert "точек: 4" in страница


def test_несравнимый_ряд_среднюю_не_показывает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ряд из разных ставок усреднять нельзя — и экран это говорит (T349).

    Без этой проверки экран показывал бы бодрое число, собранное из проверок,
    посчитанных по разной цене, — то самое среднее по несравнимому, ради
    которого признак сравнимости и заводился.
    """
    # Act
    страница = показать(стенд, monkeypatch, снимок(comparable=False))

    # Assert
    assert "Средняя по этой выборке не считается" in страница
    assert "83.5" not in страница


def test_пустые_блоки_говорят_словами_а_не_исчезают(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Исчезнувший блок читается как «здесь всё в порядке» — а это неправда."""
    # Act
    страница = показать(стенд, monkeypatch, ПУСТО)

    # Assert — заголовок каждого блока на месте, и рядом сказано, почему пусто.
    for заголовок in (
        "Требует решения сегодня",
        "Где сеть теряет проценты",
        "Системные нарушения",
        "Проблемные точки",
    ):
        assert заголовок in страница
    assert "Поводов нет" in страница
    assert "Потерь не записано" in страница
    assert "Повторов нет" in страница


def test_каждая_плитка_ведёт_куда_то(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Цифра, из которой нельзя провалиться, на вопрос экрана не отвечает.

    Бриф запрещает «шаблонный дашборд-вид с четырьмя одинаковыми плитками», и
    отличие ровно здесь: у каждой плитки есть адрес перехода.
    """
    # Act
    страница = показать(стенд, monkeypatch, снимок())

    # Assert — плитка на экране ровно одна форма: ссылка. Кнопок без
    # перехода и мёртвых блоков с цифрой быть не должно ни одного.
    плитки = re.findall(r'<(\w+) class="ov-tile[ "]', страница)
    assert плитки, "плиток на экране нет вовсе"
    assert set(плитки) == {"a"}, (
        f"плитка нарисована тегами {sorted(set(плитки))}: всё, что не ссылка, — "
        f"цифра без перехода, а такую бриф на этом экране запрещает"
    )


def test_средняя_без_проверок_не_выдумывается() -> None:
    """Ноль вместо «не из чего считать» читался бы как «сеть на нуле»."""
    assert ov._average(()) is None


def test_буквы_идут_по_шкале_а_не_по_частоте() -> None:
    """Полоса букв читается как шкала: A слева, D справа — всегда."""
    # Arrange — букв D больше, чем A.
    rows = (строка("а", 60.0, "D"), строка("б", 61.0, "D"), строка("в", 99.0, "A"))

    # Act
    порядок = [буква for буква, _ in ov._grades(rows)]

    # Assert
    assert порядок == ["A", "B", "C", "D"]
