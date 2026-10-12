"""Вид экрана «Пользователи»: названия ролей, фильтры, выбор человека, адреса.

Здесь нет ни одного решения о правах: кого показывать и что разрешать, решает
`access_policy.py` до того, как строки попадают сюда. Этот модуль только сужает
уже разрешённый перечень по фильтрам вошедшего и собирает адреса экрана.

Экран — «слева список, справа настройки» (образец — Swarm Brain, раздел
коннекторов, решение владельца 30.09.2026). Выбранный человек, открытая форма
добавления и фильтры живут в адресе (`?person=…&q=…`): выбор переживает
перезагрузку и работает без скриптов.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from src.domain.tenants import HQ_TENANT, canonical_tenant

#: Длина строки поиска: дальше ввод обрезается, а не роняет страницу.
_MAX_QUERY = 80

#: Вкладки экрана: люди и пространства партнёров (D364).
TAB_PEOPLE = "people"
TAB_SPACES = "spaces"


class _Row(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def login(self) -> str: ...

    @property
    def tenant(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def email(self) -> str | None: ...

    @property
    def disabled_at(self) -> object | None: ...


def is_partner(tenant: str) -> bool:
    """Пространство партнёра, а не УК: у его людей свои названия ролей (D346)."""
    return canonical_tenant(tenant) != HQ_TENANT


def role_key(role: str, tenant: str) -> str:
    """Ключ названия роли: «Аудитор» в УК — «Сотрудник» у партнёра."""
    return f"users.role.partner.{role}" if is_partner(tenant) else f"users.role.{role}"


def hint_key(role: str, tenant: str) -> str:
    """Ключ строки «что роль может» — под названием роли в форме и в панели."""
    return f"users.hint.partner.{role}" if is_partner(tenant) else f"users.hint.{role}"


@dataclass(frozen=True)
class Filters:
    """Фильтры списка людей, как их прислал адрес. Пустое — «все»."""

    q: str = ""
    space: str = ""
    role: str = ""
    off: bool = False

    @property
    def active(self) -> bool:
        """Сужает ли что-нибудь список (для кнопки «Сбросить»)."""
        return bool(self.q or self.space or self.role or self.off)

    def params(self) -> dict[str, str]:
        """Непустые фильтры — для адресов экрана."""
        пары = {"q": self.q, "space": self.space, "role": self.role, "off": "1" if self.off else ""}
        return {k: v for k, v in пары.items() if v}


def read_filters(args: Mapping[str, str]) -> Filters:
    """Фильтры из адреса. Это ввод снаружи: обрезается и приводится, но не роняет."""
    return Filters(
        q=(args.get("q") or "").strip()[:_MAX_QUERY],
        space=canonical_tenant((args.get("space") or "").strip()) if args.get("space") else "",
        role=(args.get("role") or "").strip()[:_MAX_QUERY],
        off=(args.get("off") or "") == "1",
    )


def apply_filters[R: _Row](rows: Iterable[R], f: Filters) -> tuple[R, ...]:
    """Строки, которые проходят фильтры. Отключённые — только по `off`."""
    искомое = f.q.casefold()
    return tuple(
        r
        for r in rows
        if (f.off or r.disabled_at is None)
        and (not f.space or canonical_tenant(r.tenant) == f.space)
        and (not f.role or r.role == f.role)
        and (not искомое or искомое in r.login.casefold() or искомое in (r.email or "").casefold())
    )


@dataclass(frozen=True)
class RoleOption:
    """Пункт фильтра ролей: код и ключ подписи."""

    code: str
    label_key: str


def role_options(rows: Iterable[_Row]) -> tuple[RoleOption, ...]:
    """Роли, которые есть среди видимых людей, — для фильтра.

    Код `auditor` в УК и у партнёра называется по-разному; если в списке есть
    оба, пункт один — «Аудитор или сотрудник».
    """
    где: dict[str, set[bool]] = {}
    for r in rows:
        где.setdefault(r.role, set()).add(is_partner(r.tenant))
    пункты = []
    for код, партнёр in где.items():
        if len(партнёр) > 1:
            подпись = "users.filter.auditor_any" if код == "auditor" else f"users.role.{код}"
        else:
            подпись = f"users.role.partner.{код}" if True in партнёр else f"users.role.{код}"
        пункты.append(RoleOption(код, подпись))
    return tuple(sorted(пункты, key=lambda p: _ROLE_ORDER.get(p.code, len(_ROLE_ORDER))))


#: Порядок ролей в фильтре: сверху самые широкие.
_ROLE_ORDER = {"superadmin": 0, "admin": 1, "control": 2, "auditor": 3}


def selected[R: _Row](rows: Iterable[R], person_id: str) -> R | None:
    """Выбранный человек — только из уже разрешённого перечня; чужой ключ — `None`."""
    if not person_id:
        return None
    return next((r for r in rows if r.id == person_id), None)


def screen_url(base: str, *, lang: str, f: Filters, **extra: str) -> str:
    """Адрес экрана с фильтрами вошедшего и выбором (`person`, `add`, `tab`, `space_code`)."""
    язык = {"lang": lang} if lang else {}
    пары = {**язык, **f.params(), **{k: v for k, v in extra.items() if v}}
    return f"{base}?{urlencode(пары)}"
