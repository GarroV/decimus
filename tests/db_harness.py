"""Оснастка тестов блока `db`, которой не место в общем `conftest.py`.

Общий `tests/conftest.py` — файл всех блоков сразу: его правят и `domain`, и
`bot`, и правка из параллельной работы стоит конфликта на ровном месте. Всё,
что нужно только проверкам базы, живёт здесь и подключается обычным импортом
(`tests/` плоский, `sys.path` до него доводит `pythonpath = ["."]` и сам
pytest).

`psycopg` импортируется внутри тела функции, а не на уровне модуля: этот файл
собирается вместе со всем `tests/`, и голый импорт уронил бы сбор целиком в
окружении, где зависимость блока ещё не поставлена (тот же приём и та же
причина, что в `tests/conftest.py`).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import BASE_DSN


@contextmanager
def empty_database() -> Iterator[str]:
    """DSN свежесозданной базы, на которой НЕ накатана ни одна миграция.

    Отличие от фикстуры `pg_dsn` принципиальное: та отдаёт базу с уже
    применённой схемой, и на ней накат «с нуля» проверить нечем — раннер
    честно ответит «нечего накатывать». Пустая база нужна ровно там, где
    проверяется, что вся история применяется по порядку и до конца.

    Имя случайное, база удаляется в `finally` — соседние базы на том же
    сервере (проектная, чужих блоков) не трогаются ни при каком исходе.
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    # Строка запускающего берётся у `conftest`, а не из окружения: во время
    # теста переменной там уже нет — её снимает автоматическая фикстура
    # `_база_не_видна_сама_собой`, чтобы база не доставалась тому, кто её
    # не просил (T123).
    maintenance_dsn = make_conninfo(BASE_DSN, dbname="postgres")
    dbname = f"dodo_audit_test_{uuid.uuid4().hex[:12]}"

    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(dbname)))
    try:
        yield make_conninfo(BASE_DSN, dbname=dbname)
    finally:
        with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(dbname))
            )


#: Роль администратора истории (миграция `0010`). Вторая непривилегированная
#: роль базы: снятые проверки видны только ей. Проверять разграничение под
#: суперпользователем бессмысленно — он обходит политики всегда.
ADMIN_ROLE = "dodo_audit_admin"

#: Пароль роли администратора, если на этой машине к Postgres ходят по паролю.
#: Пусто — подключение идёт без него (peer/trust), как на машине разработчика.
ADMIN_PASSWORD_VAR = "DATABASE_RETRACTION_PASSWORD"

#: Переменная, из которой блок берёт подключение администратора истории.
RETRACTION_URL_VAR = "DATABASE_RETRACTION_URL"


def admin_role_dsn(dsn: str) -> str:
    """Та же база, но под ролью администратора истории.

    Пароль чужой роли отбрасывается намеренно, тем же приёмом и по той же
    причине, что в `conftest.app_role_dsn`: подставленный сюда, он дал бы отказ
    аутентификации вместо понятного «у роли администратора нет пароля».
    """
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = {k: v for k, v in conninfo_to_dict(dsn).items() if k != "password"}
    params["user"] = ADMIN_ROLE
    password = os.environ.get(ADMIN_PASSWORD_VAR)
    if password:
        params["password"] = password
    return make_conninfo(**params)


def set_retraction_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Дать тесту подключение администратора истории вдобавок к подключению приложения.

    Помощник, а не фикстура: фикстуру пришлось бы импортировать в каждый файл,
    а импортированное имя фикстуры совпадает с именем аргумента теста — и
    линтер справедливо читает это как переопределение. Поэтому файлы объявляют
    свою однострочную фикстуру поверх этого помощника.

    Обе связи выдаются одновременно, потому что так устроен продукт: половина
    проверок этого набора в том и состоит, что одна роль видит, а вторая нет.
    """
    dsn = admin_role_dsn(db_env)
    monkeypatch.setenv(RETRACTION_URL_VAR, dsn)
    return dsn


def accept_pushed(*ids: str, dsn: str | None = None) -> None:
    """Подтвердить слитые проверки так, как это делает человек на приёмке (D199).

    Слив кладёт проверку на приёмку, и в историю — в списки, обзор, находки
    точки — она попадает только после подтверждения. Тесту, которому нужна
    именно история, приходится подтвердить проверку тем же путём, что и
    админке: под ролью администратора истории. Без `ids` — все ждущие.

    `dsn` — подключение приложения (`db_env`); не задано — то, что выставила
    фикстура `db_env` в окружение. Ни того, ни другого — отказ, а не тихий
    пропуск: тест, которому не подтвердили проверку, читал бы пустую историю.
    """
    import psycopg

    основа = dsn or os.environ.get("DATABASE_URL", "")
    if not основа:
        raise AssertionError("accept_pushed: нет подключения — тесту нужна фикстура db_env")
    with psycopg.connect(admin_role_dsn(основа)) as conn:
        conn.execute(
            "update inspections set status = 'finalized', accepted_at = now(), "
            "accepted_by = 'test' where status = 'draft' and retracted_at is null "
            "and (%(all)s or id = any(%(ids)s::uuid[]))",
            {"all": not ids, "ids": list(ids)},
        )
        conn.commit()


#: Роли, которые заводит накат: приложение (`0004`) и администратор истории
#: (`0010`). Список нужен переименованию ниже, и он же сторожит сам себя —
#: роль, которой не нашлось ни в одном файле миграций, считается опечаткой и
#: валит подготовку, а не тихо выключает проверку.
MIGRATION_ROLES = ("dodo_audit_app", "dodo_audit_admin")


@contextmanager
def empty_database_with_unique_roles(
    tmp_path: Path,
) -> Iterator[tuple[str, Path, dict[str, str]]]:
    """Пустая база и КОПИЯ каталога миграций, где роли переименованы в уникальные.

    Зачем (задача #196). Роли в Postgres — объекты кластера, а не базы, и
    миграции заводят их условно: `if not exists ... then create role`. На любой
    машине, где прогон шёл хоть раз, роли уже есть, поэтому `create role` из
    миграции больше НЕ ВЫПОЛНЯЕТСЯ — и правка этой строки на всесильную роль
    тестом не ловится вовсе: проверено порчей, тесты остались зелёными. Ровно
    так же не проверить и установку пароля: `alter role … password` действует
    на весь кластер и однажды унесла стенды соседних копий (#128).

    Уникальное имя снимает оба случая разом: роли с таким именем в кластере
    нет, значит накат её создаёт по-настоящему, и тесту видны и сам `create
    role`, и все выданные ей права. За собой роль убирается — после удаления
    базы, иначе `drop role` упёрся бы в выданные в ней права.

    Отдаёт: строку подключения, каталог с переименованными миграциями и карту
    «настоящее имя роли → уникальное».
    """
    import uuid as _uuid

    from src.db.migrate import MIGRATIONS_DIR

    suffix = _uuid.uuid4().hex[:12]
    names = {role: f"{role}_{suffix}" for role in MIGRATION_ROLES}
    target = tmp_path / f"migrations_{suffix}"
    target.mkdir()

    hits = dict.fromkeys(MIGRATION_ROLES, 0)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for role, unique in names.items():
            hits[role] += text.count(role)
            text = text.replace(role, unique)
        (target / path.name).write_text(text, encoding="utf-8")

    # Подстановка, не нашедшая ни одного вхождения, — это молчаливо выключенная
    # проверка: миграции накатились бы на НАСТОЯЩИЕ роли, тест сверил бы
    # состояние кластера и снова ничего не поймал. Роль переименовали в коде —
    # переименовать и здесь, а не узнавать об этом через полгода.
    missing = [role for role, count in hits.items() if count == 0]
    if missing:
        raise AssertionError(
            f"в миграциях не найдено ни одного упоминания ролей {missing} — "
            f"подстановка уникального имени не сработала бы, и накат пошёл бы "
            f"на настоящие роли кластера; поправить MIGRATION_ROLES"
        )

    try:
        with empty_database() as dsn:
            yield dsn, target, names
    finally:
        _drop_roles(names.values())


def _drop_roles(roles: Iterable[str]) -> None:
    """Убрать за собой временные роли. Зовётся после удаления базы.

    Порядок обязателен: пока база жива, у роли в ней есть выданные права и
    построчные политики, и `drop role` отказывает «объекты зависят от роли».
    После удаления базы зависимостей не остаётся.
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    maintenance_dsn = make_conninfo(BASE_DSN, dbname="postgres")
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        for role in roles:
            conn.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))


# ── Пространства партнёров и один справочник (волна 1, #340; D284) ─────────
#
# Проверка партнёра ссылается на точку справочника УК своей страны: своих точек
# партнёр не заводит (D234). Поэтому оснастка, которой нужна проверка
# партнёра, сначала заводит точку у УК со страной и привязывает пространство к
# стране — ровно так, как это будет на площадке.

_номер_чата = iter(range(910_000, 1_000_000))


def привязать_страну(pg_dsn: str, *, tenant: str, country: str) -> None:
    """Пространство `tenant` привязано к стране `country` (строка `space_countries`).

    Пишет под ролью, создавшей базу: роли приложения эта таблица только для
    чтения, и заводит пространства не продукт, а команда (задача 13).
    """
    import psycopg

    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values (%s) on conflict do nothing", (tenant,))
        cur.execute(
            "insert into space_countries (country, tenant_code) values (%s, %s) "
            "on conflict do nothing",
            (country, tenant),
        )


def точка_справочника(name: str, *, country: str, city: str = "") -> str:
    """Точка справочника УК со страной; возвращает её идентификатор."""
    from src.db.directory import upsert_unit

    return upsert_unit(name, country=country, city=city or None, tenant="HQ")


def слить_проверку(
    *,
    unit: str,
    tenant: str,
    chat_id: int | None = None,
    text: str = "нагар на печи",
    date: str | None = None,
    accept: bool = True,
) -> str:
    """Завершённая проверка через официальный контракт домена и слив; её `id`.

    Нужны `domain_env` (каталог состояния) и `db_env` (база) — фикстуры
    вызывающего. Имя не `push_inspection`: так называется слив по чату в
    `src.db.push`, и одноимённый помощник с другой сигнатурой путал бы (Н23).

    По умолчанию проверка ещё и подтверждается (D199): наборам этого помощника
    нужна история сети, а ждущая приёмки в историю не входит. `accept=False` —
    оставить её на приёмке.
    """
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_номер_чата) if chat_id is None else chat_id
    start_inspection(чат, unit=unit, kind="planned", report_lang="ru", tenant=tenant, date=date)
    add_finding(чат, code="CLN03", level="D1", zone="hot_kitchen", text=text)
    ident = push_inspection(чат)
    if accept:
        accept_pushed(ident)
    return ident


def привязать_пространства(pg_dsn: str, *tenants: str) -> None:
    """Каждое пространство привязано к стране своего кода (`GE` → `GE`).

    Для наборов про изоляцию партнёров друг от друга: код пространства и код
    страны совпадают, и точка «страны партнёра» не требует отдельной таблицы.
    """
    for tenant in tenants:
        привязать_страну(pg_dsn, tenant=tenant, country=tenant)


def точка_пространства(unit: str, *, tenant: str) -> None:
    """Точка, на которую `tenant` может слить проверку.

    У УК слив заводит точку сам. У партнёра — точка справочника УК в стране его
    кода (пара к `привязать_пространства`). Точку, уже заведённую в другой
    стране, помощник не переносит: одноимённых точек у двух пространств при
    одном справочнике не бывает (D284), и тест, которому это нужно, врёт.
    """
    from src.db.directory import list_units
    from src.db.reach import Reach
    from src.domain.tenants import HQ_TENANT, canonical_tenant

    if canonical_tenant(tenant) == HQ_TENANT:
        return
    уже = {u.name: u.country for u in list_units(reach=Reach(HQ_TENANT, None, None))}
    if unit in уже and уже[unit] != tenant:
        raise AssertionError(
            f"Точка «{unit}» уже заведена в стране {уже[unit]}, а сливает её {tenant}: "
            f"при одном справочнике одноимённых точек у двух пространств нет (D284)"
        )
    точка_справочника(unit, country=tenant)


def пространства_для_теста(request: pytest.FixtureRequest, *tenants: str) -> None:
    """Привязать пространства к странам своего кода — если тесту нужна база.

    Для автоматической фикстуры набора, где база нужна не всем тестам: тест без
    `db_env` базы не получает и здесь, а тест с ней получает ту же базу, что
    `db_env` (`pg_dsn` один на тест).
    """
    if "db_env" in request.fixturenames:
        привязать_пространства(request.getfixturevalue("pg_dsn"), *tenants)
