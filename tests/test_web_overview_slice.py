"""#470: «Обзор» и «Страна» считают по всему срезу, а не по сотне последних по сети.

Предел ряда раньше брался ДО отбора по месту: база отдавала сто свежих проверок
всей сети, и уже из них выбиралась страна, город или буква. Пока в сети за
период меньше ста проверок, разницы нет; больше — и страна, чьи проверки старше
сотой по сети, получала неполный ряд: другая средняя, меньше точек, короче
история. Соседние блоки того же экрана (потери по зонам, системные нарушения)
считаются запросом с отбором в базе и видели весь срез — экран говорил о двух
разных множествах и ни слова об этом.

Здесь — настоящая база: сто свежих проверок Сербии и одна, самая старая, в
Грузии. Отбор поверх прочитанной сотни грузинскую проверку теряет; отбор в
запросе — нет. А когда предел всё же срабатывает на самом срезе, снимок обязан
сказать об этом (`truncated`), а не обрезать молча.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.reach import own_reach  # noqa: E402 — после importorskip намеренно
from src.web import country as cn  # noqa: E402
from src.web import overview as ov  # noqa: E402

pytestmark = requires_db

#: Предел ряда, как у экрана (`app.REGISTRY_LIMIT`).
ПРЕДЕЛ = 100

#: Самая старая проверка сети — грузинская; сербские свежее неё.
НАЧАЛО = date(2025, 1, 1)

_ТОЧКА_SQL = """
insert into units (tenant_code, name, name_normalized, country, city)
values ('HQ', %(name)s, lower(%(name)s), %(country)s, %(city)s)
returning id
"""

_ПРОВЕРКИ_SQL = """
insert into inspections (
    tenant_code, unit_id, chat_id, kind, inspection_date, report_lang,
    ui_lang, speech_lang, checklist_version, pct, grade, source_fingerprint
)
select
    'HQ', %(unit)s, 1, 'planned', %(начало)s::date + g, 'ru',
    'ru', 'ru', 'v1', %(pct)s, %(grade)s, %(метка)s || '-' || g
from generate_series(0, %(сколько)s - 1) g
"""


def _точка(cur: psycopg.Cursor, *, name: str, country: str, city: str) -> str:
    cur.execute(_ТОЧКА_SQL, {"name": name, "country": country, "city": city})
    row = cur.fetchone()
    assert row is not None
    return str(row[0])


def _проверки(
    cur: psycopg.Cursor,
    *,
    unit: str,
    начало: date,
    сколько: int,
    pct: float,
    grade: str,
    метка: str,
) -> None:
    cur.execute(
        _ПРОВЕРКИ_SQL,
        {
            "unit": unit,
            "начало": начало,
            "сколько": сколько,
            "pct": pct,
            "grade": grade,
            "метка": метка,
        },
    )


@pytest.fixture
def сеть(pg_dsn: str, db_env: str) -> dict[str, str]:
    """Сто свежих проверок Белграда и одна старейшая — Тбилиси; `{точка: id}`."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        белград = _точка(cur, name="Белград-1", country="RS", city="Белград")
        тбилиси = _точка(cur, name="Тбилиси-1", country="GE", city="Тбилиси")
        _проверки(cur, unit=тбилиси, начало=НАЧАЛО, сколько=1, pct=82.0, grade="C", метка="ge")
        _проверки(
            cur,
            unit=белград,
            начало=НАЧАЛО + timedelta(days=1),
            сколько=ПРЕДЕЛ,
            pct=97.5,
            grade="A",
            метка="rs",
        )
        conn.commit()
    return {"Белград-1": белград, "Тбилиси-1": тбилиси}


@pytest.mark.parametrize(
    "selection",
    [
        ov.Selection(country="GE"),
        ov.Selection(city="Тбилиси"),
        ov.Selection(grade="C"),
    ],
    ids=["страна", "город", "буква"],
)
def test_срез_видит_проверку_старше_сотой_по_сети(
    сеть: dict[str, str], selection: ov.Selection
) -> None:
    снимок = ov.load(reach=own_reach("HQ"), limit=ПРЕДЕЛ, selection=selection)

    assert [r.unit_name for r in снимок.inspections] == ["Тбилиси-1"]
    assert снимок.average == 82.0
    assert {буква: n for буква, n in снимок.grades if n} == {"C": 1}
    assert not снимок.truncated


def test_экран_страны_видит_историю_точки_старше_сотой_по_сети(
    сеть: dict[str, str],
) -> None:
    вид = cn.load(
        reach=own_reach("HQ"),
        limit=ПРЕДЕЛ,
        code="GE",
        selection=ov.Selection(),
        unit_id=сеть["Тбилиси-1"],
    )

    assert вид.unit_name == "Тбилиси-1"
    assert len(вид.history) == 1
    assert [p.unit for p in вид.snapshot.points] == ["Тбилиси-1"]


def test_срез_ровно_в_предел_не_помечен_обрезанным(сеть: dict[str, str]) -> None:
    снимок = ov.load(reach=own_reach("HQ"), limit=ПРЕДЕЛ, selection=ov.Selection(country="RS"))

    assert len(снимок.inspections) == ПРЕДЕЛ
    assert not снимок.truncated


def test_срез_больше_предела_помечен_обрезанным(сеть: dict[str, str]) -> None:
    # Сто одна проверка сети при пределе сто: показать сто можно, промолчать
    # о сто первой — нет.
    снимок = ov.load(reach=own_reach("HQ"), limit=ПРЕДЕЛ, selection=ov.Selection())

    assert len(снимок.inspections) == ПРЕДЕЛ
    assert снимок.truncated


def test_плитки_и_буквы_считаются_по_всему_срезу_а_не_по_последним(
    сеть: dict[str, str],
) -> None:
    # #503: сто одна проверка при пределе сто. Последние сто — сербские по
    # 97.5, сто первая — грузинская 82.0. Средняя по последним сотне — 97.5,
    # по всему срезу — 97.3; буквы — сто A и одна C. Плитки обязаны говорить
    # о том же множестве, что потери по зонам и системные нарушения.
    снимок = ov.load(reach=own_reach("HQ"), limit=ПРЕДЕЛ, selection=ov.Selection())

    assert снимок.average == round((ПРЕДЕЛ * 97.5 + 82.0) / (ПРЕДЕЛ + 1), 1)
    assert {буква: n for буква, n in снимок.grades if n} == {"A": ПРЕДЕЛ, "C": 1}
    assert (снимок.inspections_total, снимок.units_checked, снимок.unchecked) == (
        ПРЕДЕЛ + 1,
        2,
        0,
    )
    # Таблица — по-прежнему последние сто, и об этом сказано.
    assert len(снимок.inspections) == ПРЕДЕЛ
    assert снимок.truncated


def test_плитка_критических_считает_весь_срез(сеть: dict[str, str], pg_dsn: str) -> None:
    # Критическое нарушение — у сто первой, самой старой проверки сети. В ряд
    # с пределом сто она не попадает, но плитка говорит обо всём срезе, как
    # и остальные плитки (тот же отбор, что у `class_counts`).
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "insert into findings (inspection_id, n, code, level, zone) "
            "select id, 1, 'CLN05', 'D3', 'hot_kitchen' from inspections where unit_id = %s",
            (сеть["Тбилиси-1"],),
        )
        conn.commit()

    снимок = ov.load(reach=own_reach("HQ"), limit=ПРЕДЕЛ, selection=ov.Selection())

    assert снимок.critical_total == 1
    assert "Тбилиси-1" not in {r.unit_name for r in снимок.inspections}
