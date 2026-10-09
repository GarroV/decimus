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

from src.db.models import ORIGIN_FIELD, ORIGIN_LEGACY, InspectionRow
from src.db.reach import own_reach
from src.web import app as app_mod
from src.web import overview as ov
from src.web.texts import t as _t

ПУСТО = ov.Overview(
    units_total=0,
    inspections=(),
    grades=(),
    average=None,
    zone_losses=(),
    systemic=(),
    attention=(),
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
    }
    основа.update(поля)
    основа["grades"] = ov._grades(основа["inspections"])  # type: ignore[arg-type]
    ряд = основа["inspections"]
    основа.setdefault("inspections_total", len(ряд))  # type: ignore[arg-type]
    основа.setdefault("units_checked", len({r.unit_name for r in ряд}))  # type: ignore[attr-defined]
    основа.setdefault(
        "critical_total",
        sum(1 for a in основа["attention"] if a.why == "critical"),  # type: ignore[attr-defined]
    )
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


def test_средняя_в_плитке_показывается_всегда_когда_есть(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Смена методики плитку не гасит (D352): средняя есть — она на экране."""
    # Act
    страница = показать(стенд, monkeypatch, снимок(average_delta=-1.5))

    # Assert
    assert "83.5" in страница
    assert "-1.5" in страница
    assert "разные чек-листы" not in страница


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


def test_каждая_плитка_ведёт_куда_то(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
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


# ── Отбор выборки, разбивка и движение оценки (канон прототипа) ───────────


def проверка(
    unit: str,
    pct: float,
    grade: str,
    *,
    версия: str,
    когда: date,
    происхождение: str = ORIGIN_FIELD,
) -> InspectionRow:
    """Строка ряда с заданными изданием методики, датой и происхождением."""
    основа = строка(unit, pct, grade)
    return InspectionRow(
        **{
            **{поле: getattr(основа, поле) for поле in основа.__dataclass_fields__},
            "checklist_version": версия,
            "inspection_date": когда,
            "id": f"{unit}-{когда.isoformat()}",
            "origin": происхождение,
        }
    )


def test_неизвестный_период_в_адресе_показывает_всё_время() -> None:
    """Опечатка в адресе не повод показать человеку страницу ошибки.

    Период приходит из адресной строки: его правит человек руками, его
    переносят из чужого письма. Отказом на непонятное значение экран сети
    закрывался бы от владельца ровно тогда, когда тот делится ссылкой.
    """
    # Act
    окно = ov.window("выдумка", today=date(2026, 9, 24))

    # Assert
    assert окно == (None, None), "непонятный период обязан читаться как «всё время»"


def test_окно_периода_считается_от_сегодня_а_не_от_календаря() -> None:
    # Act
    начало, конец = ov.window("d30", today=date(2026, 9, 24))

    # Assert — ровно 30 дней назад, а не «начало месяца».
    assert (начало, конец) == (date(2026, 8, 25), date(2026, 9, 24))


def test_разбивка_усредняет_город_из_разных_изданий_и_исторической() -> None:
    """Оценка каждой проверки верна по своей методике (D352): средняя города
    и её движение считаются по всем проверкам, в том числе исторической."""
    # Arrange — сейчас два издания, раньше историческая по старой методике.
    ряд = (
        проверка("Белград-1", 90.0, "A", версия="2026.09", когда=date(2026, 9, 20)),
        проверка("Белград-2", 70.0, "D", версия="2026.06", когда=date(2026, 9, 18)),
    )
    раньше = (
        проверка(
            "Белград-1",
            85.0,
            "",
            версия="legacy:Qvalon 133",
            когда=date(2026, 8, 1),
            происхождение=ORIGIN_LEGACY,
        ),
    )
    гео = {"Белград-1": ("RS", "Белград"), "Белград-2": ("RS", "Белград")}

    # Act
    разбивка = ov._breakdown(ряд, geo=гео, counts={}, before=раньше)

    # Assert
    assert len(разбивка) == 1
    assert разбивка[0].average == 80.0
    assert разбивка[0].delta == -5.0


def test_движение_точки_считается_против_проверки_другого_издания() -> None:
    """Смена издания движение точки не гасит (D352): обе оценки верны."""
    # Arrange — у точки две проверки, и они посчитаны разными изданиями.
    ряд = (
        проверка("Белград-1", 71.5, "D", версия="2026.09", когда=date(2026, 9, 20)),
        проверка("Белград-1", 90.0, "A", версия="2026.06", когда=date(2026, 8, 20)),
    )

    # Act
    точки = ov._points(ряд, geo={}, counts={}, worst={})

    # Assert
    assert len(точки) == 1
    assert точки[0].delta == -18.5


def test_движение_точки_считается_против_исторической() -> None:
    # Arrange — прошлая проверка загружена из старого отчёта (D332).
    ряд = (
        проверка("Белград-1", 92.0, "A", версия="2026.09", когда=date(2026, 9, 20)),
        проверка(
            "Белград-1",
            88.0,
            "",
            версия="legacy:old 253",
            когда=date(2025, 9, 20),
            происхождение=ORIGIN_LEGACY,
        ),
    )

    # Act / Assert
    assert ov._points(ряд, geo={}, counts={}, worst={})[0].delta == 4.0


def test_движение_оценки_считается_когда_издание_то_же() -> None:
    # Arrange
    ряд = (
        проверка("Белград-1", 71.5, "D", версия="2026.09", когда=date(2026, 9, 20)),
        проверка("Белград-1", 90.0, "A", версия="2026.09", когда=date(2026, 8, 20)),
    )

    # Act
    точки = ov._points(ряд, geo={}, counts={}, worst={})

    # Assert — минус восемнадцать с половиной, а не «—».
    assert точки[0].delta == -18.5


def test_точка_без_города_в_разбивке_не_пропадает() -> None:
    """Иначе «в разбивке 40 точек, а в сети 150» становится необъяснимым.

    Пропавшая строка выглядит как отсутствие проблемы; строка «Без города» —
    как вопрос к справочнику, и это верное прочтение.
    """
    # Arrange
    ряд = (проверка("Белград-1", 71.5, "D", версия="2026.09", когда=date(2026, 9, 20)),)

    # Act
    разбивка = ov._breakdown(ряд, geo={}, counts={})

    # Assert
    assert [строка_.city for строка_ in разбивка] == [""]
    assert разбивка[0].units == 1


def test_проблемные_точки_отбираются_по_причине_а_не_по_низу_списка() -> None:
    """«Шесть худших» — это всегда шесть строк, даже когда в сети всё хорошо.

    Такой список человек привыкает читать как шум. Отбор по причине бывает
    пустым, и пустота здесь — ответ, а не поломка.
    """
    # Arrange — три здоровые точки: критических нет, падения нет, буквы A и B.
    ряд = (
        проверка("Белград-1", 95.0, "A", версия="2026.09", когда=date(2026, 9, 20)),
        проверка("Белград-2", 92.0, "B", версия="2026.09", когда=date(2026, 9, 19)),
        проверка("Тбилиси-3", 90.0, "B", версия="2026.09", когда=date(2026, 9, 18)),
    )

    # Act
    точки = ov._points(ряд, geo={}, counts={}, worst={})
    проблемные = ov._problems(точки)

    # Assert
    assert проблемные == (), "у здоровой сети список поводов обязан быть пустым"


def test_причина_попадания_в_проблемные_записана_кодом_и_по_весу() -> None:
    # Arrange — сожжённая зона у одной, слабая буква у другой.
    ряд = (
        проверка("Белград-1", 88.0, "B", версия="2026.09", когда=date(2026, 9, 20)),
        проверка("Тбилиси-2", 71.0, "D", версия="2026.09", когда=date(2026, 9, 19)),
    )
    счёт = {"Белград-1-2026-09-20": {"D3": 2}}

    # Act
    проблемные = ov._problems(ov._points(ряд, geo={}, counts=счёт, worst={}))

    # Assert — сожжённая зона весит больше слабой буквы и идёт первой.
    assert [(т.unit, т.why) for т in проблемные] == [
        ("Белград-1", "critical"),
        ("Тбилиси-2", "low_grade"),
    ]


def test_средняя_и_движение_сети_считаются_по_разным_изданиям_и_исторической(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D352: смена методики не гасит ни среднюю, ни её движение.

    Сводка среза из базы — уже без разбивки по изданиям: в окне сейчас
    проверки двух изданий, в прошлом окне — историческая без буквы.
    """

    # Arrange
    class База(ЗаписнаяБаза):
        def slice_summary(self, **kw: object) -> tuple[int, list[tuple[str, int, float]]]:
            if kw.get("date_from") == date(2026, 8, 25):
                return 2, [("A", 1, 90.0), ("D", 1, 70.0)]
            return 1, [("", 1, 85.0)]

    monkeypatch.setattr(ov, "queries", База())

    # Act
    данные = ov.load(
        reach=own_reach(ТЕНАНТ),
        limit=50,
        selection=ov.Selection(period="d30"),
        today=date(2026, 9, 24),
    )

    # Assert
    assert данные.average == 80.0
    assert данные.average_delta == -5.0


def test_у_периода_всё_время_прошлого_окна_нет() -> None:
    """Сравнивать «всё время» с чем-то до него бессмысленно: до него ничего нет."""
    # Act & Assert
    assert ov.window_before("all", today=date(2026, 9, 24)) == (None, None)


def test_порядок_таблицы_меняется_выбором_человека() -> None:
    # Arrange — худшая по проценту проверена раньше всех.
    ряд = (
        проверка("Тбилиси-2", 95.5, "A", версия="2026.09", когда=date(2026, 9, 22)),
        проверка("Белград-1", 71.5, "D", версия="2026.09", когда=date(2026, 9, 10)),
    )
    точки = ov._points(ряд, geo={}, counts={}, worst={})

    # Act
    по_оценке = ov.sorted_points(точки, "score")
    по_дате = ov.sorted_points(точки, "date")

    # Assert — порядки разные, и каждый свой: худшее сверху против свежего сверху.
    assert [т.unit for т in по_оценке] == ["Белград-1", "Тбилиси-2"]
    assert [т.unit for т in по_дате] == ["Тбилиси-2", "Белград-1"]


def test_непонятный_порядок_в_адресе_не_роняет_таблицу() -> None:
    """Код порядка приходит из адресной строки — её правят руками."""
    # Arrange
    ряд = (
        проверка("Тбилиси-2", 95.5, "A", версия="2026.09", когда=date(2026, 9, 22)),
        проверка("Белград-1", 71.5, "D", версия="2026.09", когда=date(2026, 9, 10)),
    )
    точки = ov._points(ряд, geo={}, counts={}, worst={})

    # Act
    выдумка = ov.sorted_points(точки, "как-нибудь")

    # Assert — тот же порядок, что у умолчания, а не отказ и не случайный.
    assert выдумка == ov.sorted_points(точки, "score")


def test_умолчания_не_висят_в_адресе_среза(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sort=score` и `period=all` в каждой ссылке делают срез «настроенным».

    Человек копирует такую ссылку, видит в ней параметры и считает, что
    получил чей-то отбор, — а это обычный экран.
    """
    # Act
    страница = показать(стенд, monkeypatch, снимок())

    # Assert
    assert "sort=score" not in страница
    assert "period=all" not in страница


class ЗаписнаяБаза:
    """Заглушка слоя базы, запоминающая, с чем её позвали.

    Проверять сужение по факту ответа нельзя: заглушка вернёт что угодно.
    Проверяется именно то, что отбор человека доехал до запроса, — потому что
    сбой был ровно здесь: запрос звали без города, а ответ показывали рядом с
    сузившейся таблицей.
    """

    def __init__(self) -> None:
        self.звонки: dict[str, dict[str, object]] = {}

    def _записать(self, имя: str, kwargs: dict[str, object]) -> None:
        self.звонки[имя] = kwargs

    def unit_geography(self, **kw: object) -> dict[str, tuple[str, str]]:
        return {"Белград-1": ("RS", "Белград")}

    def unit_ids(self, **kw: object) -> dict[str, str]:
        return {"Белград-1": "11111111-2222-3333-4444-555555555555"}

    def units_total(self, **kw: object) -> int:
        return 1

    def list_inspections(self, **kw: object) -> tuple[InspectionRow, ...]:
        self._записать("list_inspections", kw)
        return ()

    def slice_summary(self, **kw: object) -> tuple[int, list[tuple[str, int, float]]]:
        self._записать("slice_summary", kw)
        return 0, []

    def class_counts(self, **kw: object) -> dict[str, dict[str, int]]:
        self._записать("class_counts", kw)
        return {}

    def worst_zones(self, **kw: object) -> dict[str, tuple[str, str, str, float]]:
        self._записать("worst_zones", kw)
        return {}

    def zone_losses(self, **kw: object) -> list[tuple[str, str, str, float, int, int]]:
        self._записать("zone_losses", kw)
        return []

    def systemic_findings(self, **kw: object) -> list[tuple[str, str, int, int, str, str]]:
        self._записать("systemic_findings", kw)
        return []


def test_отбор_сужает_и_те_блоки_что_считаются_запросом(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Город и буква доезжают до потерь по зонам и системных нарушений.

    Без этого экран показывает два множества сразу: таблица точек — выбранный
    город, а «Где сеть теряет проценты» — всю сеть, и цифры рядом выглядят
    одним разговором.
    """
    # Arrange
    база = ЗаписнаяБаза()
    monkeypatch.setattr(ov, "queries", база)

    # Act
    ov.load(
        reach=own_reach(ТЕНАНТ),
        limit=50,
        selection=ov.Selection(city="Белград", country="RS", grade="D"),
        today=date(2026, 9, 24),
    )

    # Assert — ряд проверок и все четыре агрегата спрошены с тем же отбором,
    # а не по сети (#470: ряд, отобранный поверх сотни по сети, терял срез).
    assert set(база.звонки) == {
        "list_inspections",
        "slice_summary",
        "class_counts",
        "worst_zones",
        "zone_losses",
        "systemic_findings",
    }
    for имя, kwargs in база.звонки.items():
        assert kwargs.get("city") == "Белград", имя
        assert kwargs.get("country") == "RS", имя
        assert kwargs.get("grade") == "D", имя


def test_пустой_отбор_не_сужает_агрегаты(monkeypatch: pytest.MonkeyPatch) -> None:
    """Экран без отбора обязан показывать сеть целиком.

    Пустая строка, доехавшая до запроса как значение, отсекла бы всё: город
    «» не совпадает ни с одной точкой. Поэтому «не сужать» передаётся пустым
    значением, которое слой базы превращает в NULL.
    """
    # Arrange
    база = ЗаписнаяБаза()
    monkeypatch.setattr(ov, "queries", база)

    # Act
    ov.load(reach=own_reach(ТЕНАНТ), limit=50, today=date(2026, 9, 24))

    # Assert
    for имя, kwargs in база.звонки.items():
        assert kwargs.get("city") == "", имя
        assert kwargs.get("grade") == "", имя


def test_при_выбранной_стране_города_только_её() -> None:
    # Arrange — 24.09.2026 при выбранной Турции в списке стояли Тбилиси и Батуми.
    гео = {
        "Tbilisi-1": ("GE", "tbilisi"),
        "Tbilisi-2": ("GE", "tbilisi"),
        "Antalya-1": ("TR", "antalya"),
    }

    # Act
    страны, города = ov._geo_choices(гео, selection=ov.Selection(country="TR"))

    # Assert — страны все (иначе на другую не переключиться), города — турецкие.
    assert страны == (("GE", 2), ("TR", 1))
    assert города == (("antalya", 1),)


def test_город_без_страны_в_разбивке_ведёт_в_реестр_проверок_города(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    данные = снимок(
        breakdown=(
            ov.CityRow(
                city="tbilisi",
                country="",
                units=3,
                inspections=2,
                average=90.0,
                grades=(),
                critical=0,
                delta=None,
            ),
        )
    )

    # Act
    страница = показать(стенд, monkeypatch, данные)

    # Assert — без страны экрана страны нет (D260): ссылка в реестр с кодом
    # города, а на экране город словом.
    assert 'href="/inspections?city=tbilisi' in страница
    assert "Тбилиси" in страница
    assert ">tbilisi<" not in страница


def test_точки_справочника_считаются_в_выбранном_месте() -> None:
    # Arrange — 25.09.2026 при Грузии плитка показывала 151 точку всей сети.
    гео = {
        "Tbilisi-1": ("GE", "tbilisi"),
        "Batumi-1": ("GE", "batumi"),
        "Antalya-1": ("TR", "antalya"),
    }

    # Act / Assert
    assert ov._units_in(гео, selection=ov.Selection(country="GE")) == 2
    assert ov._units_in(гео, selection=ov.Selection(city="batumi")) == 1
    assert ov._units_in(гео, selection=ov.Selection(country="RS")) == 0
    assert ov._units_in(гео, selection=ov.Selection(grade="D")) is None


def test_пункт_на_одной_точке_системным_не_считается(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Системные» — пункт, нарушенный на двух точках и больше.

    Пункт на одной точке — это одна точка, её показывают «Проблемные точки».
    До правки блок перечислял всё подряд, и на демо все шесть «системных»
    стояли с подписью «точек: 1».
    """

    # Arrange
    class База(ЗаписнаяБаза):
        def systemic_findings(self, **kw: object) -> list[tuple[str, str, int, int, str, str]]:
            return [("K-1", "D1", 5, 3, "", ""), ("K-2", "D1", 4, 1, "", "")]

    monkeypatch.setattr(ov, "queries", База())

    # Act
    данные = ov.load(reach=own_reach(ТЕНАНТ), limit=50, today=date(2026, 9, 24))

    # Assert
    assert [item.code for item in данные.systemic] == ["K-1"]


# --- «Обзор» ведёт в страну (D260) --------------------------------------------


def точка(unit: str, country: str, city: str) -> ov.PointRow:
    return ov.PointRow(
        unit=unit,
        city=city,
        country=country,
        inspection_id="11111111-2222-3333-4444-000000000009",
        when=date(2026, 9, 20),
        grade="B",
        pct=90.0,
        delta=None,
        worst_zone_ru="",
        worst_zone_en="",
        critical=0,
    )


def t_ru(key: str) -> str:
    return _t(key, "ru")


def test_точка_на_обзоре_ведёт_в_страну_с_раскрытой_точкой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    данные = снимок(points=(точка("Батуми-1", "GE", "batumi"),), unit_ids={"Батуми-1": "u-1"})
    страница = показать(стенд, monkeypatch, данные)
    assert "/country/GE?" in страница and "unit=u-1" in страница
    assert "#unit-u-1" in страница


def test_точка_без_страны_ведёт_в_карточку_как_раньше(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    данные = снимок(points=(точка("Без-1", "", ""),), unit_ids={"Без-1": "u-9"})
    страница = показать(стенд, monkeypatch, данные)
    assert "/units/u-9" in страница
    assert "/country/?" not in страница and "/country/-" not in страница


def test_город_в_разбивке_ведёт_в_страну_с_городом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    город = ov.CityRow(
        city="batumi",
        country="GE",
        units=1,
        inspections=1,
        average=90.0,
        grades=(("B", 1),),
        critical=0,
    )
    страница = показать(стенд, monkeypatch, снимок(breakdown=(город,)))
    assert "/country/GE?" in страница and "city=batumi" in страница


def test_назначить_проверку_на_обзоре_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = показать(стенд, monkeypatch, снимок())
    assert t_ru("overview.assign") not in страница


def test_обрезанный_срез_экран_называет_вслух(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #470: ряд длиннее предела показан не целиком — молча это читалось бы
    # как весь срез, а соседние блоки считаются по всему.
    обрезан = показать(стенд, monkeypatch, снимок(truncated=True))
    целый = показать(стенд, monkeypatch, снимок())

    assert "В срезе больше 2 проверок" in обрезан
    assert "В срезе больше" not in целый
