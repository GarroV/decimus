"""Листы общей таблицы контроля «база рейтингов» (ядро рейтингов, D464).

Заголовки живые, данные выдуманы (вымышленные `Testville-N`). Что держим: формат
узнаётся по заголовку; период читается из подписи листа, а не из колонки «Месяц»;
год выводится от даты строки или «сегодня»; повтор периода с разными значениями не
пишется; плохая строка уходит в журнал, а не роняет файл.
"""

from __future__ import annotations

from datetime import date

import pytest
from ratings_samples import U1, to_csv

from src.ratings import base
from src.ratings.formats import detect_format
from src.ratings.model import (
    FORMAT_BASE_COLLECTION,
    FORMAT_BASE_RKO_VIOLATIONS,
    FORMAT_BASE_RS_VIOLATIONS,
    FORMAT_BASE_SCORES,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    RKO,
    RS,
    RatingsFormatError,
)

СЕГОДНЯ = date(2026, 10, 13)
ДРУГОЙ = "bb000000000000000000000000000002"

SCORES_HEADER = [
    "Месяц",
    "Период",
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Тип проверки",
    "Балл",
    "Нарушение Д3",
    "Название Д3",
    "Критическое нарушение",
    "Название Критичного",
    "Обнуление",
    "Название Обнуления",
    "Cluster",
]


def _score_row(
    period: str = "05.01 — 11.01",
    kind: str = "РКО",
    score: str = "92,5",
    *,
    unit: str = "Testville-1",
    country: str = "Serbia",
    month: str = "Январь",
    flags: tuple[str, str, str, str, str, str] = ("Нет", "", "Нет", "", "Нет", ""),
) -> list[str]:
    d3, d3n, cr, crn, zr, zrn = flags
    return [month, period, "Dev One", country, unit, kind, score, d3, d3n, cr, crn, zr, zrn, "CEE"]


def scores(*rows: list[str]) -> bytes:
    return to_csv(SCORES_HEADER, list(rows))


COLLECTION_HEADER = [
    "Период",
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Отчеты_Ресторан",
    "Отчеты_Доставка",
    "Cluster",
]
RKO_VIOLATIONS_HEADER = [
    "Месяц",
    "Период",
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Номер заказа",
    "Тип проверки",
    "Нарушение",
    "Дата",
]
RS_VIOLATIONS_HEADER = [
    "Месяц",
    "Период",
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Тип проверки",
    "Нарушение",
    "Нарушение (EN)",
    "Дата",
]
JAN_6 = "Tue Jan 06 2026 08:38:00 GMT+0300 (Moscow Standard Time)"
SEP_8 = "Tue Sep 08 2026 12:35:00 GMT+0300 (Moscow Standard Time)"


def test_формат_узнаётся_по_заголовку() -> None:
    assert detect_format(scores(_score_row())) == FORMAT_BASE_SCORES
    coll = to_csv(
        COLLECTION_HEADER, [["05.01 — 11.01", "Dev", "Serbia", "Testville-1", "1", "2", ""]]
    )
    assert detect_format(coll) == FORMAT_BASE_COLLECTION
    rko = to_csv(
        RKO_VIOLATIONS_HEADER,
        [
            [
                "Сентябрь",
                "07.09 — 13.09",
                "Dev",
                "Serbia",
                "Testville-1",
                "20",
                "РКО",
                "Горелый борт",
                SEP_8,
            ]
        ],
    )
    assert detect_format(rko) == FORMAT_BASE_RKO_VIOLATIONS
    rs = to_csv(
        RS_VIOLATIONS_HEADER,
        [
            [
                "Сентябрь",
                "Сентябрь 1",
                "Dev",
                "Serbia",
                "Testville-1",
                "РС",
                "Грязно",
                "Dirty",
                SEP_8,
            ]
        ],
    )
    assert detect_format(rs) == FORMAT_BASE_RS_VIOLATIONS


def test_лист_без_нужной_колонки_не_узнаётся() -> None:
    header = [c for c in SCORES_HEADER if c != "Критическое нарушение"]
    with pytest.raises(RatingsFormatError):
        detect_format(to_csv(header, []))


def test_период_рс_и_ркО_из_подписи() -> None:
    rs = base.period_for("Сентябрь 2", rating_type=RS, today=СЕГОДНЯ)
    assert (rs.begin_on, rs.end_on) == (date(2026, 9, 16), date(2026, 9, 30))
    rko = base.period_for("26.01 — 01.02", rating_type=RKO, today=СЕГОДНЯ)
    assert (rko.begin_on, rko.end_on) == (date(2026, 1, 26), date(2026, 2, 1))


def test_период_через_новый_год() -> None:
    p = base.period_for("29.12 — 04.01", rating_type=RKO, today=date(2027, 1, 12))
    assert (p.begin_on, p.end_on) == (date(2026, 12, 29), date(2027, 1, 4))


def test_год_берётся_от_сегодня_а_не_вперёд() -> None:
    # 20 октября ещё не наступило — такая неделя может быть только прошлогодней
    p = base.period_for("19.10 — 25.10", rating_type=RKO, today=СЕГОДНЯ)
    assert p.begin_on == date(2025, 10, 19)


def test_год_строки_главнее_вывода_от_сегодня() -> None:
    p = base.period_for(
        "05.01 — 11.01", rating_type=RKO, today=date(2027, 2, 1), seen=date(2026, 1, 6)
    )
    assert p.begin_on == date(2026, 1, 5)


@pytest.mark.parametrize(
    ("text", "kind"),
    [("Сентябрь 1", RKO), ("05.01 — 11.01", RS), ("Сентябрь 3", RS), ("мусор", RKO)],
)
def test_подпись_не_того_типа_или_неузнанная_отказ(text: str, kind: str) -> None:
    with pytest.raises(base._BadRow):
        base.period_for(text, rating_type=kind, today=СЕГОДНЯ)


def test_дата_строки_из_таблицы() -> None:
    assert base.row_date(JAN_6) == date(2026, 1, 6)
    assert base.row_date("не дата") is None
    assert base.row_date("Tue Foo 08 2026 08:38:00 GMT+0300") is None


def test_оценка_с_флагами_и_названиями() -> None:
    row = _score_row(
        "Сентябрь 1",
        "РС",
        "88,25",
        month="Сентябрь",
        flags=("Да", "D3: Продукт просрочен", "Да", "Грязно", "Нет", ""),
    )
    parsed = base.parse_base_scores(scores(row), today=СЕГОДНЯ)
    (s,) = parsed.scores
    assert (s.score, s.period.rating_type, s.period.begin_on) == (88.25, RS, date(2026, 9, 1))
    assert s.flags is not None
    assert (s.flags.d3, s.flags.d3_name) == (True, "D3: Продукт просрочен")
    assert (s.flags.critical, s.flags.critical_name) == (True, "Грязно")
    assert (s.flags.zeroing, s.flags.zeroing_name) == (False, None)
    assert not parsed.issues


def test_оценка_без_флагов_несёт_нет() -> None:
    (s,) = base.parse_base_scores(scores(_score_row()), today=СЕГОДНЯ).scores
    assert s.flags is not None and not (s.flags.d3 or s.flags.critical or s.flags.zeroing)


def test_колонка_месяц_не_читается_периоду_верят() -> None:
    row = _score_row("05.01 — 11.01", month="10.08")
    (s,) = base.parse_base_scores(scores(row), today=СЕГОДНЯ).scores
    assert s.period.begin_on == date(2026, 1, 5)


def test_имя_девелопера_не_сохраняется() -> None:
    parsed = base.parse_base_scores(scores(_score_row()), today=СЕГОДНЯ)
    assert not parsed.developers


def test_плохая_строка_в_журнал_файл_продолжается() -> None:
    parsed = base.parse_base_scores(
        scores(
            _score_row("05.01 — 11.01", "РКО", "90"),
            _score_row("мусор", "РКО", "90", unit="Testville-2"),
            _score_row("12.01 — 18.01", "РКО", "сто", unit="Testville-3"),
            _score_row(
                "12.01 — 18.01",
                "РКО",
                "90",
                unit="Testville-4",
                flags=("Возможно", "", "Нет", "", "Нет", ""),
            ),
            _score_row("12.01 — 18.01", "РКО", "91", unit="Testville-5"),
        ),
        today=СЕГОДНЯ,
    )
    assert [s.unit.name for s in parsed.scores] == ["Testville-1", "Testville-5"]
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW] * 3


def test_пустая_оценка_не_ошибка_и_не_ноль() -> None:
    parsed = base.parse_base_scores(scores(_score_row(score="")), today=СЕГОДНЯ)
    assert not parsed.scores and not parsed.issues and parsed.skipped == 1


def test_страны_вне_imf_отброшены_неизвестная_в_журнал() -> None:
    parsed = base.parse_base_scores(
        scores(_score_row(country="Kazakhstan"), _score_row(country="Атлантида")), today=СЕГОДНЯ
    )
    assert not parsed.scores and parsed.skipped == 1
    assert [i.reason for i in parsed.issues] == [ISSUE_COUNTRY_UNKNOWN]


def test_повтор_периода_с_одним_значением_одна_строка() -> None:
    parsed = base.parse_base_scores(scores(_score_row(), _score_row()), today=СЕГОДНЯ)
    assert len(parsed.scores) == 1 and not parsed.issues


def test_повтор_периода_с_разными_значениями_не_пишется() -> None:
    parsed = base.parse_base_scores(
        scores(_score_row(score="80"), _score_row(score="90")), today=СЕГОДНЯ
    )
    assert not parsed.scores
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_собираемость_числа_и_плохая_ячейка() -> None:
    data = to_csv(
        COLLECTION_HEADER,
        [
            ["05.01 — 11.01", "Dev", "Serbia", "Testville-1", "0", "3", ""],
            ["12.01 — 18.01", "Dev", "Serbia", "Testville-1", "много", "3", ""],
            ["12.01 — 18.01", "Dev", "Serbia", "Testville-2", "", "3", ""],
        ],
    )
    parsed = base.parse_base_collection(data, today=СЕГОДНЯ)
    (c,) = parsed.collections
    assert (c.restaurant, c.delivery, c.period.rating_type) == (0, 3, RKO)
    assert len(parsed.issues) == 2


def test_нарушения_ркО_год_от_даты_строки() -> None:
    data = to_csv(
        RKO_VIOLATIONS_HEADER,
        [
            [
                "Январь",
                "05.01 — 11.01",
                "Dev",
                "Serbia",
                "Testville-1",
                "20",
                "РКО",
                "Горелый борт",
                JAN_6,
            ]
        ],
    )
    parsed = base.parse_base_rko_violations(data, today=date(2027, 2, 1))
    (r,) = parsed.sheet_remarks
    assert r.period.begin_on == date(2026, 1, 5) and r.period.rating_type == RKO
    assert r.violation.text == "Горелый борт" and r.violation.category == "remark"


def test_нарушения_рс_пустое_нарушение_пропущено() -> None:
    data = to_csv(
        RS_VIOLATIONS_HEADER,
        [
            [
                "Сентябрь",
                "Сентябрь 1",
                "Dev",
                "Serbia",
                "Testville-1",
                "РС",
                "Грязно",
                "Dirty",
                SEP_8,
            ],
            ["Сентябрь", "Сентябрь 1", "Dev", "Serbia", "Testville-1", "РС", "", "", SEP_8],
        ],
    )
    parsed = base.parse_base_rs_violations(data, today=СЕГОДНЯ)
    assert [r.violation.text for r in parsed.sheet_remarks] == ["Грязно"]
    assert parsed.sheet_remarks[0].period.rating_type == RS and parsed.skipped == 1


def test_флаги_повтор_названий_схлопывается_порядок_первого_вхождения() -> None:
    """«Название Д3 / Критичного» — тексты через «, », часто с повтором."""
    flags = (
        "Да",
        "Температура на линии, Температура на линии",
        "Да",
        "Белое дно, Пиццу привезли холодной,  Белое дно",
        "Нет",
        "",
    )
    parsed = base.parse_base_scores(scores(_score_row(flags=flags)), today=СЕГОДНЯ)
    (s,) = parsed.scores
    assert s.flags is not None
    assert s.flags.d3_name == "Температура на линии"
    assert s.flags.critical_name == "Белое дно, Пиццу привезли холодной"
    assert s.flags.zeroing_name is None


def test_неделя_через_новый_год_с_датой_строки_после_конца_недели() -> None:
    """Дата листа — время оценки, на день позже конца недели: год всё равно у недели."""
    после = base.period_for(
        "28.12 — 03.01", rating_type=RKO, today=date(2027, 1, 12), seen=date(2027, 1, 4)
    )
    assert (после.begin_on, после.end_on) == (date(2026, 12, 28), date(2027, 1, 3))
    внутри = base.period_for(
        "28.12 — 03.01", rating_type=RKO, today=date(2027, 1, 12), seen=date(2027, 1, 2)
    )
    assert внутри.begin_on == date(2026, 12, 28)
    начало = base.period_for(
        "28.12 — 03.01", rating_type=RKO, today=date(2027, 1, 12), seen=date(2026, 12, 29)
    )
    assert начало.begin_on == date(2026, 12, 28)


def test_дата_строки_на_день_позже_конца_обычной_недели_период_тот_же() -> None:
    p = base.period_for("07.09 — 13.09", rating_type=RKO, today=СЕГОДНЯ, seen=date(2026, 9, 14))
    assert (p.begin_on, p.end_on) == (date(2026, 9, 7), date(2026, 9, 13))


def test_рс_декабрь_2_с_датой_в_январе_остаётся_декабрём() -> None:
    p = base.period_for("Декабрь 2", rating_type=RS, today=date(2027, 1, 12), seen=date(2027, 1, 2))
    assert (p.begin_on, p.end_on) == (date(2026, 12, 16), date(2026, 12, 31))


def test_справочник_id_в_одной_форме_двусмысленное_имя_помечено() -> None:
    upper = U1.upper()
    other = "bb000000000000000000000000000002"
    data = to_csv(
        ["Пиццерия", "Ссылка для РКО", "Ссылка для РС"],
        [
            ["Testville-1", f"https://dodopizza.info/rating#/{upper}/1?", ""],
            [
                "Testville-2",
                f"https://dodopizza.info/rating#/{U1}/1?",
                f"https://dodopizza.info/rating#/{other}/2?",
            ],
            ["Testville-3", "", ""],
        ],
    )
    # Testville-2: в ссылках РКО и РС разные id — имя помечено, а не угадано
    assert base.parse_directory(data) == {"testville-1": U1, "testville-2": base.AMBIGUOUS}


def test_справочник_турецкое_написание_сходится_с_латиницей() -> None:
    """D467: в справочнике «İzmir-4», в листе оценок «Izmir-4» — одна пиццерия."""
    data = to_csv(
        ["Пиццерия", "Ссылка для РКО", "Ссылка для РС"],
        [["İzmir-4", f"https://dodopizza.info/rating#/{U1}/1?", ""]],
    )
    assert base.parse_directory(data) == {"izmir-4": U1}


def test_справочник_id_двух_имён_не_достаётся_ни_одному() -> None:
    """Настоящий случай: у «Новополоцк-1» обе ссылки несут id «Полоцк-1»."""
    data = to_csv(
        ["Пиццерия", "Ссылка для РКО", "Ссылка для РС"],
        [
            ["Testville-1", f"https://dodopizza.info/rating#/{U1}/1?", ""],
            ["Testville-2", f"https://dodopizza.info/rating#/{U1}/1?", ""],
            ["Testville-3", f"https://dodopizza.info/rating#/{ДРУГОЙ}/1?", ""],
        ],
    )
    assert base.parse_directory(data) == {
        "testville-1": base.AMBIGUOUS,
        "testville-2": base.AMBIGUOUS,
        "testville-3": ДРУГОЙ,
    }
