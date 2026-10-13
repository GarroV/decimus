"""Листы «базы рейтингов» через настоящую базу (ядро: идемпотентность, флаги, ключи, D464).

Повтор того же смысла другими байтами ничего не меняет; изменённая ячейка
обновляет строку; флаги Д3, критичное и обнуление ложатся рядом с баллом;
нарушения листа заменяют только свой набор, замечания снимка не трогаются;
пиццерия без id находится по имени среди известных или по справочнику ссылок.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import requires_db
from ratings_samples import U1, snapshot, to_csv
from test_ratings_base import (
    COLLECTION_HEADER,
    RKO_VIOLATIONS_HEADER,
    RS_VIOLATIONS_HEADER,
    SEP_8,
    _score_row,
    scores,
)

psycopg = pytest.importorskip("psycopg")

from src.ratings.base import AMBIGUOUS  # noqa: E402
from src.ratings.importer import CHANNEL_SYNC, ImportReport, import_file  # noqa: E402

pytestmark = requires_db

СЕГОДНЯ = date(2026, 10, 13)
ТЕСТ = "bb000000000000000000000000000002"


def _грузить(data: bytes, **kw: object) -> ImportReport:
    return import_file(
        data,
        kind=None,
        channel=CHANNEL_SYNC,
        actor="sheet-sync",
        file_name="sheet:test",
        today=СЕГОДНЯ,
        **kw,  # type: ignore[arg-type]
    )


def _строки(db_env: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(db_env) as conn:
        return [tuple(r) for r in conn.execute(sql, params).fetchall()]


def _считать(r: ImportReport) -> tuple[int, int, int, int]:
    return r.accepted, r.updated, r.skipped, r.unmatched


def _известная_пиццерия(db_env: str) -> None:
    """Testville-1 в Сербии уже есть (как после `sheet-scores`): имя сопоставляется."""
    _грузить(snapshot())


_ОЦЕНКИ = (
    _score_row("05.01 — 11.01", "РКО", "92,5"),
    _score_row(
        "Сентябрь 1",
        "РС",
        "88",
        month="Сентябрь",
        flags=("Да", "D3: Продукт просрочен", "Нет", "", "Нет", ""),
    ),
)


def test_оценки_с_флагами_ложатся_и_повтор_ничего_не_меняет(db_env: str) -> None:
    _известная_пиццерия(db_env)
    первая = _грузить(scores(*_ОЦЕНКИ))
    assert (первая.format, первая.outcome, _считать(первая)) == (
        "base-scores",
        "loaded",
        (2, 0, 0, 0),
    )
    флаги = _строки(
        db_env,
        "select p.rating_type, s.score::float, s.d3, s.d3_name, s.critical, s.zeroing, s.source "
        "from ratings.scores s join ratings.periods p on p.id = s.period_id "
        "where p.begin_on in ('2026-01-05', '2026-09-01') and s.unit_dodo_id = %s "
        "order by p.begin_on",
        (U1,),
    )
    assert флаги == [
        ("rko", 92.5, False, None, False, False, "sheet"),
        ("rs", 88.0, True, "D3: Продукт просрочен", False, False, "sheet"),
    ]
    # тот же смысл другими байтами: порядок строк иной, значит sha256 другой
    повтор = _грузить(scores(*reversed(_ОЦЕНКИ)))
    assert (повтор.outcome, _считать(повтор)) == ("loaded", (0, 0, 2, 0))


def test_изменённая_ячейка_обновляет_строку_и_флаги(db_env: str) -> None:
    _известная_пиццерия(db_env)
    _грузить(scores(*_ОЦЕНКИ))
    новая = _score_row(
        "Сентябрь 1",
        "РС",
        "88",
        month="Сентябрь",
        flags=("Да", "D3: Продукт просрочен", "Да", "Грязно", "Нет", ""),
    )
    итог = _грузить(scores(_ОЦЕНКИ[0], новая))
    assert _считать(итог) == (0, 1, 1, 0)
    assert _строки(
        db_env,
        "select critical, critical_name from ratings.scores where unit_dodo_id = %s "
        "and period_id = (select id from ratings.periods where begin_on = '2026-09-01')",
        (U1,),
    ) == [(True, "Грязно")]


def test_пиццерия_не_из_листа_не_удаляется(db_env: str) -> None:
    _известная_пиццерия(db_env)
    _грузить(snapshot())  # балл снимка за 16.09
    _грузить(scores(_score_row("05.01 — 11.01", "РКО", "70", unit="Testville-9")))
    assert _строки(
        db_env, "select count(*) from ratings.scores where unit_dodo_id = %s", (U1,)
    ) == [(2,)]


def test_пиццерия_без_id_по_справочнику_и_несопоставленная_в_журнал(db_env: str) -> None:
    # в базе пусто: Testville-1 известна только справочнику ссылок
    итог = _грузить(
        scores(
            _score_row(unit="Testville-1"),
            _score_row(unit="Testville-7", country="Poland"),
        ),
        directory={"testville-1": ТЕСТ},
    )
    assert (итог.accepted, итог.unmatched) == (1, 1)
    assert _строки(db_env, "select dodo_id, country_code from ratings.units") == [(ТЕСТ, "RS")]
    причины = _строки(
        db_env,
        "select reason, detail->>'unit' from ratings.import_issues where import_id = %s",
        (итог.import_id,),
    )
    assert причины == [("unit_unmatched", "Testville-7")]


def test_собираемость_ложится_и_повтор_kept(db_env: str) -> None:
    _известная_пиццерия(db_env)
    data = to_csv(
        COLLECTION_HEADER,
        [["05.01 — 11.01", "Dev", "Serbia", "Testville-1", "1", "4", ""]],
    )
    первая = _грузить(data)
    assert (первая.format, _считать(первая)) == ("base-collection", (1, 0, 0, 0))
    правка = to_csv(
        COLLECTION_HEADER,
        [["05.01 — 11.01", "Dev", "Serbia", "Testville-1", "2", "4", ""]],
    )
    assert _считать(_грузить(правка)) == (0, 1, 0, 0)
    assert _строки(
        db_env, "select restaurant_reports, delivery_reports from ratings.collection"
    ) == [(2, 4)]


def _нарушения_рс(*тексты: str) -> bytes:
    return to_csv(
        RS_VIOLATIONS_HEADER,
        [
            ["Сентябрь", "Сентябрь 2", "Dev", "Serbia", "Testville-1", "РС", t, "en", SEP_8]
            for t in тексты
        ],
    )


def test_нарушения_рс_набором_замечания_снимка_целы(db_env: str) -> None:
    _известная_пиццерия(db_env)  # снимок: два замечания за «Сентябрь 2»
    до = _строки(db_env, "select count(*) from ratings.violations where category = 'remark'")
    первая = _грузить(_нарушения_рс("Грязно", "Грязно", "Тухлый сыр"))
    assert (первая.format, _считать(первая)) == ("base-rs-violations", (1, 0, 0, 0))
    лист = _строки(
        db_env,
        "select text, amount, rating_type from ratings.violations "
        "where starts_with(row_key, 'sheet:') order by text",
    )
    assert лист == [("Грязно", 2, "rs"), ("Тухлый сыр", 1, "rs")]
    assert _строки(db_env, "select count(*) from ratings.violations where category = 'remark'") == [
        (до[0][0] + 2,)
    ]
    # набор пиццерии и периода заменяется целиком
    вторая = _грузить(_нарушения_рс("Тухлый сыр"))
    assert _считать(вторая) == (0, 1, 0, 0)
    assert _строки(
        db_env, "select text from ratings.violations where starts_with(row_key, 'sheet:')"
    ) == [("Тухлый сыр",)]
    assert _строки(db_env, "select count(*) from ratings.violations where category = 'remark'") == [
        (до[0][0] + 1,)
    ]
    # тот же набор другими байтами — без изменений
    повтор = _грузить(_нарушения_рс("Тухлый сыр") + b"\r\n")
    assert _считать(повтор) == (0, 0, 1, 0)


def test_нарушения_ркО_лежат_замечаниями_периода_не_проверками(db_env: str) -> None:
    _известная_пиццерия(db_env)
    data = to_csv(
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
    итог = _грузить(data)
    assert (итог.format, _считать(итог)) == ("base-rko-violations", (1, 0, 0, 0))
    assert _строки(db_env, "select count(*) from ratings.checkups where rating_type = 'rko'") == [
        (0,)
    ]
    assert _строки(
        db_env,
        "select v.rating_type, v.category, p.begin_on from ratings.violations v "
        "join ratings.periods p on p.id = v.period_id where starts_with(v.row_key, 'sheet:')",
    ) == [("rko", "remark", date(2026, 9, 7))]


def test_справочник_с_занятым_id_не_переименовывает_пиццерию_и_пишет_в_журнал(
    db_env: str,
) -> None:
    _известная_пиццерия(db_env)
    итог = _грузить(
        scores(_score_row("05.01 — 11.01", "РКО", "70", unit="Testville-9")),
        directory={"testville-9": U1},  # id у справочника чужой: он у Testville-1
    )
    assert (итог.accepted, итог.unmatched) == (0, 0)
    assert _строки(db_env, "select dodo_id, name from ratings.units") == [(U1, "Testville-1")]
    причины = {
        r[0]
        for r in _строки(
            db_env,
            "select reason from ratings.import_issues where import_id = %s",
            (итог.import_id,),
        )
    }
    assert причины == {"unit_id_clash"}


def test_наше_название_не_перезаписывается_иным_написанием(db_env: str) -> None:
    """D467: пришло «Izmir-4» с тем же id, у нас «İzmir-4» — остаётся наше."""
    _грузить(snapshot(name="İzmir-4"))
    _грузить(snapshot(name="Izmir-4"))
    assert _строки(db_env, "select dodo_id, name from ratings.units") == [(U1, "İzmir-4")]


def test_справочник_с_разными_id_у_имени_пиццерию_не_заводит_и_пишет_в_журнал(db_env: str) -> None:
    """В ссылках РКО и РС одной строки разные id: ничего не пишется, строка — в журнал."""
    итог = _грузить(
        scores(_score_row("05.01 — 11.01", "РКО", "70", unit="Testville-9")),
        directory={"testville-9": AMBIGUOUS},
    )
    assert (итог.accepted, итог.unmatched) == (0, 0)
    assert _строки(db_env, "select count(*) from ratings.units") == [(0,)]
    assert _строки(db_env, "select count(*) from ratings.scores") == [(0,)]
    assert _строки(
        db_env,
        "select reason, detail->>'unit' from ratings.import_issues where import_id = %s",
        (итог.import_id,),
    ) == [("unit_id_clash", "Testville-9")]


def test_справочник_занятый_id_в_другом_регистре_тоже_занят(db_env: str) -> None:
    _известная_пиццерия(db_env)
    итог = _грузить(
        scores(_score_row("05.01 — 11.01", "РКО", "70", unit="Testville-9")),
        directory={"testville-9": U1.upper()},
    )
    assert (итог.accepted, итог.unmatched) == (0, 0)
    assert _строки(db_env, "select dodo_id, name from ratings.units") == [(U1, "Testville-1")]


_ОКТ_8 = "Mon Oct 05 2026 12:35:00 GMT+0300 (Moscow Standard Time)"


def _лист_сентября() -> list[bytes]:
    return [
        scores(
            _score_row("07.09 — 13.09", "РКО", "90", month="Сентябрь"),
            _score_row("Сентябрь 1", "РС", "88", month="Сентябрь"),
        ),
        to_csv(
            COLLECTION_HEADER, [["07.09 — 13.09", "Dev", "Serbia", "Testville-1", "1", "4", ""]]
        ),
        to_csv(
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
                    "Грязь",
                    SEP_8,
                ],
            ],
        ),
        to_csv(
            RS_VIOLATIONS_HEADER,
            [
                [
                    "Сентябрь",
                    "Сентябрь 1",
                    "Dev",
                    "Serbia",
                    "Testville-1",
                    "РС",
                    "Тухлый сыр",
                    "",
                    SEP_8,
                ]
            ],
        ),
    ]


def _лист_октября() -> list[bytes]:
    """Таблица перевернулась на октябрь: сентября в листах больше нет."""
    return [
        scores(
            _score_row("05.10 — 11.10", "РКО", "80", month="Октябрь"),
            _score_row("Октябрь 1", "РС", "70", month="Октябрь"),
        ),
        to_csv(
            COLLECTION_HEADER, [["05.10 — 11.10", "Dev", "Serbia", "Testville-1", "2", "3", ""]]
        ),
        to_csv(
            RKO_VIOLATIONS_HEADER,
            [
                [
                    "Октябрь",
                    "05.10 — 11.10",
                    "Dev",
                    "Serbia",
                    "Testville-1",
                    "9",
                    "РКО",
                    "Дым",
                    _ОКТ_8,
                ]
            ],
        ),
        to_csv(
            RS_VIOLATIONS_HEADER,
            [["Октябрь", "Октябрь 1", "Dev", "Serbia", "Testville-1", "РС", "Мухи", "", _ОКТ_8]],
        ),
    ]


def _всё_до_октября(db_env: str) -> dict[str, list[tuple[object, ...]]]:
    return {
        "оценки": _строки(
            db_env,
            "select p.begin_on, s.score::float, s.d3 from ratings.scores s "
            "join ratings.periods p on p.id = s.period_id "
            "where p.begin_on < '2026-10-01' order by 1, 2",
        ),
        "собираемость": _строки(
            db_env,
            "select p.begin_on, c.restaurant_reports, c.delivery_reports "
            "from ratings.collection c "
            "join ratings.periods p on p.id = c.period_id "
            "where p.begin_on < '2026-10-01' order by 1",
        ),
        "нарушения": _строки(
            db_env,
            "select p.begin_on, v.rating_type, v.text, v.amount from ratings.violations v "
            "join ratings.periods p on p.id = v.period_id "
            "where p.begin_on < '2026-10-01' order by 1, 2, 3",
        ),
    }


def test_таблица_без_прошлого_месяца_не_стирает_загруженное_раньше(db_env: str) -> None:
    """Листы нарушений держат только текущий месяц: прошлый остаётся у нас целиком."""
    _известная_пиццерия(db_env)
    for data in _лист_сентября():
        _грузить(data)
    сентябрь = _всё_до_октября(db_env)
    assert all(сентябрь.values()), "сентябрь не лёг — проверка ничего не проверяла бы"
    for data in _лист_октября():
        _грузить(data)
    assert _всё_до_октября(db_env) == сентябрь
    # октябрь лёг рядом, а не вместо
    assert _строки(
        db_env,
        "select count(*) from ratings.violations v join ratings.periods p on p.id = v.period_id "
        "where p.begin_on >= '2026-10-01' and starts_with(v.row_key, 'sheet:')",
    ) == [(2,)]
    assert _строки(
        db_env,
        "select count(*) from ratings.collection c join ratings.periods p on p.id = c.period_id "
        "where p.begin_on >= '2026-10-01'",
    ) == [(1,)]
