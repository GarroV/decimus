"""Кто кого ведёт на экране «Пользователи» (#585, D362, D364) — одно правило на экран.

Экран один для всех, охват — по роли вошедшего:

* **главный админ** (`superadmin`, только УК) — все люди всех пространств с любой
  ролью, включая других главных админов; пространства партнёров и их страны;
* **админ УК** (`admin` в УК) — люди УК, кроме админов и главных админов
  (аудиторы и контроль), и все люди партнёров; пространства партнёров и их
  страны. Админа УК и главного админа он не заводит, не повышает до них и не
  трогает;
* **контроль** (`control`, D360) — только люди контролинга в УК;
* **админ партнёра** (`admin` в пространстве партнёра, D346) — люди своего
  пространства: админы и сотрудники (`auditor`). Свои страны видит на чтение;
* остальные (аудитор УК, сотрудник партнёра) — никого, только себя.

Правило здесь, а не в маршрутах и не в разметке, потому что вопрос «можно ли» у
списка, у формы и у каждого POST один: видимое = трогаемое, и разойтись они не
могут. Маршрут сверяет цель по базе, а не по форме; атомарный заслон на
запись — условие на роль цели в самом запросе (`only_roles` у дверей базы).
Последнего главного админа держит база (`0041`), не это правило.

Свою роль не меняет никто и себя не отключает никто — это решает маршрут
(`people.is_self`), потому что зависит от вошедшего, а не от охвата.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from src.domain.tenants import CONTROL_ROLE, HQ_TENANT, SUPERADMIN_ROLE, canonical_tenant

from .accounts import ROLE_ADMIN, ROLE_AUDITOR, roles_for

#: Виды охвата: кто вошёл с точки зрения экрана людей.
SUPER = "super"
HQ_ADMIN = "hq_admin"
CONTROL = "control"
PARTNER_ADMIN = "partner_admin"

#: Роли людей УК, которых ведёт админ УК: всё, кроме админов (D364).
_HQ_ADMIN_TOUCHES_IN_HQ = frozenset({ROLE_AUDITOR, CONTROL_ROLE})
#: Роли людей партнёра (D346): админ пространства и сотрудник.
_PARTNER_ROLES = frozenset({ROLE_ADMIN, ROLE_AUDITOR})


class _Row(Protocol):
    @property
    def tenant(self) -> str: ...

    @property
    def role(self) -> str: ...


@dataclass(frozen=True)
class Scope:
    """Охват вошедшего: вид и его пространство (код приведён)."""

    kind: str
    tenant: str


def scope_of(role: str | None, tenant: str | None) -> Scope | None:
    """Охват по роли и пространству вошедшего; `None` — людьми не управляет."""
    своё = canonical_tenant(tenant or "")
    в_уК = своё == HQ_TENANT
    if role == SUPERADMIN_ROLE and в_уК:
        return Scope(SUPER, своё)
    if role == ROLE_ADMIN and в_уК:
        return Scope(HQ_ADMIN, своё)
    if role == CONTROL_ROLE and в_уК:
        return Scope(CONTROL, своё)
    if role == ROLE_ADMIN and своё:
        return Scope(PARTNER_ADMIN, своё)
    return None


def may_touch(scope: Scope, *, tenant: str, role: str) -> bool:
    """Можно ли трогать учётку с этой НЫНЕШНЕЙ ролью в этом пространстве."""
    где = canonical_tenant(tenant)
    if role not in roles_for(где):
        return False
    if scope.kind == SUPER:
        return True
    if scope.kind == HQ_ADMIN:
        if где == HQ_TENANT:
            return role in _HQ_ADMIN_TOUCHES_IN_HQ
        return role in _PARTNER_ROLES
    if scope.kind == CONTROL:
        return где == HQ_TENANT and role == CONTROL_ROLE
    if scope.kind == PARTNER_ADMIN:
        return где == scope.tenant and role in _PARTNER_ROLES
    return False


def may_grant(scope: Scope, *, tenant: str, role: str) -> bool:
    """Можно ли выдать эту роль в этом пространстве (заведение или смена роли).

    Совпадает с `may_touch`: кого нельзя трогать, того нельзя и создать, —
    иначе админ УК заводил бы админов, которых потом сам не видит.
    """
    return may_touch(scope, tenant=tenant, role=role)


def grantable_roles(scope: Scope, tenant: str) -> tuple[str, ...]:
    """Роли для формы в этом пространстве — в порядке `roles_for`."""
    return tuple(r for r in roles_for(tenant) if may_grant(scope, tenant=tenant, role=r))


def visible[R: _Row](scope: Scope, rows: Iterable[R]) -> tuple[R, ...]:
    """Строки перечня, которые вошедшему показывать: ровно те, которых он может трогать."""
    return tuple(r for r in rows if may_touch(scope, tenant=r.tenant, role=r.role))


def manages_spaces(scope: Scope) -> bool:
    """Заводить пространства партнёров и привязывать их к странам (D364)."""
    return scope.kind in (SUPER, HQ_ADMIN)


def spaces_for_add(scope: Scope, spaces: tuple[str, ...]) -> tuple[str, ...]:
    """Пространства формы заведения: те, где вошедший может выдать хоть одну роль."""
    return tuple(s for s in spaces if grantable_roles(scope, s))
