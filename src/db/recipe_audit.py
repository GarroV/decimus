"""T203 (#170): можно ли снять прежний рецепт отпечатка на ЭТОЙ базе.

Прежние рецепты (`fingerprint.previous_fingerprints`) — совместимость, а не
архитектура: слив ищет проверку сперва по ним, чтобы смена рецепта не положила
уже слитую проверку второй строкой в историю точки. Совместимость обязана
однажды уйти, иначе будет жить вечно и обрастать следующими рецептами. Уйти она
может ровно тогда, когда известно, что строк прежнего рецепта не осталось ни в
одной базе — своей, владельца и площадки.

**Почему это модуль, а не строчка в отчёте.** Знание «строк нет» есть у
площадки, а не у кода, и добывалось оно до сих пор словами. Слова на трёх
машинах не сверить: базы владельца и площадки отсюда не видны, а цена ошибки
здесь необратима — запечатанная проверка не правится и не удаляется (миграция
`0004`). Прогон этой проверки даёт на каждой машине один и тот же однозначный
ответ, который можно приложить к решению.

**Что считается доказательством.** Только полный ноль проверок. Разобрать,
каким рецептом считан отпечаток конкретной строки, отсюда нельзя: отпечаток —
это `sha256` поверх `json.dumps` по данным, часть которых лежит в
`translations`, и восстановить исходные данные строки байт в байт, чтобы
пересчитать, — та же задача, которую задача #170 прямо запрещает решать
миграцией, и по той же причине. Поэтому проверка отвечает на вопрос, на
который ответить МОЖНО: сколько всего строк в базе, и сколько из них слито до
наката информационной части (те заведомо прежнего рецепта — информационной
части тогда не было ни в схеме, ни в отпечатке).

**Главная ловушка — видимость, а не арифметика.** С миграции `0010` снятая
проверка не видна обычной роли построчной политикой. Тот же
`select count(*) from inspections` под ролью приложения ответит «ноль» на базе,
где строки есть: ответ ложный, вид — успешный, последствие — необратимое.
Поэтому связь, которая снятых проверок не видит, здесь ОТКАЗЫВАЕТ. Непроверенное
не значит безопасное.

Запуск: `python -m src.db.recipe_audit` (берёт `DATABASE_ADMIN_URL`, а нет её —
`DATABASE_URL`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .errors import ConfigError
from .migrate import ADMIN_ROLE, DATABASE_ADMIN_URL_VAR

#: Миграция, которой появилась информационная часть проверки (T200). Всё, что
#: слито до её наката, считано рецептом БЕЗ информационной части — то есть
#: прежним. Обратное неверно: слитое после могло быть записано и старым кодом,
#: если накат опередил выкладку. Поэтому уточнение называет заведомо прежние
#: строки, а разрешает снятие по-прежнему только полный ноль.
INFO_PART_MIGRATION = "0009_inspection_info.sql"

_VISIBILITY_SQL = """
select
    current_database(),
    coalesce(
        (select rolsuper or rolbypassrls from pg_roles where rolname = current_user),
        false
    ),
    coalesce(
        (select pg_has_role(current_user, oid, 'member')
         from pg_roles where rolname = %s),
        false
    )
"""


@dataclass(frozen=True)
class LegacyRecipeReport:
    """Ответ по ОДНОЙ базе. Решение принимается по трём таким ответам сразу."""

    #: Имя базы, к которой ходили. В отчёте обязательно: три ответа с разных
    #: машин без него неразличимы, и «проверено везде» доказывалось бы тремя
    #: одинаковыми строчками ни о чём.
    database: str

    #: Всего проверок, включая снятые.
    inspections: int

    #: Сколько из них слито ДО наката `INFO_PART_MIGRATION`. `None` — историю
    #: схемы этой связи читать не дано (так у роли администратора истории), и
    #: уточнение осталось неизвестным. Именно `None`, а не ноль: ноль здесь
    #: читался бы как «таких строк нет».
    pushed_before_info: int | None

    @property
    def can_retire_previous_recipes(self) -> bool:
        """Можно ли снимать прежние рецепты — на этой базе и только на ней."""
        return self.inspections == 0

    def summary(self) -> str:
        строки = [f"База: {self.database}", f"Проверок всего (включая снятые): {self.inspections}"]
        if self.inspections:
            заведомо = (
                "неизвестно (историю схемы этой связи читать не дано)"
                if self.pushed_before_info is None
                else str(self.pushed_before_info)
            )
            строки.append(f"Из них слито до наката {INFO_PART_MIGRATION}: {заведомо}")
        if self.can_retire_previous_recipes:
            строки.append(
                "Прежние рецепты отпечатка снимать МОЖНО — на этой базе строк, "
                "которые могли бы лежать под ними, нет."
            )
        else:
            строки.append(
                "Прежние рецепты отпечатка снимать НЕЛЬЗЯ: в базе есть проверки, "
                "а каким рецептом считан отпечаток каждой — отсюда не видно."
            )
        строки.append(
            "Ответ относится ТОЛЬКО к этой базе. Снятие возможно, когда такой же "
            "ответ получен на всех: своей, владельца и площадки."
        )
        return "\n".join(строки)


def _require_visibility(conn: psycopg.Connection[Any]) -> str:
    """Убедиться, что этой связи видны СНЯТЫЕ проверки. Вернуть имя базы.

    Отказ, а не подсчёт по видимой части: под ролью приложения построчная
    политика прячет снятые проверки, и счёт ответил бы «ноль» на базе, где
    строки есть.
    """
    row = conn.execute(_VISIBILITY_SQL, (ADMIN_ROLE,)).fetchone()
    if row is None:  # pragma: no cover — запрос без `from` всегда даёт строку
        raise ConfigError("База не ответила на запрос о правах связи")
    database = str(row[0])
    bypasses_rls = bool(row[1])
    is_history_admin = bool(row[2])
    if not (bypasses_rls or is_history_admin):
        raise ConfigError(
            f"Этой связи не видны снятые проверки: роль не обходит построчные "
            f"политики и не состоит в {ADMIN_ROLE}. Считать по ней нельзя — "
            f"снятые проверки выпали бы из счёта, и «ноль» ничего бы не значил. "
            f"Ходить сюда связью наката ({DATABASE_ADMIN_URL_VAR}) или связью "
            f"администратора истории."
        )
    return database


def _info_part_applied_at(conn: psycopg.Connection[Any]) -> tuple[bool, datetime | None]:
    """Когда накатана информационная часть: (история читается, время наката).

    Первый член пары отделяет «читать не дано» от «не накатано»: у роли
    администратора истории прав на `schema_migrations` нет, и это не то же
    самое, что миграция отсутствует.
    """
    try:
        with conn.transaction():
            row = conn.execute(
                "select applied_at from schema_migrations where filename = %s",
                (INFO_PART_MIGRATION,),
            ).fetchone()
    except psycopg.errors.InsufficientPrivilege:
        return False, None
    except psycopg.errors.UndefinedTable:
        # Таблицы истории нет вовсе — база не накатывалась этим раннером.
        return True, None
    if row is None:
        return True, None
    applied_at: datetime = row[0]
    return True, applied_at


def audit_legacy_recipes(dsn: str) -> LegacyRecipeReport:
    """Сосчитать, что лежит в базе, и сказать, можно ли снимать прежние рецепты."""
    with psycopg.connect(dsn) as conn:
        database = _require_visibility(conn)
        row = conn.execute("select count(*) from inspections").fetchone()
        inspections = 0 if row is None else int(row[0])

        pushed_before_info: int | None = None
        history_readable, applied_at = _info_part_applied_at(conn)
        if history_readable and applied_at is None:
            # Информационной части в схеме нет — значит и в отпечатке её нет
            # ни у одной из лежащих строк.
            pushed_before_info = inspections
        elif history_readable:
            before = conn.execute(
                "select count(*) from inspections where pushed_at < %s", (applied_at,)
            ).fetchone()
            pushed_before_info = 0 if before is None else int(before[0])

    return LegacyRecipeReport(
        database=database,
        inspections=inspections,
        pushed_before_info=pushed_before_info,
    )


def main() -> None:  # pragma: no cover — тонкая обёртка CLI, части проверены по отдельности
    from .config import check_environment
    from .migrate import admin_dsn, load_env_file

    load_env_file()
    dsn = admin_dsn() or check_environment().dsn
    print(audit_legacy_recipes(dsn).summary())


if __name__ == "__main__":  # pragma: no cover
    main()
