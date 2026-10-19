"""Сводка через настоящую базу: загрузили синтетику — сводка показала её цифры.

Расчёты проверены в `test_ratings_summary.py`; здесь — что чтение отдаёт
расчётам ровно нужный срез: страны группы, периоды внутри, отклонённые
проверки вне счёта, замечания только периодов РС, окно риска старыми первыми.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import requires_db
from ratings_samples import (
    P_RKO,
    P_RS,
    P_RS_PREV,
    U1,
    rko_evaluations,
    rko_violations,
    sheet_rs,
    snapshot,
    to_csv,
)

psycopg = pytest.importorskip("psycopg")
from test_ratings_base import COLLECTION_HEADER  # noqa: E402

from src.db import ratings_read  # noqa: E402
from src.db.errors import RatingsError  # noqa: E402
from src.ratings import report  # noqa: E402
from src.ratings.importer import CHANNEL_WEB, import_file  # noqa: E402
from src.ratings.periods import KIND_QUARTER, quarter_period  # noqa: E402

pytestmark = requires_db

СЕГОДНЯ = date(2026, 10, 8)


def _грузить(data: bytes) -> None:
    import_file(data, kind=None, channel=CHANNEL_WEB, actor="ctl", file_name=None, today=СЕГОДНЯ)


def _период(pid: str, begin: str, end: str, rating_type: int = 2) -> dict[str, object]:
    return {"id": pid, "rating_type": rating_type, "begin": begin, "end": end, "alias": begin}


def _снимок_ниже_порога() -> bytes:
    """Два периода РС подряд ниже порога: 60 (старый), потом 50."""
    return snapshot(
        history=[
            {"score": 60, "status": "1", "period": _период(P_RS_PREV, "2026-09-01", "2026-09-15")},
            {"score": 50, "status": "1", "period": _период(P_RS, "2026-09-16", "2026-09-30")},
        ],
        remarks=[],
    )


def test_сводка_по_стране_из_загруженного(db_env: str) -> None:
    for data in (snapshot(), rko_violations(), rko_evaluations()):
        _грузить(data)
    ratings_read.set_developer("RS", "Dev One", actor="ctl")
    sel = report.Selection(report.GROUP_DEVELOPER, "Dev One", quarter_period(2026, 3))
    summary = report.build(sel)
    assert summary.countries == ("RS",)
    (line,) = summary.lines
    assert line.rs == pytest.approx(97.5) and line.rko == pytest.approx(91.0)
    assert summary.rs_cluster.top[0].text == "Грязный пол" and summary.rs_cluster.checkups == 4


def test_отклонённая_проверка_вне_счёта(db_env: str) -> None:
    _грузить(rko_violations())
    _грузить(rko_evaluations().replace("Принято".encode(), "Отклонено".encode(), 1))
    facts, checkups = ratings_read.rko_violation_facts(
        countries=["RS", "BY"], begin=date(2026, 10, 1), end=date(2026, 12, 31)
    )
    assert checkups == {"BY": 1}
    assert {f[2] for f in facts} == {"BY"}


def test_принятая_проверка_в_счёте(db_env: str) -> None:
    """Контроль к отклонённой: тот же срез без отклонения видит обе страны."""
    _грузить(rko_violations())
    _грузить(rko_evaluations())
    facts, checkups = ratings_read.rko_violation_facts(
        countries=["RS", "BY"], begin=date(2026, 10, 1), end=date(2026, 12, 31)
    )
    assert checkups == {"RS": 1, "BY": 1}
    assert {f[2] for f in facts} == {"RS", "BY"}


def _собираемость(*недели: tuple[str, str, str]) -> bytes:
    return to_csv(
        COLLECTION_HEADER,
        [
            [w, "Dev", "Serbia", "Testville-1", ресторан, доставка, ""]
            for w, ресторан, доставка in недели
        ],
    )


def test_знаменатель_ркО_берётся_из_собираемости_где_она_есть(db_env: str) -> None:
    """Лист нарушений РКО несёт только проверки с нарушениями: счёт по ним занижает знаменатель."""
    _грузить(rko_violations())
    _грузить(rko_evaluations())
    _грузить(_собираемость(("05.10 — 11.10", "5", "7"), ("14.09 — 20.09", "100", "100")))
    facts, checkups = ratings_read.rko_violation_facts(
        countries=["RS", "BY"], begin=date(2026, 10, 1), end=date(2026, 12, 31)
    )
    # RS: 5 + 7 отчётов недели 05.10, неделя 14.09 в рамку не задевает; BY без собираемости — счёт
    assert checkups == {"RS": 12, "BY": 1}
    assert {f[2] for f in facts} == {"RS", "BY"}


def test_пустой_квартал_пустые_блоки(db_env: str) -> None:
    """Страна есть, данных за квартал нет: строка страны с пустыми оценками, а не пустой список."""
    _грузить(snapshot())
    summary = report.build(report.Selection(report.GROUP_IMF, None, quarter_period(2020, 1)))
    assert summary.countries == ("RS",)
    assert [(line.country, line.rs, line.rko) for line in summary.lines] == [("RS", None, None)]
    assert (summary.total.rs, summary.total.rko) == (None, None)
    assert summary.rko_cluster.total == 0 and summary.rko_cluster.per_checkup is None
    assert summary.rs_cluster.checkups == 0 and summary.rs_cluster.per_checkup is None
    assert summary.rs_by_country["RS"].checkups == 0


def test_рамка_берёт_каждый_период_который_задевает(db_env: str) -> None:
    """D396: период РС 16–30.09 попадает в любую рамку, задевшую его хоть днём, —
    и начатую после его начала; рамка после его конца его не берёт."""
    _грузить(snapshot())

    def рамка(begin: date, end: date) -> list[tuple[object, ...]]:
        rows = ratings_read.score_facts(countries=["RS"], begin=begin, end=end)
        return [(f[0], f[3], f[5], f[7]) for f in rows]

    рс = (U1, "rs", date(2026, 9, 16), date(2026, 9, 30))
    assert рамка(date(2026, 9, 16), date(2026, 9, 16)) == [рс]
    assert рамка(date(2026, 9, 30), date(2026, 9, 30))[0] == рс
    assert рс in рамка(date(2026, 9, 17), date(2026, 9, 29))
    assert рс not in рамка(date(2026, 9, 1), date(2026, 9, 15))
    assert рс not in рамка(date(2026, 10, 1), date(2026, 10, 31))


def test_оценка_не_размножается_повторной_загрузкой(db_env: str) -> None:
    _грузить(snapshot())
    _грузить(snapshot(name="Testville-1 renamed"))  # другие байты, те же ключи — обновление
    facts = ratings_read.score_facts(
        countries=["RS"], begin=date(2026, 7, 1), end=date(2026, 9, 30)
    )
    assert sorted((f[0], f[4]) for f in facts) == sorted(set((f[0], f[4]) for f in facts))
    assert len(facts) == 2
    by_ids = ratings_read.score_facts(
        countries=["RS"], begin=date(2026, 7, 1), end=date(2026, 9, 30), period_ids=[facts[0][4]]
    )
    assert len(by_ids) == 1


def test_замечания_только_периодов_рс(db_env: str) -> None:
    """Импортёр замечания периода РКО не пишет; строка заведена руками — чтение её не берёт."""
    _грузить(snapshot())
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.violations "
            "(row_key, rating_type, unit_dodo_id, period_id, text, category, amount, import_id) "
            "select 'test:rko-remark', 'rko', %s, p.id, 'Белый борт', 'remark', 1, "
            "(select max(id) from ratings.imports) "
            "from ratings.periods p where p.dodo_id = %s",
            (U1, P_RKO),
        )
    facts, checkups = ratings_read.rs_remark_facts(
        countries=["RS"], begin=date(2026, 7, 1), end=date(2026, 9, 30)
    )
    texts = {f[3] for f in facts}
    assert "Грязный пол" in texts
    assert "Белый борт" not in texts  # замечание периода РКО
    assert checkups == {"RS": 4}


def test_зона_риска_окно_старыми_первыми(db_env: str) -> None:
    _грузить(_снимок_ниже_порога())
    assert ratings_read.last_period_ids("rs", until=date(2026, 9, 30), n=5) == tuple(
        p[0] for p in reversed(ratings_read.rs_periods())
    )
    ratings_read.set_setting("risk_periods", 2, actor="ctl")
    summary = report.build(report.Selection(report.GROUP_IMF, None, quarter_period(2026, 3)))
    (unit,) = summary.risk
    assert (unit.unit, unit.rating_type, unit.scores) == (U1, "rs", (60.0, 50.0))


def test_зона_риска_пуста_если_периодов_меньше_окна(db_env: str) -> None:
    _грузить(_снимок_ниже_порога())  # два периода РС, окно — три (стартовое)
    summary = report.build(report.Selection(report.GROUP_IMF, None, quarter_period(2026, 3)))
    assert summary.risk == ()


def test_группа_мф_без_стран_вне_охвата(db_env: str) -> None:
    _грузить(snapshot())
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.countries (code, name_ru, name_en, is_imf, developer) "
            "values ('RU', 'Россия', 'Russia', false, 'Dev One')"
        )
    ratings_read.set_developer("RS", "Dev One", actor="ctl")
    sel, choices = report.select({}, today=СЕГОДНЯ)
    assert [c.code for c in choices.countries] == ["RS"]
    assert choices.developers == ("Dev One",)
    assert (sel.group, sel.value) == (report.GROUP_IMF, None)
    assert report.build(sel).countries == ("RS",)
    assert report.build(
        report.Selection(report.GROUP_DEVELOPER, "Dev One", sel.period)
    ).countries == ("RS",)


def test_группа_по_девелоперу_и_стране() -> None:
    rows = [
        ratings_read.CountryRow("RS", "Сербия", "Serbia", "Dev One", True),
        ratings_read.CountryRow("BY", "Беларусь", "Belarus", "Dev Two", True),
        ratings_read.CountryRow("SI", "Словения", "Slovenia", None, True),
    ]
    period = quarter_period(2026, 3)
    assert report.group_countries(
        report.Selection(report.GROUP_DEVELOPER, "Dev Two", period), rows
    ) == ("BY",)
    # Девелопер не выбран: страна без девелопера в группу не попадает.
    assert (
        report.group_countries(report.Selection(report.GROUP_DEVELOPER, None, period), rows) == ()
    )
    assert report.group_countries(report.Selection(report.GROUP_COUNTRY, "SI", period), rows) == (
        "SI",
    )
    assert report.group_countries(report.Selection(report.GROUP_IMF, None, period), rows) == (
        "RS",
        "BY",
        "SI",
    )


def test_отбор_по_адресу(db_env: str) -> None:
    _грузить(snapshot())
    ratings_read.set_developer("RS", "Dev One", actor="ctl")
    sel, choices = report.select(
        {"group": "developer", "value": "нет такого", "period": "2026-Q2"}, today=СЕГОДНЯ
    )
    assert (sel.group, sel.value, sel.period.key) == (report.GROUP_DEVELOPER, "Dev One", "2026-Q2")
    (rs,) = choices.rs_periods
    assert (rs.title_ru, rs.title_en) == ("Сентябрь 2 часть 2026", "September part 2 2026")
    (country,) = choices.countries
    assert (country.name_ru, country.name_en) == ("Сербия", "Serbia")
    sel, _ = report.select({"group": "мусор", "period": "мусор"}, today=СЕГОДНЯ)
    assert (sel.group, sel.period.kind) == (report.GROUP_IMF, KIND_QUARTER)
    assert sel.period.begin == date(2026, 7, 1)  # последний период РС в базе — III квартал


def test_журнал_и_проблемы_загрузки(db_env: str) -> None:
    _грузить(snapshot())
    _грузить(snapshot())  # тот же файл — duplicate
    _грузить(sheet_rs())
    rows = ratings_read.imports()
    assert [r.outcome for r in rows] == ["loaded", "duplicate", "loaded"]
    assert rows[1].duplicate_of == rows[2].id
    assert set(ratings_read.last_loaded()) == {"snapshot", "sheet-scores"}
    issues = ratings_read.open_issues()
    assert issues and {i.import_id for i in issues} == {rows[0].id}
    assert all(isinstance(i.detail, dict) for i in issues)


def test_правила_и_пороги_читаются(db_env: str) -> None:
    rules = ratings_read.hard_rules()
    assert ("rko", "text", "Нарушен рецепт") in {r[1:] for r in rules}
    assert ratings_read.settings() == {
        "top_threshold": 85.0,
        "risk_threshold": 85.0,
        "risk_periods": 3.0,
    }


def test_контроль_правит_порог_и_мусор_отказ(db_env: str) -> None:
    ratings_read.set_setting("top_threshold", 80, actor="ctl")
    assert ratings_read.settings()["top_threshold"] == 80
    with pytest.raises(RatingsError) as exc:
        ratings_read.set_setting("risk_periods", 1.5, actor="ctl")
    assert exc.value.code == ratings_read.REFUSED_SETTING  # type: ignore[attr-defined]
    with pytest.raises(RatingsError) as exc:
        ratings_read.set_setting("нет такой", 1, actor="ctl")
    assert exc.value.code == ratings_read.REFUSED_SETTING_UNKNOWN  # type: ignore[attr-defined]


def test_правка_справочников_и_отказы_кодом(db_env: str) -> None:
    _грузить(snapshot())
    assert ratings_read.set_developer("RS", "  Dev One  ", actor="ctl") is True
    assert ratings_read.set_developer("ZZ", "Dev One", actor="ctl") is False
    assert {c.code: c.developer for c in ratings_read.countries()}["RS"] == "Dev One"
    with pytest.raises(RatingsError) as exc:
        ratings_read.set_developer("RS", "x" * 121, actor="ctl")
    assert exc.value.code == ratings_read.REFUSED_DEVELOPER  # type: ignore[attr-defined]

    ratings_read.add_hard_rule("rs", "contains", "  гряз ", actor="ctl")
    (rule,) = [r for r in ratings_read.hard_rules() if r[3] == "гряз"]
    with pytest.raises(RatingsError) as exc:
        ratings_read.add_hard_rule("rs", "contains", "гряз", actor="ctl")
    assert exc.value.code == ratings_read.REFUSED_RULE  # type: ignore[attr-defined]
    assert ratings_read.remove_hard_rule(rule[0]) is True
    assert ratings_read.remove_hard_rule(rule[0]) is False


def test_оценки_за_оба_типа_рядом(db_env: str) -> None:
    """Порядок колонок факта совпадает с `summary.Fact` — оценка РКО не уходит в РС."""
    _грузить(snapshot())
    facts = ratings_read.score_facts(
        countries=["RS"], begin=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    by_type = {f[3]: f[6] for f in facts}
    assert by_type == {"rs": pytest.approx(97.5), "rko": pytest.approx(91.0)}
    assert all(isinstance(f[5], date) for f in facts)


@pytest.mark.parametrize("zone", ["Europe/Belgrade", "America/New_York"])
def test_сутки_ркО_по_utc_а_не_по_поясу_сессии(
    db_env: str, monkeypatch: pytest.MonkeyPatch, zone: str
) -> None:
    """Дата заказа в файле — UTC: 30.09 23:30 — III квартал, 01.10 00:30 — IV, в любом поясе."""
    monkeypatch.setenv("PGTZ", zone)
    q3 = {"countries": ["RS", "BY"], "begin": date(2026, 7, 1), "end": date(2026, 9, 30)}
    q4 = {"countries": ["RS", "BY"], "begin": date(2026, 10, 1), "end": date(2026, 12, 31)}
    with psycopg.connect(db_env) as conn:
        assert conn.execute("show timezone").fetchone()[0] == zone  # пояс сессии применился

    _грузить(rko_violations(**{"Дата заказа": "2026-09-30 23:30:00"}))
    facts, checkups = ratings_read.rko_violation_facts(**q3)  # type: ignore[arg-type]
    assert ({f[2] for f in facts}, checkups) == ({"RS"}, {"RS": 1})
    facts, checkups = ratings_read.rko_violation_facts(**q4)  # type: ignore[arg-type]
    assert ({f[2] for f in facts}, checkups) == ({"BY"}, {"BY": 1})

    _грузить(rko_violations(**{"Дата заказа": "2026-10-01 00:30:00"}))
    facts, checkups = ratings_read.rko_violation_facts(**q3)  # type: ignore[arg-type]
    assert (facts, checkups) == ([], {})
    facts, checkups = ratings_read.rko_violation_facts(**q4)  # type: ignore[arg-type]
    assert ({f[2] for f in facts}, checkups) == ({"RS", "BY"}, {"RS": 1, "BY": 1})


def test_окно_замечаний_рс_включает_оба_края(db_env: str) -> None:
    """Период РС 16–30.09: окно, задевшее его хоть днём, его берёт (D396)."""
    _грузить(snapshot())

    def срез(begin: date, end: date) -> tuple[set[str], dict[str, int]]:
        facts, checkups = ratings_read.rs_remark_facts(countries=["RS"], begin=begin, end=end)
        return {f[3] for f in facts}, checkups

    assert срез(date(2026, 9, 1), date(2026, 9, 16)) == ({"Грязный пол"}, {"RS": 4})
    assert срез(date(2026, 9, 16), date(2026, 9, 30)) == ({"Грязный пол"}, {"RS": 4})
    assert срез(date(2026, 9, 1), date(2026, 9, 15)) == (set(), {})
    assert срез(date(2026, 9, 17), date(2026, 9, 30)) == ({"Грязный пол"}, {"RS": 4})
    assert срез(date(2026, 9, 30), date(2026, 10, 15)) == ({"Грязный пол"}, {"RS": 4})
    assert срез(date(2026, 10, 1), date(2026, 10, 31)) == (set(), {})


def test_правило_неверного_типа_отказ_своим_кодом(db_env: str) -> None:
    for rating_type, match in (("xx", "text"), ("rs", "regex")):
        with pytest.raises(RatingsError) as exc:
            ratings_read.add_hard_rule(rating_type, match, "гряз", actor="ctl")
        assert exc.value.code == ratings_read.REFUSED_RULE_KIND  # type: ignore[attr-defined]


# --- разбивка пиццерии по периодам (#958) --------------------------------------

U_RS = "e1" * 16
U_BY = "e2" * 16


def _вставить(dsn: str) -> None:
    """Две пиццерии (RS, BY), у RS — РС за два периода и РКО за один, проверки и нарушения."""
    with psycopg.connect(dsn) as conn:
        imp = conn.execute(
            "insert into ratings.imports (actor, channel, format, sha256, outcome, accepted) "
            "values ('ctl', 'sync', 'base-scores', %s, 'loaded', 3) returning id",
            ("0" * 64,),
        ).fetchone()[0]
        for code in ("RS", "BY"):
            conn.execute(
                "insert into ratings.countries (code, name_ru, name_en, is_imf) "
                "values (%s, %s, %s, true) on conflict do nothing",
                (code, code, code),
            )
        for dodo, name, country in ((U_RS, "Testville-1", "RS"), (U_BY, "Minsk-1", "BY")):
            conn.execute(
                "insert into ratings.units (dodo_id, name, name_normalized, country_code) "
                "values (%s, %s, %s, %s)",
                (dodo, name, name.casefold(), country),
            )
        periods = {}
        for kind, begin, end in (
            ("rs", "2026-08-01", "2026-08-31"),
            ("rs", "2026-09-01", "2026-12-31"),
            ("rko", "2026-09-01", "2026-09-30"),
        ):
            periods[(kind, begin)] = conn.execute(
                "insert into ratings.periods (rating_type, begin_on, end_on, title_ru, title_en) "
                "values (%s, %s, %s, 'П', 'P') returning id",
                (kind, begin, end),
            ).fetchone()[0]
        for key, score, d3 in ((("rs", "2026-08-01"), 80, False), (("rs", "2026-09-01"), 24, True)):
            conn.execute(
                "insert into ratings.scores (unit_dodo_id, period_id, score, checkups_count, "
                "source, import_id, d3, d3_name) values (%s, %s, %s, 4, 'sheet', %s, %s, %s)",
                (U_RS, periods[key], score, imp, d3, "Д3 пол" if d3 else None),
            )
        conn.execute(
            "insert into ratings.scores (unit_dodo_id, period_id, score, source, import_id) "
            "values (%s, %s, 70, 'sheet', %s)",
            (U_RS, periods[("rko", "2026-09-01")], imp),
        )
        for dodo, when, acceptance in (
            ("f1" * 16, "2026-09-10 10:00+00", "accepted"),
            ("f2" * 16, "2026-09-12 10:00+00", "rejected"),
            ("f3" * 16, "2026-08-10 10:00+00", "accepted"),
        ):
            conn.execute(
                "insert into ratings.checkups (rating_type, dodo_id, unit_dodo_id, occurred_at, "
                "acceptance, import_id) values ('rs', %s, %s, %s, %s, %s)",
                (dodo, U_RS, when, acceptance, imp),
            )
        conn.execute(
            "insert into ratings.violations (row_key, rating_type, checkup_dodo_id, unit_dodo_id, "
            "text, category, import_id) "
            "values ('k1', 'rs', %s, %s, 'Грязный пол', 'violation', %s), "
            "('k2', 'rs', %s, %s, 'Пыль', 'violation', %s)",
            ("f1" * 16, U_RS, imp, "f3" * 16, U_RS, imp),
        )


def test_разбивка_по_периодам_считает_загруженное_по_окну_периода(db_env: str) -> None:
    _вставить(db_env)

    rows = ratings_read.unit_periods(
        U_RS, rating_type=None, begin=date(2026, 8, 1), end=date(2026, 10, 1)
    )

    assert [(r.rating_type, r.begin_on.isoformat()) for r in rows] == [
        ("rko", "2026-09-01"),
        ("rs", "2026-09-01"),
        ("rs", "2026-08-01"),
    ]
    сентябрь = rows[1]
    assert (сентябрь.score, сентябрь.d3, сентябрь.d3_name, сентябрь.checkups_count) == (
        24.0,
        True,
        "Д3 пол",
        4,
    )
    # августовская проверка и её нарушение в сентябрьское окно не попадают
    assert (сентябрь.loaded_checkups, сентябрь.accepted_checkups, сентябрь.violations) == (2, 1, 1)
    assert (rows[2].loaded_checkups, rows[2].violations) == (1, 1)
    assert (сентябрь.import_format, сентябрь.import_channel) == ("base-scores", "sync")
    только_рко = ratings_read.unit_periods(
        U_RS, rating_type="rko", begin=date(2026, 8, 1), end=date(2026, 10, 1)
    )
    assert [r.rating_type for r in только_рко] == ["rko"] and только_рко[0].loaded_checkups == 0


def test_поиск_пиццерии_ставит_охват_в_запросе(db_env: str) -> None:
    _вставить(db_env)

    везде = ratings_read.find_units("1", countries=None, normalized="-1", limit=10)
    только_rs = ratings_read.find_units("1", countries=["RS"], normalized="-1", limit=10)
    по_id = ratings_read.find_units(U_BY, countries=["RS"], normalized=U_BY, limit=10)

    assert {u.unit for u in везде} == {U_RS, U_BY}
    assert {u.unit for u in только_rs} == {U_RS}
    assert по_id == ()  # чужая страна не находится и по точному id
