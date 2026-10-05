"""T092: справочник точек и карта синонимов.

Задача не про ввод: название пиццерии в первой версии по-прежнему приходит
текстом (D051), и бот здесь не меняется. Задача про то, ЧЕМ введённая строка
становится. Раньше «БГ2» и «Белград 2» заводили две несвязанные точки с двумя
историями — а история точки и есть то, ради чего проверки складываются в базу
(D035). Теперь синоним приводит к той же точке по её идентификатору.

Связь идёт кодами, не формулировками (конституция, принцип 5): проверка
ссылается на `units.id`, а написание живёт отдельной строкой и на связь не
влияет — синоним можно переименовать, добавить и убрать, ничего не сломав.

Ключ сопоставления один на всю карту — `normalize_unit_name` из `units.py`.
Второе правило нормализации здесь было бы худшим из возможных дефектов:
справочник и слив расходились бы молча и только на части написаний.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .config import check_environment
from .errors import PushError, UnitExistsError
from .reach import Reach, require_reach
from .space_guard import require_space
from .units import normalize_unit_name

#: Арендатор по умолчанию — то же значение, что у `push.DEFAULT_TENANT` и у
#: `domain.state.DEFAULT_TENANT`. Импортировать чужую внутреннюю константу ради
#: одной строки дороже, чем закрепить значение тестом (так же сделано в push).
DEFAULT_TENANT = HQ_TENANT


@dataclass(frozen=True)
class Unit:
    """Точка справочника: идентификатор, каноничное название, синонимы, география."""

    id: str
    name: str
    code: str | None
    aliases: tuple[str, ...]
    #: Код страны ISO 3166-1 alpha-2 в верхнем регистре. `None` — географии у
    #: точки нет: она заведена по факту первой проверки, и откуда она, никто
    #: не спрашивал. Это НЕ «страна неизвестна навсегда» — проставить её может
    #: загрузка справочника или человек.
    country: str | None = None
    #: Город как он называется в источнике. Без справочника и без нормализации.
    city: str | None = None


_SELECT_UNITS_SQL = """
select u.id, u.name, u.code, coalesce(array_agg(a.alias order by a.alias)
       filter (where a.alias is not null), '{}'), u.country, u.city
from units u
left join unit_aliases a on a.unit_id = u.id
where u.tenant_code = 'HQ'
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(country)s::text is null or u.country = %(country)s)
group by u.id, u.name, u.code, u.country, u.city
order by u.country nulls last, u.city nulls last, u.name
"""

# Порядок ветвей задан ЯВНО колонкой приоритета, а не тем, что каноничное
# название написано в запросе первым: `union all` порядок строк не обещает, и
# планировщик волен отдать сперва ветку синонимов. Проверено на себе — тест
# «каноничное название сильнее синонима» на одном и том же коде то проходил,
# то падал, пока приоритет не стал явным.
_RESOLVE_SQL = """
select id, name, code from (
    select u.id, u.name, u.code, 0 as priority
    from units u
    where u.tenant_code = %(tenant)s and u.name_normalized = %(key)s
    union all
    select u.id, u.name, u.code, 1 as priority
    from unit_aliases a
    join units u on u.id = a.unit_id
    where a.tenant_code = %(tenant)s and a.alias_normalized = %(key)s
) candidates
order by priority
limit 1
"""


# География проставляется через `coalesce(excluded…, units…)` и в обеих
# ветвях: повторная загрузка НЕ обязана знать всё, что знает база. Загрузчик
# справочника отдаёт страну и город, а человек, заводящий точку руками одним
# названием, — нет; прямое присваивание стёрло бы его же географию обратно в
# NULL и сделало бы это молча.
_UPSERT_UNIT_BY_CODE_SQL = """
insert into units (tenant_code, name, name_normalized, code, country, city)
values (%(tenant)s, %(name)s, %(key)s, %(code)s, %(country)s, %(city)s)
on conflict (tenant_code, code) do update set name = excluded.name,
    name_normalized = excluded.name_normalized,
    country = coalesce(excluded.country, units.country),
    city = coalesce(excluded.city, units.city)
returning id
"""

_UPSERT_UNIT_BY_NAME_SQL = """
insert into units (tenant_code, name, name_normalized, code, country, city)
values (%(tenant)s, %(name)s, %(key)s, %(code)s, %(country)s, %(city)s)
on conflict (tenant_code, name_normalized) do update set name = excluded.name,
    code = coalesce(excluded.code, units.code),
    country = coalesce(excluded.country, units.country),
    city = coalesce(excluded.city, units.city)
returning id
"""

# Заведение новой точки, а не «завести или обновить»: совпадение имени — дубль,
# и решает его человек, а не молчаливое обновление чужой строки (#437).
_INSERT_NEW_UNIT_SQL = """
insert into units (tenant_code, name, name_normalized, country, city)
values (%(tenant)s, %(name)s, %(key)s, %(country)s, %(city)s)
on conflict (tenant_code, name_normalized) do nothing
returning id
"""

_INSERT_NEW_ALIAS_SQL = """
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
values (%s, %s, %s, %s)
on conflict (tenant_code, alias_normalized) do nothing
"""

_UPSERT_ALIAS_SQL = """
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
values (%s, %s, %s, %s)
on conflict (tenant_code, alias_normalized) do update
    set unit_id = excluded.unit_id, alias = excluded.alias
returning unit_id
"""


def _row_to_unit(row: tuple[Any, ...], aliases: tuple[str, ...] = ()) -> Unit:
    return Unit(
        id=str(row[0]),
        name=str(row[1]),
        code=row[2],
        aliases=aliases,
        country=row[4] if len(row) > 4 else None,
        city=row[5] if len(row) > 5 else None,
    )


def resolve_unit_id(
    conn: psycopg.Connection[Any], name: str, *, tenant: str = DEFAULT_TENANT
) -> str | None:
    """Идентификатор точки по любому её написанию. Не нашлось — `None`.

    Сначала каноничное название, потом карта синонимов: если строка совпала с
    названием точки, спрашивать карту незачем, а обратный порядок дал бы
    синониму право перекрыть настоящее название чужой точки.

    Работает на переданном подключении: вызывается изнутри транзакции слива,
    и своё подключение здесь означало бы решение о точке, принятое вне той
    транзакции, которая её же и пишет.
    """
    tenant = canonical_tenant(tenant)
    key = normalize_unit_name(name)
    if not key:
        return None
    with conn.cursor() as cur:
        cur.execute(_RESOLVE_SQL, {"tenant": tenant, "key": key})
        row = cur.fetchone()
    return None if row is None else str(row[0])


def resolve_unit(name: str, *, tenant: str = DEFAULT_TENANT) -> Unit | None:
    """То же, но со своим подключением и полной карточкой точки."""
    tenant = canonical_tenant(tenant)
    settings = check_environment()
    key = normalize_unit_name(name)
    if not key:
        return None
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_RESOLVE_SQL, {"tenant": tenant, "key": key})
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "select alias from unit_aliases where unit_id = %s order by alias", (row[0],)
            )
            aliases = tuple(str(a[0]) for a in cur.fetchall())
    except psycopg.Error as exc:
        raise PushError(f"Справочник точек недоступен ({type(exc).__name__}): {exc}") from exc
    return _row_to_unit(row, aliases)


def list_units(*, reach: Reach, country: str | None = None) -> list[Unit]:
    """Справочник в охвате читающего с синонимами, целиком или одной страной.

    Справочник у сети один — у УК (D284): партнёр видит его точки своих стран,
    УК — все. Своих точек у партнёра нет, и заводить их продукт не даёт.

    `country` — код ISO 3166-1 alpha-2; регистр приводится здесь, потому что
    код приходит из адреса страницы и от человека, а в базе он лежит в одном
    виде. Точки без страны в страновой срез не попадают — и это верно: «страна
    не проставлена» не значит «страна эта».
    """
    охват = require_reach(reach)
    settings = check_environment()
    код = (country or "").strip().upper() or None
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_SELECT_UNITS_SQL, {**охват.params(), "country": код})
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise PushError(f"Справочник точек недоступен ({type(exc).__name__}): {exc}") from exc
    return [_row_to_unit(row, tuple(str(a) for a in row[3])) for row in rows]


def upsert_unit(
    name: str,
    *,
    code: str | None = None,
    aliases: tuple[str, ...] = (),
    country: str | None = None,
    city: str | None = None,
    tenant: str = DEFAULT_TENANT,
) -> str:
    """Завести или обновить точку справочника вместе с её синонимами.

    Повторяемо: та же точка с тем же кодом (а без кода — с тем же названием)
    не создаёт вторую строку, а обновляет существующую. Именно поэтому у точки
    есть код: повторная загрузка справочника из внешнего источника иначе
    опознавала бы уже заведённые точки по названию — по тому самому, от чего
    задача и уходит.

    Синоним, совпавший с каноничным названием точки, в карту не пишется: он
    там ничего не решает, а место занимает и путает читающего.

    Отказ — `PushError`: справочник ведётся тем же блоком и теми же правилами,
    что слив, и вызывающему не нужно знать про второй тип ошибки.
    """
    tenant = canonical_tenant(tenant)
    settings = check_environment()
    key = normalize_unit_name(name)
    if not key:
        raise PushError("У точки пустое название — в справочник её завести нечем")

    normalized_code = (code or "").strip() or None
    # Код страны приводится к одному виду на границе, а не проверяется на
    # принадлежность списку: список стран меняется, и своя копия запретила бы
    # новую страну ровно в день прихода сети в неё. Форму держит база
    # (`units_country_is_code`), и отказ там — это положенное вместо кода
    # название, то есть настоящая ошибка вызывающего.
    страна = (country or "").strip().upper() or None
    город = (city or "").strip() or None
    try:
        with psycopg.connect(settings.dsn) as conn:
            with conn.cursor() as cur:
                # Пространство не заводится точкой справочника: незаведённое —
                # отказ (#481).
                require_space(cur, tenant, error=PushError)
                sql = _UPSERT_UNIT_BY_CODE_SQL if normalized_code else _UPSERT_UNIT_BY_NAME_SQL
                cur.execute(
                    sql,
                    {
                        "tenant": tenant,
                        "name": name.strip(),
                        "key": key,
                        "code": normalized_code,
                        "country": страна,
                        "city": город,
                    },
                )
                row = cur.fetchone()
                if row is None:
                    raise PushError(
                        "Postgres не вернул точку после записи — целостность транзакции нарушена"
                    )
                unit_id = str(row[0])

                for alias in aliases:
                    alias_key = normalize_unit_name(alias)
                    if not alias_key or alias_key == key:
                        continue
                    cur.execute(
                        _UPSERT_ALIAS_SQL, (tenant, alias_key, UUID(unit_id), alias.strip())
                    )
            conn.commit()
    except PushError:
        raise
    except psycopg.Error as exc:
        raise PushError(
            f"Не удалось записать точку «{name}» в справочник ({type(exc).__name__}): {exc}"
        ) from exc
    return unit_id


def _existing(
    cur: psycopg.Cursor[Any], tenant: str, keys: tuple[str, ...]
) -> tuple[str, str] | None:
    """Точка, которую любое из написаний уже называет: `(id, имя)` или `None`."""
    for key in keys:
        cur.execute(_RESOLVE_SQL, {"tenant": tenant, "key": key})
        row = cur.fetchone()
        if row is not None:
            return str(row[0]), str(row[1])
    return None


def _insert_new(cur: psycopg.Cursor[Any], поля: dict[str, Any], alias_keys: tuple[str, ...]) -> str:
    """Вставить точку, если ни имя, ни синонимы ничего не называют; иначе — отказ."""
    tenant = str(поля["tenant"])
    занята = _existing(cur, tenant, (str(поля["key"]), *alias_keys))
    if занята is None:
        cur.execute(_INSERT_NEW_UNIT_SQL, поля)
        row = cur.fetchone()
        if row is not None:
            return str(row[0])
        # Ключ имени занял кто-то между сверкой и вставкой: тот же дубль.
        занята = _existing(cur, tenant, (str(поля["key"]),))
    if занята is None:
        raise PushError("Postgres не вставил точку и не нашёл занявшую её имя")
    raise UnitExistsError(
        f"Пиццерия «{занята[1]}» в справочнике уже есть", unit_id=занята[0], name=занята[1]
    )


def create_unit(
    name: str,
    *,
    country: str,
    city: str | None = None,
    aliases: tuple[str, ...] = (),
    tenant: str = DEFAULT_TENANT,
) -> str:
    """Завести НОВУЮ точку справочника; уже есть — `UnitExistsError` (#437).

    В отличие от `upsert_unit`, ничего существующего не трогает: имя или
    синоним, совпавшие с точкой справочника (название или синоним, тем же
    ключом, что сверка бота), — отказ с этой точкой. Сверка и запись идут в
    одной транзакции, а гонку двух одинаковых заведений закрывает уникальный
    ключ имени: вторая вставка ничего не вставляет и становится тем же отказом.

    Кто вправе заводить, здесь не решается — это `domain.tenants.may_add_units`
    у вызывающего; пространство обязано быть заведено (`require_space`).
    """
    tenant = canonical_tenant(tenant)
    key = normalize_unit_name(name)
    if not key:
        raise PushError("У точки пустое название — в справочник её завести нечем")
    синонимы: dict[str, str] = {}
    for alias in aliases:
        alias_key = normalize_unit_name(alias)
        if alias_key and alias_key != key:
            синонимы.setdefault(alias_key, alias.strip())
    поля = {
        "tenant": tenant,
        "name": name.strip(),
        "key": key,
        "country": (country or "").strip().upper() or None,
        "city": (city or "").strip() or None,
    }
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            with conn.cursor() as cur:
                require_space(cur, tenant, error=PushError)
                unit_id = _insert_new(cur, поля, tuple(синонимы))
                for alias_key, alias in синонимы.items():
                    cur.execute(_INSERT_NEW_ALIAS_SQL, (tenant, alias_key, UUID(unit_id), alias))
            conn.commit()
    except (PushError, UnitExistsError):
        raise
    except psycopg.Error as exc:
        raise PushError(
            f"Не удалось завести точку «{name}» в справочник ({type(exc).__name__}): {exc}"
        ) from exc
    return unit_id
