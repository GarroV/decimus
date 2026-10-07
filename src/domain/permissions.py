"""Каталог действий и проверка прав `can` (спека «Администрирование», D304, D306, D307, D311).

Решение принимается двумя слоями, и отказ первого второй не переопределяет:

1. **Граница** (код, не настраивается): человек УК действует в любом
   пространстве; человек страны — только в своём; объект УК страна не меняет
   никогда; действия «только УК» роли страны не выдаются никаким правом.
2. **Матрица** (настраивает админ УК): есть ли у роли право и с каким охватом.
   У действий над проверкой охват — «свои» (`own`: проверку занесла учётка
   этого человека) или «все» (`all`); у остальных — только `all`.

Код действия — ключ, подписи переводятся отдельно. Новая пишущая операция
получает код здесь в момент появления: это часть её готовности.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .tenants import HQ_TENANT, canonical_tenant


@dataclass(frozen=True)
class Action:
    """Одна пишущая операция каталога."""

    code: str
    group: str
    #: Действие только УК: роли страны не выдаётся никаким правом (слой 1).
    hq_only: bool = False
    #: Объект — конкретная проверка: право несёт охват «свои/все» (D311).
    on_inspection: bool = False


ACTIONS: tuple[Action, ...] = (
    Action("inspection.conduct", "inspection"),
    Action("inspection.retract", "inspection", on_inspection=True),
    Action("inspection.move", "inspection", on_inspection=True),
    Action("inspection.accept", "inspection", on_inspection=True),
    Action("inspection.revise", "inspection", on_inspection=True),
    Action("inspection.letter", "inspection", on_inspection=True),
    Action("prescription.manage", "prescription"),
    Action("prescription.reply", "prescription"),
    Action("plan.manage", "plan"),
    Action("plan.submit", "plan"),
    Action("checklist.edit", "checklist"),
    Action("checklist.publish", "checklist"),
    Action("checklist.manage", "checklist"),
    Action("phrases.manage", "phrases"),
    Action("people.manage", "people"),
    Action("mcp.connect", "mcp"),
    Action("unit.create", "unit", hq_only=True),
    Action("space.manage", "space", hq_only=True),
    Action("roles.manage", "roles", hq_only=True),
)

ACTION_CODES: frozenset[str] = frozenset(a.code for a in ACTIONS)
HQ_ONLY_ACTIONS: frozenset[str] = frozenset(a.code for a in ACTIONS if a.hq_only)
INSPECTION_OBJECT_ACTIONS: frozenset[str] = frozenset(a.code for a in ACTIONS if a.on_inspection)
_BY_CODE: Mapping[str, Action] = {a.code: a for a in ACTIONS}

REACH_OWN = "own"
REACH_ALL = "all"

#: Права роли: код действия → охват. Нет ключа — нет права.
Grants = Mapping[str, str]

RULE_OK = "ok"
RULE_MATRIX = "matrix"
RULE_HQ_ONLY = "hq_only"
RULE_HQ_OBJECT = "hq_object"
RULE_FOREIGN_SPACE = "foreign_space"
RULE_NOT_AUTHOR = "not_author"


class UnknownAction(ValueError):
    """Код действия не из каталога — ошибка кода, а не отказ человеку."""


def require_action(code: str) -> Action:
    """Действие каталога по коду. Единственная проверка кода на весь проект."""
    действие = _BY_CODE.get(code)
    if действие is None:
        raise UnknownAction(f"Действия «{code}» нет в каталоге src/domain/permissions.py")
    return действие


class AuthorNotGiven:
    """Метка «автора объекта не передали» — отличается от `None` («автор неизвестен»)."""


AUTHOR_NOT_GIVEN = AuthorNotGiven()


@dataclass(frozen=True)
class Actor:
    """Кто действует: пространство, роль и права роли на момент запроса."""

    tenant: str
    #: Код роли; `None` — права не из роли (мост MCP до блока 3).
    role: str | None
    grants: Grants
    #: Учётка веба: по ней опознаются «свои» проверки и пишется журнал.
    user_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """Ответ `can`: можно ли и каким правилом это решено."""

    allowed: bool
    rule: str

    def __bool__(self) -> bool:
        return self.allowed


def _required_tenant(code: str, *, what: str) -> str:
    приведённый = canonical_tenant(code or "")
    if not приведённый:
        raise ValueError(f"Не задано {what}: без него граница пространств не решается")
    return приведённый


def _boundary(кто: str, action: str, чьё: str) -> str | None:
    """Слой 1: правило отказа границы или `None`, если граница пропускает."""
    if кто == HQ_TENANT:
        return None
    if action in HQ_ONLY_ACTIONS:
        return RULE_HQ_ONLY
    if чьё == HQ_TENANT:
        return RULE_HQ_OBJECT
    if чьё != кто:
        return RULE_FOREIGN_SPACE
    return None


def can(
    actor: Actor,
    action: str,
    object_tenant: str,
    *,
    object_author: str | AuthorNotGiven | None = AUTHOR_NOT_GIVEN,
) -> Decision:
    """Может ли `actor` сделать `action` над объектом пространства `object_tenant`.

    У действия над проверкой `object_author` обязателен: учётка, занёсшая
    проверку, или `None`, если она неизвестна. Забытый автор — ошибка кода:
    молча считать его «чужим» значило бы прятать пропуск в отказах людям.
    """
    require_action(action)
    if action in INSPECTION_OBJECT_ACTIONS and isinstance(object_author, AuthorNotGiven):
        raise ValueError(f"«{action}» — действие над проверкой: передайте автора объекта")
    кто = _required_tenant(actor.tenant, what="пространство человека")
    чьё = _required_tenant(object_tenant, what="пространство объекта")
    отказ_границы = _boundary(кто, action, чьё)
    if отказ_границы is not None:
        return Decision(False, отказ_границы)
    охват = actor.grants.get(action)
    if охват == REACH_ALL:
        return Decision(True, RULE_OK)
    if охват == REACH_OWN and action in INSPECTION_OBJECT_ACTIONS:
        свой = bool(actor.user_id) and object_author == actor.user_id
        return Decision(True, RULE_OK) if свой else Decision(False, RULE_NOT_AUTHOR)
    return Decision(False, RULE_MATRIX)


SCOPE_HQ = "hq"
SCOPE_COUNTRY = "country"

ROLE_HQ_ADMIN = "hq_admin"
ROLE_HQ_STAFF = "hq_staff"
ROLE_COUNTRY_ADMIN = "country_admin"
ROLE_COUNTRY_STAFF = "country_staff"

#: Охват ролей по умолчанию. Заведённые админом УК роли (блок 2) несут охват в
#: строке `roles.scope`, а не здесь.
ROLE_SCOPES: Mapping[str, str] = {
    ROLE_HQ_ADMIN: SCOPE_HQ,
    ROLE_HQ_STAFF: SCOPE_HQ,
    ROLE_COUNTRY_ADMIN: SCOPE_COUNTRY,
    ROLE_COUNTRY_STAFF: SCOPE_COUNTRY,
}


def _all(codes: frozenset[str]) -> dict[str, str]:
    return {код: REACH_ALL for код in codes}


#: Сотрудник правит только проверки, которые занёс сам (D311).
_OWN_INSPECTIONS: Mapping[str, str] = {код: REACH_OWN for код in INSPECTION_OBJECT_ACTIONS}

#: Права по умолчанию — таблица спеки с поправками D310 (`unit.create` у
#: `hq_staff`) и D311 (охват «свои» у сотрудников). Засев `0038` сверяется с
#: ней тестом (`tests/test_db_roles_migration.py`), а не копируется руками.
DEFAULT_MATRIX: Mapping[str, Grants] = {
    ROLE_HQ_ADMIN: _all(ACTION_CODES),
    ROLE_HQ_STAFF: {
        **_all(ACTION_CODES - {"people.manage", "space.manage", "roles.manage"}),
        **_OWN_INSPECTIONS,
    },
    ROLE_COUNTRY_ADMIN: _all(ACTION_CODES - HQ_ONLY_ACTIONS),
    ROLE_COUNTRY_STAFF: {
        **_all(
            frozenset({"inspection.conduct", "prescription.reply", "plan.submit", "mcp.connect"})
        ),
        **_OWN_INSPECTIONS,
    },
}

#: Роли учёток до спеки «Администрирование» (`0020`). Живут в командах стендов
#: (`make web-user ... role <логин> admin`) и в тестах; переводятся на входе.
LEGACY_ROLE_ADMIN = "admin"
LEGACY_ROLE_AUDITOR = "auditor"
_LEGACY: Mapping[tuple[str, str], str] = {
    (LEGACY_ROLE_ADMIN, SCOPE_HQ): ROLE_HQ_ADMIN,
    (LEGACY_ROLE_AUDITOR, SCOPE_HQ): ROLE_HQ_STAFF,
    (LEGACY_ROLE_ADMIN, SCOPE_COUNTRY): ROLE_COUNTRY_ADMIN,
    (LEGACY_ROLE_AUDITOR, SCOPE_COUNTRY): ROLE_COUNTRY_STAFF,
}


def scope_of_tenant(tenant: str) -> str:
    """Охват ролей пространства: у УК — роли УК, у страны — роли страны."""
    return SCOPE_HQ if _required_tenant(tenant, what="пространство") == HQ_TENANT else SCOPE_COUNTRY


def canonical_role(role: str, tenant: str) -> str:
    """Код роли: старое `admin`/`auditor` переводится по пространству, прочее — как есть."""
    код = (role or "").strip()
    if not код:
        raise ValueError("Не задана роль учётки")
    return _LEGACY.get((код, scope_of_tenant(tenant)), код)


def _grant_problem(роль: str, охват_роли: str, код: str, охват: str) -> str | None:
    if код not in ACTION_CODES:
        return f"{роль}: {код} — нет в каталоге действий"
    if охват not in (REACH_OWN, REACH_ALL):
        return f"{роль}: {код} — охват «{охват}» не из own/all"
    if охват == REACH_OWN and код not in INSPECTION_OBJECT_ACTIONS:
        return f"{роль}: {код} — охват «own» только у действий над проверкой"
    if охват_роли == SCOPE_COUNTRY and код in HQ_ONLY_ACTIONS:
        return f"{роль}: {код} — действие только УК ({RULE_HQ_ONLY})"
    return None


def validate_matrix(matrix: Mapping[str, Grants], scopes: Mapping[str, str]) -> list[str]:
    """Нарушения матрицы словами: код или охват не из каталога, «только УК» у страны."""
    нарушения: list[str] = []
    for роль in sorted(matrix):
        охват_роли = scopes.get(роль)
        if охват_роли is None:
            нарушения.append(f"{роль}: у роли нет охвата")
            continue
        for код in sorted(matrix[роль]):
            беда = _grant_problem(роль, охват_роли, код, matrix[роль][код])
            if беда is not None:
                нарушения.append(беда)
    return нарушения
