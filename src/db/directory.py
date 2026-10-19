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

D538: поиск по написанию — ОДИН для всех дверей (`domain/unit_resolve.py`): бот,
мини-апп, MCP, админка, слив проверки и загрузки спрашивают `resolve_unit_id` /
`resolve_unit` здесь. Справочник читается целиком (сотни строк) и сверяется в
Python: ключ поиска (кириллица, армянский, пробелы, тире) в базе не хранится.
Снятая точка (`units.merged_into`, миграция 0078) в списках не показывается, а её
имя и id ведут на живую.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.domain.unit_match import Ref
from src.domain.unit_resolve import DirUnit, find_reference, find_unit

from .config import check_environment
from .errors import PushError, UnitExistsError
from .pool import connection
from .reach import Reach, require_reach
from .space_guard import require_space
from .units import normalize_unit_name

logger = logging.getLogger(__name__)

#: Арендатор по умолчанию — то же значение, что у `push.DEFAULT_TENANT` и у
#: `domain.state.DEFAULT_TENANT`. Импортировать чужую внутреннюю константу ради
#: одной строки дороже, чем закрепить значение тестом (так же сделано в push).
DEFAULT_TENANT = HQ_TENANT


@dataclass(frozen=True)
class CreatedUnit:
    """Заведённая точка и написания, которые синонимом не легли (#437)."""

    id: str
    #: Синонимы, чей ключ к моменту записи уже занят ДРУГОЙ точкой: точка
    #: заведена, а это написание по-прежнему ведёт к той, другой.
    taken_aliases: tuple[str, ...] = ()


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
  and u.merged_into is null
  and (%(country)s::text is null or u.country = %(country)s)
group by u.id, u.name, u.code, u.country, u.city
order by u.country nulls last, u.city nulls last, u.name
"""

# Справочник для поиска: все точки пространства, и снятые тоже — они ведут на живые.
_DIRECTORY_SQL = """
select u.id::text, u.name, u.merged_into::text, u.country is not null,
       coalesce(array_agg(a.alias order by a.alias) filter (where a.alias is not null), '{}')
from units u
left join unit_aliases a on a.unit_id = u.id
where u.tenant_code = %(tenant)s
group by u.id, u.name, u.merged_into, u.country
"""

# Справочник пиццерий — эталон имени (D538).
_REFERENCE_SQL = "select country_code, name, dodo_id, city, address from unit_profiles"

# Живая точка с таким именем — быстрый ход поиска, до чтения справочника целиком.
_LIVE_NAME_SQL = """
select name from units
where tenant_code = %(tenant)s and name_normalized = %(key)s and merged_into is null
"""

# Живая точка за идентификатором: сама или та, в которую влита.
_LIVE_ID_SQL = "select coalesce(merged_into, id)::text from units where id = %s"


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
insert into units (tenant_code, name, name_normalized, code, country, city)
values (%(tenant)s, %(name)s, %(key)s, %(code)s, %(country)s, %(city)s)
on conflict (tenant_code, name_normalized) do nothing
returning id
"""

# Точка, которая уже держит код Dodo: второй такой не заводится (`units_code_idx`).
_BY_CODE_SQL = "select id::text, name, country from units where tenant_code = %s and code = %s"

_INSERT_NEW_ALIAS_SQL = """
insert into unit_aliases (tenant_code, alias_normalized, unit_id, alias)
values (%s, %s, %s, %s)
on conflict (tenant_code, alias_normalized) do nothing
returning unit_id
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


def load_directory(
    conn: psycopg.Connection[Any], *, tenant: str = DEFAULT_TENANT
) -> tuple[DirUnit, ...]:
    """Все точки пространства для поиска по написанию, снятые тоже. Читает на данном подключении."""
    with conn.cursor() as cur:
        cur.execute(_DIRECTORY_SQL, {"tenant": canonical_tenant(tenant)})
        rows = cur.fetchall()
    return tuple(
        DirUnit(
            id=str(r[0]),
            name=str(r[1]),
            aliases=tuple(str(a) for a in r[4]),
            merged_into=None if r[2] is None else str(r[2]),
            anchored=bool(r[3]),
        )
        for r in rows
    )


def reference_refs(conn: psycopg.Connection[Any]) -> tuple[Ref, ...]:
    """Справочник пиццерий (`unit_profiles`) — эталон имени, на данном подключении (D538)."""
    with conn.cursor() as cur:
        cur.execute(_REFERENCE_SQL)
        return tuple(
            Ref(r[0], r[1], r[2] or None, r[3] or None, r[4] or None) for r in cur.fetchall()
        )


def resolve_unit_id(
    conn: psycopg.Connection[Any], name: str, *, tenant: str = DEFAULT_TENANT
) -> str | None:
    """Идентификатор ЖИВОЙ точки по любому её написанию. Не нашлось — `None`.

    Один поиск на все двери (`domain.unit_resolve.find_unit`, D538): регистр, пробелы,
    тире и алфавит не различаются, имя точки сильнее синонима, а имя снятой точки
    ведёт на ту, в которую она влита. Подошло несколько разных точек — `None`: угадать
    не значит найти.

    Работает на переданном подключении: вызывается изнутри транзакции слива,
    и своё подключение здесь означало бы решение о точке, принятое вне той
    транзакции, которая её же и пишет.
    """
    if not name.strip():
        return None
    found = find_unit(load_directory(conn, tenant=tenant), name).unit
    return None if found is None else found.id


def canonical_unit_name(
    conn: psycopg.Connection[Any], typed: str, *, tenant: str = DEFAULT_TENANT
) -> str | None:
    """Имя живой точки по любому написанию («Тбилиси-1» → «Tbilisi-1»); не нашлась — `None`."""
    key = normalize_unit_name(typed)
    if not key:
        return None
    # Точное имя живой точки — самый частый случай (MCP обходит точки по их же именам):
    # справочник целиком ради него не читается.
    with conn.cursor() as cur:
        cur.execute(_LIVE_NAME_SQL, {"tenant": canonical_tenant(tenant), "key": key})
        row = cur.fetchone()
    if row is not None:
        return str(row[0])
    found = find_unit(load_directory(conn, tenant=tenant), typed).unit
    return None if found is None else found.name


def live_unit_id(conn: psycopg.Connection[Any], unit_id: str) -> str | None:
    """Живая точка за идентификатором: он сам или точка, в которую он влит. Нет такой — `None`."""
    try:
        UUID(unit_id)
    except ValueError:
        return None
    with conn.cursor() as cur:
        cur.execute(_LIVE_ID_SQL, (unit_id,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def redirect_target(unit_id: str) -> str | None:
    """Точка, в которую влита снятая `unit_id`; живая или неизвестная — `None`."""
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn:
            live = live_unit_id(conn, unit_id)
    except psycopg.Error as exc:
        raise PushError(f"Справочник точек недоступен ({type(exc).__name__}): {exc}") from exc
    return live if live is not None and live != unit_id else None


def resolve_unit(name: str, *, tenant: str = DEFAULT_TENANT) -> Unit | None:
    """То же, но со своим подключением и полной карточкой живой точки."""
    tenant = canonical_tenant(tenant)
    settings = check_environment()
    if not name.strip():
        return None
    try:
        with connection(settings.dsn) as conn:
            unit_id = resolve_unit_id(conn, name, tenant=tenant)
            if unit_id is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    "select id, name, code, null, country, city from units where id = %s",
                    (unit_id,),
                )
                row = cur.fetchone()
                cur.execute(
                    "select alias from unit_aliases where unit_id = %s order by alias", (unit_id,)
                )
                aliases = tuple(str(a[0]) for a in cur.fetchall())
    except psycopg.Error as exc:
        raise PushError(f"Справочник точек недоступен ({type(exc).__name__}): {exc}") from exc
    return None if row is None else _row_to_unit(row, aliases)


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
        with connection(settings.dsn) as conn, conn.cursor() as cur:
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
        with connection(settings.dsn) as conn:
            with conn.cursor() as cur:
                # Пространство не заводится точкой справочника: незаведённое —
                # отказ (#481).
                require_space(cur, tenant, error=PushError)
                if not normalized_code:
                    # D538: набранное имя — не всегда имя точки. Она уже есть под другим
                    # написанием — обновляется она; справочник пиццерий знает строку —
                    # точка ложится под его именем и кодом. Набранное остаётся синонимом.
                    name, key, normalized_code, aliases, страна = _canonical_target(
                        conn, name, key, aliases, страна, tenant
                    )
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


def _canonical_target(
    conn: psycopg.Connection[Any],
    name: str,
    key: str,
    aliases: tuple[str, ...],
    country: str | None,
    tenant: str,
) -> tuple[str, str, str | None, tuple[str, ...], str | None]:
    """Под каким именем и кодом писать точку, названную `name` без кода (D538).

    Возвращает `(имя, ключ, код, синонимы, страна)`. Нашлась живая точка — пишем в неё под
    её именем; нет, но справочник пиццерий знает строку — под его именем и кодом (если код
    держит другая точка, это она: пишем в неё). Ничего не знаем — имя как набрано.
    """
    typed = name.strip()
    found = find_unit(load_directory(conn, tenant=tenant), name).unit
    if found is not None:
        return found.name, normalize_unit_name(found.name), None, (*aliases, typed), country
    ref = find_reference(name, reference_refs(conn), country=country)
    if ref is None:
        return name, key, None, aliases, country
    owner = None
    if ref.dodo_id:
        with conn.cursor() as cur:
            cur.execute(_BY_CODE_SQL, (tenant, ref.dodo_id))
            owner = cur.fetchone()
    if owner is not None:
        return str(owner[1]), normalize_unit_name(str(owner[1])), None, (*aliases, typed), country
    return (
        ref.clean_name,
        normalize_unit_name(ref.clean_name),
        ref.dodo_id,
        (*aliases, typed),
        country or ref.country,
    )


def insert_typed_unit(
    conn: psycopg.Connection[Any], typed: str, *, tenant: str = DEFAULT_TENANT
) -> str:
    """Завести точку по названию из файла проверки, которого справочник не знает (D538).

    Зовётся слив проверки УК после неудачного `resolve_unit_id`. Справочник пиццерий
    знает строку — точка ложится под его латинским именем и кодом Dodo, а написанное
    остаётся синонимом; не знает — под написанным, как и раньше: справочник может быть
    не заполнен, и это не повод отказать в сливе. Пишет на данном подключении, в его
    транзакции.
    """
    tenant = canonical_tenant(tenant)
    key = normalize_unit_name(typed)
    name, key, code, aliases, country = _canonical_target(conn, typed, key, (), None, tenant)
    sql = _UPSERT_UNIT_BY_CODE_SQL if code else _UPSERT_UNIT_BY_NAME_SQL
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "tenant": tenant,
                "name": name.strip(),
                "key": key,
                "code": code,
                "country": country,
                "city": None,
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
            if alias_key and alias_key != key:
                cur.execute(_UPSERT_ALIAS_SQL, (tenant, alias_key, UUID(unit_id), alias.strip()))
    return unit_id


def _existing(
    cur: psycopg.Cursor[Any], tenant: str, spellings: tuple[str, ...]
) -> tuple[str, str, str | None] | None:
    """Живая точка, которую любое из написаний уже называет: `(id, имя, страна)` или `None`.

    Поиск тот же, что у всех дверей (`find_unit`, D538): «Тбилиси-1» занято, если есть
    «Tbilisi-1», а имя снятой точки называет ту, в которую она влита.
    """
    found = find_unit(load_directory(cur.connection, tenant=tenant), *spellings).unit
    if found is None:
        return None
    cur.execute("select country from units where id = %s", (found.id,))
    страна = cur.fetchone()
    return found.id, found.name, (None if страна is None else страна[0])


def _insert_new(
    cur: psycopg.Cursor[Any], поля: dict[str, Any], alias_texts: tuple[str, ...]
) -> str:
    """Вставить точку, если ни имя, ни синонимы ничего не называют; иначе — отказ."""
    tenant = str(поля["tenant"])
    занята = _existing(cur, tenant, (str(поля["name"]), *alias_texts))
    if занята is None and поля.get("code"):
        cur.execute(_BY_CODE_SQL, (tenant, поля["code"]))
        по_коду = cur.fetchone()
        if по_коду is not None:
            занята = (str(по_коду[0]), str(по_коду[1]), по_коду[2])
    if занята is None:
        cur.execute(_INSERT_NEW_UNIT_SQL, поля)
        row = cur.fetchone()
        if row is not None:
            return str(row[0])
        # Ключ имени занял кто-то между сверкой и вставкой: тот же дубль.
        занята = _existing(cur, tenant, (str(поля["name"]),))
    if занята is None:
        raise PushError("Postgres не вставил точку и не нашёл занявшую её имя")
    raise UnitExistsError(
        f"Пиццерия «{занята[1]}» в справочнике уже есть",
        unit_id=занята[0],
        name=занята[1],
        country=занята[2],
    )


def create_unit(
    name: str,
    *,
    country: str,
    city: str | None = None,
    aliases: tuple[str, ...] = (),
    code: str | None = None,
    tenant: str = DEFAULT_TENANT,
) -> CreatedUnit:
    """Завести НОВУЮ точку справочника; уже есть — `UnitExistsError` (#437).

    В отличие от `upsert_unit`, ничего существующего не трогает: имя или
    синоним, совпавшие с точкой справочника (название или синоним, тем же
    ключом, что сверка бота и любая другая дверь, `find_unit`), — отказ с этой
    точкой. Код Dodo, уже занятый другой точкой, — тот же отказ. Сверка и запись идут в
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
        "code": (code or "").strip() or None,
        "country": (country or "").strip().upper() or None,
        "city": (city or "").strip() or None,
    }
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn:
            with conn.cursor() as cur:
                require_space(cur, tenant, error=PushError)
                unit_id = _insert_new(cur, поля, tuple(синонимы.values()))
                занятые: list[str] = []
                for alias_key, alias in синонимы.items():
                    cur.execute(_INSERT_NEW_ALIAS_SQL, (tenant, alias_key, UUID(unit_id), alias))
                    if cur.fetchone() is None:
                        # Ключ занял другой между сверкой и записью. Точку не
                        # откатываем — она заведена верно, — но и не молчим.
                        занятые.append(alias)
            conn.commit()
    except (PushError, UnitExistsError):
        raise
    except psycopg.Error as exc:
        raise PushError(
            f"Не удалось завести точку «{name}» в справочник ({type(exc).__name__}): {exc}"
        ) from exc
    if занятые:
        logger.warning(
            "точка %s заведена, но синонимы заняты другой точкой: %s", name, ", ".join(занятые)
        )
    return CreatedUnit(id=unit_id, taken_aliases=tuple(занятые))
