"""Роль приложения и предупреждение о её всесилии (T111).

Защита завершённых проверок держится построчными политиками, а суперпользователь
обходит их **всегда**. Значит приложение, пущенное под привилегированной ролью,
выглядит защищённым, ничем таковым не являясь, — и узнать об этом можно только
если раннер скажет вслух.

Эти пути остались непокрытыми, когда работа блока оборвалась по лимиту сессии:
код был написан и работал, а тестов на него не появилось. Дописано диспетчером.
"""

from __future__ import annotations

from pathlib import Path

import db_harness
import pytest
from conftest import requires_db
from db_harness import empty_database, empty_database_with_unique_roles

psycopg = pytest.importorskip("psycopg")

from src.db import migrate  # noqa: E402 — после importorskip намеренно
from src.db.errors import ConfigError  # noqa: E402
from src.db.migrate import (  # noqa: E402
    ADMIN_ROLE,
    APP_ROLE,
    DATABASE_ADMIN_URL_VAR,
    DATABASE_APP_PASSWORD_VAR,
    DATABASE_RETRACTION_PASSWORD_VAR,
    _set_role_password,
    admin_dsn,
    apply_migrations,
    discover_migrations,
    role_bypasses_rls,
    set_app_password,
)


def test_каталог_миграций_которого_нет_отказывает(tmp_path: Path) -> None:
    """Пустой путь — не повод накатить ноль миграций и отчитаться об успехе."""
    with pytest.raises(ConfigError) as exc:
        discover_migrations(tmp_path / "нет-такого")
    assert "не найден" in str(exc.value)


def test_пустой_каталог_миграций_отказывает(tmp_path: Path) -> None:
    """Ноль файлов и «нечего накатывать» — разные вещи, вторая тут ложь."""
    with pytest.raises(ConfigError) as exc:
        discover_migrations(tmp_path)
    assert "ни одного файла" in str(exc.value)


def test_admin_dsn_читается_из_окружения() -> None:
    assert admin_dsn({DATABASE_ADMIN_URL_VAR: " postgresql://x/y "}) == "postgresql://x/y"


def test_admin_dsn_пустой_это_отсутствие_а_не_пустая_строка() -> None:
    """Пустая переменная не должна выглядеть как заданный адрес."""
    assert admin_dsn({DATABASE_ADMIN_URL_VAR: "   "}) is None
    assert admin_dsn({}) is None


@requires_db
def test_пустой_пароль_роли_отказывает() -> None:
    """Пустой пароль оставил бы роль приложения без входа — молча."""
    with empty_database() as dsn:
        with pytest.raises(ConfigError) as exc:
            set_app_password(dsn, "   ")
        assert DATABASE_APP_PASSWORD_VAR in str(exc.value)
        assert APP_ROLE in str(exc.value)


@requires_db
def test_суперпользователь_опознан_как_обходящий_политики() -> None:
    """Роль прогона — суперпользователь, и раннер обязан это видеть.

    Проверка, которая не может упасть, была бы бесполезна: если бы
    `role_bypasses_rls` всегда возвращала False, защита выглядела бы включённой
    везде. Поэтому здесь два утверждения — на привилегированной роли True, на
    роли приложения False.
    """
    with empty_database() as dsn:
        assert role_bypasses_rls(dsn) is True, (
            "роль прогона привилегированная, а раннер этого не заметил — значит и в бою не заметит"
        )


@requires_db
def test_роль_приложения_политики_не_обходит() -> None:
    """Встречное утверждение: после наката роль приложения уже не всесильна."""
    with empty_database() as dsn:
        apply_migrations(dsn)
        # Пароль роли НЕ ставится: утверждение теста от него не зависит, а роль
        # приложения — объект кластера, а не этой временной базы. Пока пароль
        # здесь менялся, прогон уносил с собой стенды соседних копий: следом
        # падало около девяноста чужих тестов, а виновник оставался зелёным
        # (задача #128). Сам `set_app_password` проверяется отдельно, отказом
        # на пустой пароль — там до SQL дело не доходит.
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "select rolsuper or rolbypassrls from pg_roles where rolname = %s",
                (APP_ROLE,),
            ).fetchone()
        assert row is not None, f"роль {APP_ROLE} не заведена накатом миграций"
        assert row[0] is False, (
            f"роль {APP_ROLE} обходит политики — запрет правки завершённых "
            "проверок на ней не сработает, а выглядеть будет включённым"
        )


# --- Накат на роли с уникальным именем (задача #196) --------------------------
#
# Проверки выше сторожат СОСТОЯНИЕ ролей в кластере, и это правильная проверка
# для стенда. Но роль заводится миграцией только если её ещё нет, поэтому на
# любой машине, где прогон шёл хоть раз, правка `create role dodo_audit_app
# login` на всесильную ими не ловится: `create role` попросту не выполняется.
# Проверено порчей — семь тестов остались зелёными.
#
# Ниже накат идёт на КОПИЮ миграций, где роли переименованы в уникальные
# (`empty_database_with_unique_roles`). Роли с таким именем в кластере нет,
# значит `create role` выполняется по-настоящему, и тесту видно, какой роль
# создана. Тем же ходом становится проверяемой установка пароля: на настоящей
# роли `alter role … password` действует на весь кластер и однажды унесла
# стенды соседних копий (#128).


@requires_db
def test_накат_заводит_роли_без_всесилия(tmp_path: Path) -> None:
    """Миграция, заводящая роль всесильной, обязана валить этот тест.

    Перечислены не только `rolsuper`/`rolbypassrls`: `createrole` — это тот же
    обход политик через один шаг, роль с ним выдаёт себе членство в роли
    администратора истории и начинает видеть снятые проверки, а `replication`
    читает данные мимо прав вовсе.
    """
    with empty_database_with_unique_roles(tmp_path) as (dsn, directory, roles):
        applied = apply_migrations(dsn, directory=directory)
        assert applied, "накат не применил ни одной миграции — проверять нечего"

        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "select rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb,"
                " rolreplication from pg_roles where rolname = any(%s)",
                (list(roles.values()),),
            ).fetchall()
        привилегии = {row[0]: row[1:] for row in rows}

        for настоящая, уникальная in roles.items():
            assert уникальная in привилегии, (
                f"накат не завёл роль {настоящая} — либо `create role` из миграции "
                f"пропал, либо подстановка уникального имени не сработала"
            )
            assert not any(привилегии[уникальная]), (
                f"роль {настоящая} заведена накатом всесильной "
                f"(super/bypassrls/createrole/createdb/replication = "
                f"{привилегии[уникальная]}) — построчные политики на ней не держат "
                f"ничего, а выглядеть защита будет включённой"
            )


#: Права, которые накат выдаёт роли приложения НА ТАБЛИЦУ ЦЕЛИКОМ.
#:
#: Перечень намеренно выписан руками, а не снят с кластера: он и есть
#: утверждение. Расширение гранта в миграции обязано требовать осознанной
#: правки этой таблицы — иначе проверка превращается в «сверить состояние с
#: самим собой» и пропускает ровно то, ради чего написана.
APP_TABLE_GRANTS: dict[str, set[str]] = {
    # Справочник правится по делу, но не удаляется: DELETE не выдан (`0004`).
    "tenants": {"SELECT", "INSERT"},
    "units": {"SELECT", "INSERT", "UPDATE"},
    "unit_aliases": {"SELECT", "INSERT", "UPDATE"},
    # Документ проверки: полный набор выдан НАМЕРЕННО, держит политика (`0004`).
    "inspections": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "findings": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "photos": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "translations": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "inspection_info": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    # Личный доступ к MCP живёт пометками, поэтому DELETE нет (`0011`).
    "mcp_admins": {"SELECT", "INSERT"},
    "mcp_tokens": {"SELECT", "INSERT"},
    # Карта синонимов формулировок только пополняется (`0012`, T284, D119):
    # UPDATE и DELETE не выданы намеренно. Синоним, который уже работает, не
    # переписывается ошибкой одного аудитора и не пропадает от промаха в коде —
    # разночтение слой доступа обязан НАЗВАТЬ (`synonyms.CONFLICT`), а не
    # разрешить втихую, и держит это отсутствие права, а не дисциплина вызовов.
    "phrase_aliases": {"SELECT", "INSERT"},
    # `schema_migrations` не отдаётся вовсе: историю схемы ведёт накат.
}

#: Права роли приложения НА ОТДЕЛЬНЫЕ КОЛОНКИ: таблица → право → колонки.
#:
#: Здесь заслон и стоит: `fingerprint`, владелец токена, арендатор и время
#: выпуска не правятся ни одним запросом, потому что права на них нет (`0011`).
APP_COLUMN_GRANTS: dict[str, dict[str, set[str]]] = {
    "mcp_tokens": {"UPDATE": {"revoked_at", "revoked_by"}},
    "mcp_admins": {"UPDATE": {"added_by", "added_at", "revoked_at", "revoked_by"}},
}

#: Права администратора истории на таблицу целиком — только чтение (`0010`).
ADMIN_TABLE_GRANTS: dict[str, set[str]] = {
    "units": {"SELECT"},
    "inspections": {"SELECT"},
    "findings": {"SELECT"},
    "photos": {"SELECT"},
    "translations": {"SELECT"},
    "inspection_info": {"SELECT"},
    # Карту синонимов администратор читает целиком, вместе со снятыми строками
    # (`0013`, T292): в продуктовой выдаче снятых нет, а показать человеку
    # нужно именно их. Ни INSERT, ни DELETE не выдано — заводит синонимы
    # приложение, а удалять строки в этой базе не умеет никто.
    "phrase_aliases": {"SELECT"},
}

#: А пишет администратор ровно три колонки, и это главный заслон снятия
#: (`0010`): политика «менять разрешено только пометку» не выражается вовсе,
#: потому что `with check` не видит старой строки.
ADMIN_COLUMN_GRANTS: dict[str, dict[str, set[str]]] = {
    "inspections": {"UPDATE": {"retracted_at", "retraction_reason"}},
    "photos": {"UPDATE": {"purged_at"}},
    # Правка карты синонимов (`0013`, T292) — тот же заслон, что у снятия
    # проверки: пишутся ровно названные колонки. Неприкосновенны при этом
    # арендатор, язык и ключ поиска (ключ карты не переезжает), сказанное
    # человеком дословно, происхождение записи и время её заведения. Станет
    # этот грант табличным — роль начнёт переписывать показание аудитора, и
    # поймать это, кроме как здесь, будет негде.
    "phrase_aliases": {
        "UPDATE": {
            "item_code",
            "retracted_at",
            "retraction_reason",
            "corrected_at",
            "correction_reason",
            "previous_item_code",
        }
    },
}


def _выданные_права(
    dsn: str, роль: str
) -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    """Права роли в базе, разложенные на табличные и собственно колоночные.

    `information_schema.column_privileges` разворачивает право, выданное на
    таблицу целиком, на КАЖДУЮ её колонку — проверено на живом Postgres. Если
    не вычесть табличные права, колоночный перечень раздуется до всех колонок
    всех таблиц, и выписать его руками станет нечем. Поэтому колоночным здесь
    считается то, что таблице целиком не выдано, — ровно `grant update (…)`.
    """
    with psycopg.connect(dsn) as conn:
        табличные_строки = conn.execute(
            "select table_name, privilege_type from information_schema.table_privileges"
            " where grantee = %s and table_schema = 'public'",
            (роль,),
        ).fetchall()
        колоночные_строки = conn.execute(
            "select table_name, privilege_type, column_name"
            " from information_schema.column_privileges"
            " where grantee = %s and table_schema = 'public'",
            (роль,),
        ).fetchall()

    табличные: dict[str, set[str]] = {}
    for таблица, право in табличные_строки:
        табличные.setdefault(таблица, set()).add(право)

    колоночные: dict[str, dict[str, set[str]]] = {}
    for таблица, право, колонка in колоночные_строки:
        if право in табличные.get(таблица, ()):
            continue
        колоночные.setdefault(таблица, {}).setdefault(право, set()).add(колонка)

    return табличные, колоночные


@requires_db
def test_накат_выдаёт_ролям_ровно_перечисленные_права(tmp_path: Path) -> None:
    """Расширение гранта в миграции обязано валить этот тест.

    Проверка выше смотрит АТРИБУТЫ роли в кластере и про права на таблицы не
    знает ничего. Поэтому правка `grant update (retracted_at,
    retraction_reason) on inspections` до `grant update on inspections` при
    первом накате не ловилась ничем: атрибуты роли те же, контрольная сумма
    миграции на свежей базе ещё ни с чем не сверяется, а
    `tests/test_db_retraction_policies.py` ходит под УЖЕ закреплённой ролью
    кластера, которой расширенный грант не достался. Свежая база плюс
    расширенный грант — та самая дыра, и закрывает её сверка ниже.

    Роли здесь одноразовые, значит `grant` из миграций выполняется
    по-настоящему и достаётся именно им, а не закреплённым ролям кластера.
    """
    with empty_database_with_unique_roles(tmp_path) as (dsn, directory, roles):
        applied = apply_migrations(dsn, directory=directory)
        assert applied, "накат не применил ни одной миграции — проверять нечего"

        for роль, ожидание_таблиц, ожидание_колонок in (
            (APP_ROLE, APP_TABLE_GRANTS, APP_COLUMN_GRANTS),
            (ADMIN_ROLE, ADMIN_TABLE_GRANTS, ADMIN_COLUMN_GRANTS),
        ):
            табличные, колоночные = _выданные_права(dsn, roles[роль])
            assert табличные == ожидание_таблиц, (
                f"накат выдал роли {роль} не те права на таблицы целиком. Если "
                f"право добавлено намеренно — дописать его в перечень теста и "
                f"объяснить зачем; если нет — это расширение доступа, которое "
                f"на свежей базе не поймает больше ничто"
            )
            assert колоночные == ожидание_колонок, (
                f"накат выдал роли {роль} не те права на отдельные колонки. "
                f"Пропавшая здесь строка означает, что колоночный грант стал "
                f"табличным, то есть роль правит всю строку целиком — заслон "
                f"снятия ({ADMIN_ROLE}) или подмены отпечатка ({APP_ROLE}) "
                f"держится ровно этим перечнем"
            )


@requires_db
def test_роль_приложения_не_состоит_в_роли_администратора(tmp_path: Path) -> None:
    """Разграничение снятых проверок держится членством — его не должно быть.

    Миграция `0010` пускает к снятым проверкам через
    `pg_has_role(current_user, 'dodo_audit_admin', 'member')`. Выданное накатом
    членство роли приложения в роли администратора сняло бы это разграничение
    целиком, и ни один тест снятия этого бы не заметил: он ходит под своими
    связями, а не проверяет, кто кому член.
    """
    with empty_database_with_unique_roles(tmp_path) as (dsn, directory, roles):
        apply_migrations(dsn, directory=directory)
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "select pg_has_role(%s, %s, 'member')",
                (roles[APP_ROLE], roles[ADMIN_ROLE]),
            ).fetchone()
        assert row is not None and row[0] is False, (
            f"роль приложения {APP_ROLE} состоит в роли администратора истории "
            f"{ADMIN_ROLE} — снятые проверки видны приложению, хотя вся защита "
            f"миграции 0010 построена на обратном"
        )


@requires_db
def test_пароль_ложится_роли_и_кавычка_в_нём_не_ломает_запрос(tmp_path: Path) -> None:
    """Установка пароля проверяется на временной роли, а не на настоящей.

    На настоящей её проверить нельзя: `alter role … password` меняет объект
    кластера, а кластер общий — так прогон и унёс стенды соседних копий (#128).
    Здесь роль своя и одноразовая, поэтому можно и поставить пароль, и убедиться,
    что он лёг.

    Кавычка в пароле — не придирка: пароль приходит из `.env`, то есть извне
    кода, и склеенный руками `alter role` был бы ровно тем местом, где она
    превращается в чужой SQL.
    """
    with empty_database_with_unique_roles(tmp_path) as (dsn, directory, roles):
        apply_migrations(dsn, directory=directory)
        роль = roles[APP_ROLE]
        _set_role_password(dsn, 'па\'роль "с кавычками"', role=роль, var=DATABASE_APP_PASSWORD_VAR)
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "select rolpassword is not null from pg_authid where rolname = %s",
                (роль,),
            ).fetchone()
        assert row is not None and row[0] is True, (
            f"пароль роли {роль} не поставлен — на стенде с парольной "
            f"аутентификацией она просто не войдёт"
        )


def test_пароль_уходит_той_роли_и_из_той_переменной(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пара «роль, переменная» у каждой из двух функций своя и не перепутана.

    Без базы намеренно: перепутанная пара поставила бы администратору истории
    пароль приложения, не сказав ни слова, и узнать об этом на живом кластере
    можно было бы только сломав его.
    """
    вызовы: list[tuple[str, str]] = []

    def запись(dsn: str, password: str, *, role: str, var: str) -> None:
        вызовы.append((role, var))

    monkeypatch.setattr(migrate, "_set_role_password", запись)
    migrate.set_app_password("postgresql://x/y", "пароль")
    migrate.set_admin_password("postgresql://x/y", "пароль")

    assert вызовы == [
        (APP_ROLE, DATABASE_APP_PASSWORD_VAR),
        (ADMIN_ROLE, DATABASE_RETRACTION_PASSWORD_VAR),
    ]


# --- самозаслон оснастки ------------------------------------------------------


def test_оснастка_отказывает_если_роли_в_миграциях_не_нашлось(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Переименовали роль в миграциях, забыли в оснастке — прогон обязан упасть.

    Без этого отказа `empty_database_with_unique_roles` продолжала бы работать,
    но уже вхолостую: подставлять было бы нечего, накат пошёл бы на НАСТОЯЩИЕ
    роли кластера, которые на любой рабочей машине уже заведены, — и все три
    проверки выше стали бы сверять состояние закреплённых ролей, ничего не
    ловя. Отказ проверен руками, своей регрессии у него не было.

    База здесь не нужна намеренно: сверка имён идёт до `create database`, а
    значит эта проверка работает и там, где Postgres рядом нет, — ровно там,
    где молчаливое выключение и осталось бы незамеченным.
    """
    monkeypatch.setattr(db_harness, "MIGRATION_ROLES", ("dodo_audit_app", "dodo_audit_привидение"))
    with pytest.raises(AssertionError) as exc:
        with db_harness.empty_database_with_unique_roles(tmp_path):
            pytest.fail("оснастка не отказала и завела базу — сверка имён ролей выключена")

    assert "dodo_audit_привидение" in str(exc.value), (
        "отказ не назвал роль, которой не нашлось, — по такому сообщению "
        "непонятно, что именно чинить"
    )
    assert "dodo_audit_app" not in str(exc.value), (
        "в отказ попала роль, которая в миграциях есть: сверка считает "
        "вхождения не по каждой роли отдельно, и настоящая пропажа утонет "
        "в перечислении всех подряд"
    )
