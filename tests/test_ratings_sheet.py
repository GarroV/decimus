"""Лист «Качество по пиццериям» таблиц контроля (ядро рейтингов, D324).

Строка — девелопер, страна, пиццерия, ссылка на рейтинг, затем колонки-периоды:
РС — полумесяцы «Сентябрь 2», РКО — недели «05.05 — 11.05». Года в подписи нет —
его выводит `assign_years`.
"""

from __future__ import annotations

from datetime import date

import pytest
from ratings_samples import SHEET_RS_HEADER, U1, sheet_rko, sheet_rs, to_csv

from src.ratings.formats import detect_format
from src.ratings.model import ISSUE_BAD_ROW, ISSUE_DEVELOPER_CONFLICT, RKO, RS, RatingsFormatError
from src.ratings.sheet import assign_years, is_sheet_header, parse_label, parse_sheet_scores

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
    assert [s.period.rating_type for s in parsed.scores] == [RKO, RKO, RKO]


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
    data = sheet_rs().replace("Dev One,Slovenia".encode(), "Dev Two,Serbia".encode())
    parsed = parse_sheet_scores(data, today=СЕГОДНЯ)
    assert parsed.developers == {"RS": "Dev One"}
    assert [(i.reason, i.detail["ignored"]) for i in parsed.issues] == [
        (ISSUE_DEVELOPER_CONFLICT, "Dev Two")
    ]
