"""Лист «Качество по пиццериям» таблиц контроля (ядро рейтингов, D324).

Строка — девелопер, страна, пиццерия, ссылка на рейтинг, затем колонки-периоды:
РС — полумесяцы «Сентябрь 2», РКО — недели «05.05 — 11.05». Года в подписи нет —
его выводит `assign_years`.
"""

from __future__ import annotations

from datetime import date

import pytest
from ratings_samples import SHEET_RS_HEADER, U1, sheet_csv, sheet_rko, sheet_rs, to_csv

from src.ratings.countries import country_code
from src.ratings.formats import detect_format
from src.ratings.model import (
    ERR_NOT_SHEET,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    ISSUE_DEVELOPER_CONFLICT,
    RKO,
    RS,
    RatingsFormatError,
)
from src.ratings.sheet import (
    HEADER_WINDOW,
    assign_years,
    is_sheet_header,
    parse_label,
    parse_sheet_scores,
)

СЕГОДНЯ = date(2026, 10, 8)


def test_подписи_периодов() -> None:
    rs = parse_label("Сентябрь 2")
    assert rs is not None and (rs.rating_type, rs.begin_month, rs.begin_day) == (RS, 9, 16)
    assert parse_label("январь 1 часть 2026") is not None
    rko = parse_label("05.05 — 11.05")
    assert rko is not None and (rko.rating_type, rko.begin_day, rko.end_month) == (RKO, 5, 5)
    assert parse_label("Сентябрь 3") is None
    assert parse_label("Брумбрь 1") is None
    assert parse_label("40.05 — 11.05") is None


def test_год_выводится_справа_налево_через_новый_год() -> None:
    labels = [parse_label(text) for text in ("22.12 — 28.12", "29.12 — 04.01", "05.01 — 11.01")]
    periods = assign_years([label for label in labels if label], today=date(2026, 1, 20))
    assert [(p.begin_on, p.end_on) for p in periods] == [
        (date(2025, 12, 22), date(2025, 12, 28)),
        (date(2025, 12, 29), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 11)),
    ]


def test_последний_период_не_позже_сегодня() -> None:
    label = parse_label("Ноябрь 1")
    assert label is not None
    (period,) = assign_years([label], today=СЕГОДНЯ)
    assert period.begin_on == date(2025, 11, 1)


def test_полумесяц_рС_с_концом_месяца_и_названием() -> None:
    label = parse_label("Сентябрь 2")
    assert label is not None
    (period,) = assign_years([label], today=СЕГОДНЯ)
    assert (period.begin_on, period.end_on) == (date(2026, 9, 16), date(2026, 9, 30))
    assert (period.title_ru, period.title_en) == ("Сентябрь 2 часть 2026", "September part 2 2026")


def test_лист_рС_разобран() -> None:
    parsed = parse_sheet_scores(sheet_rs(), today=СЕГОДНЯ)
    assert parsed.skipped == 1  # Россия
    assert parsed.developers == {"RS": "Dev One", "SI": "Dev One"}
    assert parsed.issues == ()
    by_unit = {(s.unit.name, s.period.begin_on): s.score for s in parsed.scores}
    assert by_unit == {
        ("Testville-1", date(2026, 8, 16)): 90.0,
        ("Testville-1", date(2026, 9, 1)): 88.5,
        ("Testville-1", date(2026, 9, 16)): 97.5,
        ("Testville 2", date(2026, 9, 1)): 71.0,
    }
    assert {s.unit.dodo_id for s in parsed.scores} == {U1, None}


def test_лист_ркО_разобран() -> None:
    parsed = parse_sheet_scores(sheet_rko(), today=date(2026, 1, 20))
    assert [s.period.rating_type for s in parsed.scores] == [RKO] * 4
    assert parsed.issues == ()


def test_испорченный_балл_строкой_журнала() -> None:
    data = sheet_rs().replace(b"88,5", b"abc")
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]
    assert len(parsed.scores) == 3


def test_балл_вне_0_100_строкой_журнала() -> None:
    parsed = parse_sheet_scores(sheet_rs().replace(b"88,5", b"188"), today=СЕГОДНЯ)
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_смесь_рС_и_ркО_в_одном_листе_не_лист() -> None:
    header = [*SHEET_RS_HEADER[:-1], "05.05 — 11.05"]
    assert not is_sheet_header(header)
    with pytest.raises(RatingsFormatError):
        parse_sheet_scores(to_csv(header, [["a", "Serbia", "b", "", "1", "2", "3"]]), today=СЕГОДНЯ)


def test_лист_узнаётся_по_заголовку() -> None:
    assert detect_format(sheet_rs()) == "sheet-scores"


def test_ссылка_листа_чужой_хост_id_не_берётся() -> None:
    data = sheet_rs().replace(
        b"https://dodopizza.info/rating#/" + U1.encode() + b"/2",
        b"https://evil.example/rating#/" + U1.encode() + b"/2",
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert {s.unit.dodo_id for s in parsed.scores if s.unit.name == "Testville-1"} == {None}


def test_два_девелопера_у_страны_не_теряются_молча() -> None:
    data = sheet_rs().replace(b"\r\n,Slovenia,", b"\r\nDev Two,Serbia,")
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert parsed.developers == {"RS": "Dev One"}
    assert [(i.reason, i.detail["ignored"]) for i in parsed.issues] == [
        (ISSUE_DEVELOPER_CONFLICT, "Dev Two")
    ]


def test_конфликт_девелопера_одно_замечание_на_страну() -> None:
    rows = [
        ["Dev One", "Serbia", "Testville-1", "", "1", "", ""],
        ["Dev Two", "Serbia", "Testville-2", "", "2", "", ""],
        ["Dev Three", "Serbia", "Testville-3", "", "3", "", ""],
    ]
    parsed = parse_sheet_scores(to_csv(SHEET_RS_HEADER, rows), today=СЕГОДНЯ)
    assert [(i.reason, i.row_no) for i in parsed.issues] == [(ISSUE_DEVELOPER_CONFLICT, 3)]


def _лист(rows: list[list[str]]) -> bytes:
    """Лист РС: служебная строка, подписи периодов, затем строки пиццерий."""
    return sheet_csv(
        [
            ["Кол-во пиццерий", "", "", "", "", "", ""],
            ["Рейтинг/Показатель", "", "", "", "", "Сентябрь 1", "Сентябрь 2"],
            *rows,
        ]
    )


def test_заголовок_ниже_служебных_строк_находится() -> None:
    assert detect_format(sheet_rko()) == "sheet-scores"
    parsed = parse_sheet_scores(sheet_rs(), today=СЕГОДНЯ)
    assert {s.period.begin_on for s in parsed.scores} == {
        date(2026, 8, 16),
        date(2026, 9, 1),
        date(2026, 9, 16),
    }


def test_подписи_периодов_дальше_окна_не_лист() -> None:
    rows = [["служебная", "", "", "", "", "", ""]] * HEADER_WINDOW
    data = sheet_csv([*rows, ["", "", "", "", "", "Сентябрь 1", "Сентябрь 2"]])
    with pytest.raises(RatingsFormatError) as err:
        parse_sheet_scores(data, today=СЕГОДНЯ)
    assert err.value.code == ERR_NOT_SHEET


def test_дубль_колонки_пиццерия_не_балл() -> None:
    data = _лист([["Dev One", "Serbia", "Testville-1", "", "Testville-1", "90", "91"]])
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert parsed.issues == ()
    assert [s.score for s in parsed.scores] == [90.0, 91.0]


def test_числа_под_неподписанной_колонкой_в_журнал() -> None:
    data = sheet_csv(
        [
            ["Девелопер", "Страна", "Пиццерия", "", "Сентябрь 3", "Сентябрь 1", "Сентябрь 2"],
            ["Dev One", "Serbia", "Testville-1", "", "77", "90", "91"],
        ]
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert [(i.reason, i.row_no) for i in parsed.issues] == [(ISSUE_BAD_ROW, 1)]
    assert "Сентябрь 3" in parsed.issues[0].detail["reason"]
    assert [s.score for s in parsed.scores] == [90.0, 91.0]


def test_девелопер_и_страна_протягиваются_вниз_по_блоку() -> None:
    data = _лист(
        [
            ["Dev One", "Serbia", "Testville-1", "", "Testville-1", "90", ""],
            ["", "", "Testville-2", "", "Testville-2", "80", ""],
            ["", "Slovenia", "Testville-3", "", "Testville-3", "70", ""],
            ["Dev Two", "Croatia", "Testville-4", "", "Testville-4", "60", ""],
            ["", "", "Testville-5", "", "Testville-5", "50", ""],
        ]
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert parsed.issues == ()
    assert [(s.unit.name, s.unit.country) for s in parsed.scores] == [
        ("Testville-1", "RS"),
        ("Testville-2", "RS"),
        ("Testville-3", "SI"),
        ("Testville-4", "HR"),
        ("Testville-5", "HR"),
    ]
    assert parsed.developers == {"RS": "Dev One", "SI": "Dev One", "HR": "Dev Two"}


def test_страна_с_флагом_и_переносами() -> None:
    assert country_code("🇳🇬 Nigeria") == "NG"
    assert country_code("🇷🇸 Сербия") == "RS"
    assert country_code("🇹🇷️ Turkey") == "TR"
    assert country_code("\n\nBelarus\n\n") == "BY"
    assert country_code("🇲🇽 Mexico") == "MX"
    assert country_code("🇳🇬 Narnia") is None


def test_прочерк_и_пусто_не_оценка() -> None:
    data = _лист(
        [
            ["Dev One", "Serbia", "Testville-1", "", "Testville-1", "-", "—"],
            ["", "", "Testville-2", "", "Testville-2", "–", ""],
            ["", "", "Testville-3", "", "Testville-3", "88,5", "97%"],
        ]
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert parsed.issues == ()
    assert [(s.unit.name, s.score) for s in parsed.scores] == [
        ("Testville-3", 88.5),
        ("Testville-3", 97.0),
    ]


def test_неизвестная_страна_блока_на_каждой_строке() -> None:
    data = _лист(
        [
            ["Dev One", "🇳🇦 Narnia", "Testville-1", "", "Testville-1", "90", ""],
            ["", "", "Testville-2", "", "Testville-2", "80", ""],
        ]
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert [(i.reason, i.detail["unit"]) for i in parsed.issues] == [
        (ISSUE_COUNTRY_UNKNOWN, "Testville-1"),
        (ISSUE_COUNTRY_UNKNOWN, "Testville-2"),
    ]


def test_две_колонки_с_одним_началом_недели_не_склеиваются() -> None:
    data = sheet_csv(
        [
            ["Неделя рейтинга", "", "", "", "", "03.08 — 09.08", "10.08 — 16.08", "10.08 — 23.08"],
            ["Dev One", "Serbia", "Testville-1", "", "Testville-1", "91", "92", "93"],
        ]
    )
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert [(s.period.begin_on, s.period.end_on, s.score) for s in parsed.scores] == [
        (date(2026, 8, 3), date(2026, 8, 9), 91.0),
        (date(2026, 8, 10), date(2026, 8, 16), 92.0),
    ]
    assert [(i.reason, i.row_no) for i in parsed.issues] == [(ISSUE_BAD_ROW, 1)]
    assert "10.08 — 23.08" in parsed.issues[0].detail["reason"]
