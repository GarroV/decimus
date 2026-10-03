"""Охват чтения: что видит пространство (волна 1, #340; D283, D284, D289).

УК делает эталоны и читает всю сеть. Партнёр читает пиццерии своих стран — кто
бы их ни проверял (D289). Запись охватом не расширяется: пишет каждый только в
своё пространство, и функции записи принимают `tenant`, а не `Reach`.

Охват уходит в запрос параметрами-массивами, а текст запроса не меняется
(правило S608). `None` в массиве — «без ограничения», пустой массив — «ничего».

Условия ниже вписаны в текст каждого запроса ЛИТЕРАЛОМ, а не склейкой: сверку
«везде ли оно есть и везде ли одно и то же» делает
`tests/test_db_reach_static.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .errors import DbError
from .reading import reading

#: Условие охвата для запроса по проверкам: `i` — проверка, `u` — её точка.
REACH_SQL = (
    "(%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) "
    "and (%(countries)s::text[] is null or u.country = any(%(countries)s))"
)

#: Условие охвата для запроса по справочнику: справочник один, и он у УК (D284).
UNIT_REACH_SQL = (
    "u.tenant_code = 'HQ' and (%(countries)s::text[] is null or u.country = any(%(countries)s))"
)

_COUNTRIES_SQL = "select country from space_countries where tenant_code = %s order by country"


@dataclass(frozen=True)
class Reach:
    """Кто читает (`tenant`), чьи проверки (`tenants`), пиццерии каких стран (`countries`).

    `None` — без ограничения по этому измерению, пустой кортеж — ничего.
    """

    tenant: str
    tenants: tuple[str, ...] | None
    countries: tuple[str, ...] | None

    def params(self) -> dict[str, list[str] | None]:
        """Параметры запроса: массивы, а не текст условия."""
        return {
            "tenants": None if self.tenants is None else list(self.tenants),
            "countries": None if self.countries is None else list(self.countries),
        }


def require_reach(reach: Reach) -> Reach:
    """Охват чтения — или явный отказ (#340).

    Без охвата выборка отдала бы либо всю сеть, либо пустоту вместо ошибки —
    оба исхода тихие, тот же довод, что у прежнего обязательного арендатора
    (T110). Строка вместо охвата — ошибка вызывающего, пропущенная до волны.
    """
    if not isinstance(reach, Reach) or not canonical_tenant(reach.tenant or ""):
        raise DbError(
            "Не задан охват чтения — пространство (арендатор), чьи проверки и каких "
            "стран читаем. Выборка без него отдала бы либо чужие проверки, либо "
            "пустоту вместо ошибки"
        )
    return reach


def own_reach(tenant: str) -> Reach:
    """Только свои проверки тенанта, справочник — без сужения по стране.

    Прежняя граница «один тенант» в новой форме. Нужна тестам изоляции партнёров
    друг от друга и поверхностям, которые до задач 6 и 12 читают по тенанту
    стенда (мост: список мест — в отчёте задачи 5).
    """
    код = canonical_tenant(tenant)
    return Reach(tenant=код, tenants=(код,), countries=None)


def countries_of(tenant: str) -> tuple[str, ...]:
    """Страны пространства из `space_countries`, по алфавиту. У УК строк нет."""
    with reading("страны пространства") as conn, conn.cursor() as cur:
        cur.execute(_COUNTRIES_SQL, (canonical_tenant(tenant),))
        return tuple(str(row[0]) for row in cur.fetchall())


def reach_of(tenant: str) -> Reach:
    """Охват пространства. Партнёр без стран не видит ничего — закрыто по умолчанию."""
    код = canonical_tenant(tenant)
    if код == HQ_TENANT:
        return Reach(tenant=код, tenants=None, countries=None)
    return Reach(tenant=код, tenants=None, countries=countries_of(код))
