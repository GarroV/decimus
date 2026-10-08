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
)

psycopg = pytest.importorskip("psycopg")

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


def test_пустой_квартал_пустые_блоки(db_env: str) -> None:
    summary = report.build(report.Selection(report.GROUP_IMF, None, quarter_period(2020, 1)))
    assert summary.lines == () or all(line.rs is None for line in summary.lines)
    assert summary.rko_cluster.total == 0 and summary.rko_cluster.per_checkup is None


def test_окно_периодов_включает_оба_края(db_env: str) -> None:
    _грузить(snapshot())
    один_день = ratings_read.score_facts(
        countries=["RS"], begin=date(2026, 9, 16), end=date(2026, 9, 16)
    )
    assert [(f[0], f[3]) for f in один_день] == [(U1, "rs")]
    до_конца = ratings_read.score_facts(
        countries=["RS"], begin=date(2026, 9, 17), end=date(2026, 9, 29)
    )
    assert [(f[0], f[3], f[5]) for f in до_конца] == [(U1, "rko", date(2026, 9, 29))]


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
