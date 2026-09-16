"""T203 (#170): проверяемый ответ на вопрос «строк прежнего рецепта в базе нет».

Прежний рецепт отпечатка снимать можно только тогда, когда известно, что строк
под ним не осталось НИ В ОДНОЙ базе — своей, владельца и площадки. Знание это
есть у площадки, а не у кода, и до сих пор оно добывалось словами. Здесь оно
добывается запросом, который можно прогнать на каждой из трёх машин и получить
один и тот же однозначный ответ.

Главная ловушка этой проверки — не арифметика, а ВИДИМОСТЬ. С миграции `0010`
снятая проверка не видна обычной роли построчной политикой: тот же
`select count(*) from inspections` под ролью приложения ответит «ноль» на базе,
где строки есть. Ответ будет ложным, выглядеть будет успехом, а ценой ошибки
станет необратимая двойная строка в истории точки. Поэтому связь, которая
снятых проверок не видит, здесь ОТКАЗЫВАЕТ, а не считает.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.errors import ConfigError  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.recipe_audit import (  # noqa: E402
    INFO_PART_MIGRATION,
    audit_legacy_recipes,
)
from src.db.retract import retract_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ЧАТ = 2030
ТОЧКА = "Белград-1"
АРЕНДАТОР = "default"


@pytest.fixture
def retraction_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Связь администратора истории рядом со связью приложения."""
    return set_retraction_env(db_env, monkeypatch)


def _слить() -> str:
    """Слить одну проверку на синтетической методике (`domain_env`)."""
    start_inspection(ЧАТ, unit=ТОЧКА, kind="planned", report_lang="ru")
    add_finding(ЧАТ, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(ЧАТ)


@requires_db
def test_пустая_база_разрешает_снять_прежний_рецепт(pg_dsn: str) -> None:
    """Ноль проверок — единственное, что доказывает отсутствие прежних строк.

    Доказывает именно потому, что не требует разбирать, каким рецептом считан
    каждый отпечаток: нет строк — нет и строк прежнего рецепта.
    """
    отчёт = audit_legacy_recipes(pg_dsn)

    assert отчёт.inspections == 0
    assert отчёт.can_retire_previous_recipes is True
    assert отчёт.database


@requires_db
def test_слитая_проверка_запрещает_снятие(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    """Одна строка — и снимать нельзя: рецепт, которым она считана, отсюда не виден."""
    _слить()

    отчёт = audit_legacy_recipes(pg_dsn)

    assert отчёт.inspections == 1
    assert отчёт.can_retire_previous_recipes is False


@requires_db
def test_снятая_проверка_из_счёта_не_пропадает(
    domain_env: Path, db_env: str, retraction_env: str, pg_dsn: str
) -> None:
    """Ради этого утверждения проверка и заведена.

    Снятая проверка остаётся строкой в базе и остаётся носителем отпечатка.
    Спрятанная от счёта политикой, она дала бы «ноль» там, где строка есть, —
    то есть разрешение снять совместимость на базе, где снимать её нельзя.
    """
    inspection_id = _слить()
    retract_inspection(inspection_id, tenant=АРЕНДАТОР, reason="правил ошибку в шапке")

    отчёт = audit_legacy_recipes(pg_dsn)

    assert отчёт.inspections == 1, (
        "снятая проверка выпала из счёта — значит счёт идёт связью, которая "
        "не видит снятого, и его «ноль» ничего не значит"
    )
    assert отчёт.can_retire_previous_recipes is False


@requires_db
def test_связь_не_видящая_снятого_отказывает_а_не_считает(db_env: str) -> None:
    """Роль приложения снятых проверок не видит — считать ей нечего.

    Отказ, а не тихий подсчёт по видимой части: непроверенное не значит
    безопасное, а здесь цена ошибки необратима.
    """
    with pytest.raises(ConfigError) as exc:
        audit_legacy_recipes(db_env)

    текст = str(exc.value)
    assert "снят" in текст
    assert "DATABASE_ADMIN_URL" in текст


@requires_db
def test_база_без_схемы_отказывает_а_не_отвечает_нулём() -> None:
    """Пустая база — это «схемы нет», а не «строк нет», и ответы разные.

    Ответ этой проверки читают как «снимать можно», поэтому «я не смог
    посмотреть» обязано выглядеть иначе, чем «посмотрел, пусто». База без
    наката раньше отдавала сырой стек драйвера — то есть отказ был, но
    неотличимый от поломки инструмента.
    """
    from db_harness import empty_database

    with empty_database() as dsn:
        with pytest.raises(ConfigError) as exc:
            audit_legacy_recipes(dsn)

    текст = str(exc.value)
    assert "схема не накатывалась" in текст
    assert "пустая база ответом не является" in текст


def test_недоступная_база_отказывает_внятно() -> None:
    """Молчащая база — тоже отказ, а не ноль. Инструмент зовут руками на трёх
    разных машинах, и стек драйвера там не ответ."""
    with pytest.raises(ConfigError) as exc:
        audit_legacy_recipes("postgresql://nobody@127.0.0.1:1/nothing?connect_timeout=2")

    assert "не отвечает" in str(exc.value)


@requires_db
def test_администратор_истории_считать_может(
    domain_env: Path, db_env: str, retraction_env: str
) -> None:
    """Связь администратора снятое видит — значит счёту можно верить.

    Историю схемы она при этом не читает (права на `schema_migrations` ей не
    выдано), и уточнение «сколько слито до наката информационной части»
    остаётся неизвестным. Неизвестное названо неизвестным, а не нулём: ноль
    здесь читался бы как «таких строк нет».
    """
    inspection_id = _слить()
    retract_inspection(inspection_id, tenant=АРЕНДАТОР, reason="правил ошибку в шапке")

    отчёт = audit_legacy_recipes(retraction_env)

    assert отчёт.inspections == 1
    assert отчёт.pushed_before_info is None


@requires_db
def test_слитое_до_наката_информационной_части_названо_отдельно(
    domain_env: Path, db_env: str, pg_dsn: str
) -> None:
    """Проверка, слитая до появления информационной части, — ЗАВЕДОМО прежний рецепт.

    Доказательство прямое: информационной части тогда не было ни в схеме, ни в
    отпечатке. Обратное неверно — слитая позже могла быть записана и старым
    кодом, — поэтому уточнение только называет заведомо прежние строки, а
    разрешает снятие по-прежнему лишь полный ноль.
    """
    _слить()
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update schema_migrations set applied_at = now() + interval '1 day' "
            "where filename = %s",
            (INFO_PART_MIGRATION,),
        )
        conn.commit()

    отчёт = audit_legacy_recipes(pg_dsn)

    assert отчёт.inspections == 1
    assert отчёт.pushed_before_info == 1
    assert отчёт.can_retire_previous_recipes is False


@requires_db
def test_сводка_называет_базу_и_вердикт(pg_dsn: str) -> None:
    """Сводку читает человек на трёх разных машинах — база в ней названа.

    Без имени базы три ответа неразличимы между собой, и «проверено везде»
    доказывается тремя одинаковыми строчками ни о чём.
    """
    отчёт = audit_legacy_recipes(pg_dsn)

    сводка = отчёт.summary()
    assert отчёт.database in сводка
    assert "МОЖНО" in сводка
