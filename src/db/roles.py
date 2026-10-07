# src/db/roles.py
"""Роли и их права — чтение ролью приложения (спека «Администрирование», `0038`).

Здесь же — единственный подзапрос «права роли одной колонкой» и его разбор: их
зовут SQL опознания веба (`web_access`) и бота (`bot_links`, Task 13). Три копии
подзапроса разошлись бы на первой правке схемы прав.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.domain.permissions import Grants

from .reading import reading


def grants_column(role_expr: str) -> str:
    """Подзапрос «права роли `role_expr` одной колонкой jsonb» (код действия → охват).

    `role_expr` — выражение SQL из кода модуля (`"u.role"`, `"r.code"`), не ввод
    человека: в текст запроса он попадает как есть.
    """
    return (
        "(select coalesce(jsonb_object_agg(p.action_code, p.reach), '{}'::jsonb) "  # noqa: S608
        f"from role_permissions p where p.role_code = {role_expr})"
    )


def grants_from_row(value: object) -> Grants:
    """Колонка `grants_column` → права роли. Не словарь — ошибка схемы, а не «прав нет»."""
    if not isinstance(value, Mapping):
        raise TypeError(f"Права роли ожидались объектом jsonb, пришло {type(value).__name__}")
    return MappingProxyType({str(код): str(охват) for код, охват in value.items()})


_LIST_SQL = f"""
    select r.code, r.scope, r.name_ru, r.name_en, {grants_column("r.code")}
      from roles r
     order by r.scope, r.code
"""  # noqa: S608 — подзапрос собран из константы модуля

_GRANTS_SQL = "select action_code, reach from role_permissions where role_code = %s"


@dataclass(frozen=True)
class Role:
    """Роль так, как её показывают и проверяют: код, охват, подписи, права."""

    code: str
    scope: str
    name_ru: str
    name_en: str
    grants: Grants


def list_roles() -> tuple[Role, ...]:
    """Все роли с правами — для выбора роли на экране людей."""
    with reading("роли") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL)
        return tuple(
            Role(str(r[0]), str(r[1]), str(r[2]), str(r[3]), grants_from_row(r[4]))
            for r in cur.fetchall()
        )


def grants_of(role_code: str) -> Grants:
    """Права роли. Незаведённая роль — пусто: закрыто по умолчанию."""
    with reading("права роли") as conn, conn.cursor() as cur:
        cur.execute(_GRANTS_SQL, (role_code,))
        return MappingProxyType({str(код): str(охват) for код, охват in cur.fetchall()})
