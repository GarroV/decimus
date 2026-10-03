"""Пространства и их страны — заводит команда проекта (D284, D287, волна 1 — #340).

Пространство — это строка `tenants`; страна партнёра — строка `space_countries`
(миграция 0029). Продукт ни того, ни другого не заводит: новое пространство —
новый заказчик, а не новый сотрудник, и пишет это роль владельца схемы
(`DATABASE_ADMIN_URL`) командой `make space`.

Правила, которые держит этот модуль, а не человек у консоли:

* код пространства — заглавная латиница, цифры, дефис и подчёркивание, от 2
  до 32 знаков. Код не меняется никогда: на нём держатся учётки, проверки и
  каталог методики (`checklist_layout.space_of` — код строчными);
* два кода, совпадающие без учёта регистра, — одно пространство: каталог
  методики у них был бы один;
* страна — один партнёр. Занятая страна — отказ с кодом того, у кого она;
* у УК стран нет: её охват — вся сеть (D283).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.tenants import HQ_TENANT, LEGACY_TENANTS, canonical_tenant

from .errors import AccessError
from .web_access import _connected, _owned

SPACE_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")

_SELECT_SPACE_SQL = "select 1 from tenants where code = %s"
_INSERT_SPACE_SQL = "insert into tenants (code, name) values (%s, %s)"
_LIST_SPACES_SQL = """
    select t.code, t.name,
           coalesce((select array_agg(c.country order by c.country)
                       from space_countries c where c.tenant_code = t.code), '{}'),
           (select count(*) from web_users u
             where u.tenant_code = t.code and u.disabled_at is null)
      from tenants t order by t.code
"""
_OWNER_OF_COUNTRY_SQL = "select tenant_code from space_countries where country = %s"
_BIND_COUNTRY_SQL = "insert into space_countries (country, tenant_code) values (%s, %s)"


@dataclass(frozen=True)
class SpaceRow:
    """Пространство для перечня: код, название, страны, живые учётки."""

    code: str
    name: str
    countries: tuple[str, ...]
    people: int


def check_space_code(code: str) -> str:
    """Годный код нового пространства — или отказ с правилом и примером."""
    значение = (code or "").strip()
    if not SPACE_CODE.match(значение) or значение in LEGACY_TENANTS:
        raise AccessError(
            f"Код пространства «{code}» не годится: заглавные латинские буквы, цифры, "
            f"дефис, подчёркивание, от 2 до 32 знаков (например «GE»). Код не меняется никогда"
        )
    return значение


def space_exists(code: str) -> bool:
    """Заведено ли пространство. Читает роль приложения: ей список дан (0004)."""
    with _connected("проверить пространство") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_SPACE_SQL, (canonical_tenant(code),))
        return cur.fetchone() is not None


def create_space(code: str, *, name: str) -> SpaceRow:
    """Завести пространство. Совпадение с заведённым без учёта регистра — отказ."""
    код = check_space_code(code)
    название = (name or "").strip()
    if код.lower() in {s.code.lower() for s in list_spaces()}:
        raise AccessError(
            f"Пространство «{код}» уже заведено (или совпадает с заведённым без учёта "
            f"регистра — каталог методики у них был бы один)"
        )
    with _owned(f"завести пространство «{код}»") as conn, conn.cursor() as cur:
        cur.execute(_INSERT_SPACE_SQL, (код, название))
    return SpaceRow(code=код, name=название, countries=(), people=0)


def list_spaces() -> tuple[SpaceRow, ...]:
    """Все пространства со странами и числом живых учёток."""
    with _owned("перечислить пространства") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SPACES_SQL)
        строки = cur.fetchall()
    return tuple(
        SpaceRow(code=str(r[0]), name=str(r[1]), countries=tuple(r[2]), people=int(r[3]))
        for r in строки
    )


def bind_countries(space: str, countries: tuple[str, ...]) -> tuple[str, ...]:
    """Привязать пространство партнёра к странам. Возвращает его страны после привязки.

    Всё или ничего: одна занятая страна в списке — отказ, и не привязывается ни
    одна. Уже привязанная к этому же пространству страна — не ошибка.
    """
    код = canonical_tenant(space)
    if код == HQ_TENANT or not space_exists(код):
        raise AccessError(
            f"К странам привязывается заведённое пространство партнёра, а не «{space}». "
            f"У УК стран нет: она видит всю сеть"
        )
    страны = tuple(dict.fromkeys(c.strip() for c in countries))
    if not страны:
        raise AccessError("Не названо ни одной страны")
    for страна in страны:
        if not COUNTRY_CODE.match(страна):
            raise AccessError(
                f"Код страны «{страна}» не годится: две заглавные буквы ISO, например GE"
            )
    with _owned(f"привязать «{код}» к странам") as conn, conn.cursor() as cur:
        for страна in страны:
            cur.execute(_OWNER_OF_COUNTRY_SQL, (страна,))
            чья = cur.fetchone()
            if чья is not None and чья[0] != код:
                raise AccessError(
                    f"Страна {страна} уже у пространства {чья[0]}: одна страна — один партнёр"
                )
            if чья is None:
                cur.execute(_BIND_COUNTRY_SQL, (страна, код))
    return next(s.countries for s in list_spaces() if s.code == код)
