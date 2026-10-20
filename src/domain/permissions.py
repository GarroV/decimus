"""Матрица «роль × действие» и проверка `can` — единственное место, где решается,
что роли можно (D408; роли — D440, D420, D429; партнёр — D341, D346, D367).

Решение принимается двумя слоями, и отказ первого второй не переопределяет:

1. **Граница пространств** (код, не настраивается): человек УК действует в
   любом пространстве; человек партнёра — только в своём и никогда над
   объектом УК; действие «только УК» не выдаётся роли партнёра ни одной
   клеткой; действие «только своё пространство» не выходит за своё и у УК.
2. **Матрица**: есть ли у роли (пространство × роль учётки) это действие.

Сюда же сведены разделы веба на чтение (`view.<раздел>`) и то, что закрыто
в Claude поверх матрицы (`CLAUDE_CLOSED`). Остальные модули не сравнивают роли
строками — спрашивают здесь (`can`, `role_may`); полноту держат тесты
`tests/test_permissions_*.py`, `tests/test_web_guard.py`, `tests/test_mcp_policy.py`
и `tests/test_bot_command_actions.py`.

Матрица живёт в коде. Настройка галочками в админке (D408) — отдельный шаг,
развилка у владельца (как совместить с D440 и D447). Код действия — ключ, подписи
переводятся отдельно. Новая операция получает код здесь в момент появления —
это часть её готовности.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .tenants import HQ_TENANT, canonical_tenant

#: Сторона, которой принадлежит пространство: УК или партнёр.
SIDE_HQ = "hq"
SIDE_PARTNER = "partner"


@dataclass(frozen=True)
class Action:
    """Одно действие каталога."""

    code: str
    group: str
    #: Только УК: роли партнёра не выдаётся никакой клеткой (слой 1).
    hq_only: bool = False
    #: Только партнёр: у УК этого действия нет (ответ на предписание, свой план).
    partner_only: bool = False
    #: Только в своём пространстве — и у УК тоже (письмо партнёру по своей проверке).
    own_space: bool = False
    #: Меняет данные. Роль без пишущих действий — «только чтение» (гость, D440).
    writes: bool = True


#: Разделы веба (`src/web/sections.py`) — чтение. Ключи совпадают с реестром
#: разделов; сверку держит `tests/test_permissions_table.py`.
_VIEWS: tuple[Action, ...] = (
    Action("view.overview", "view", writes=False),
    Action("view.registry", "view", writes=False),
    # Экран пиццерии (D508): УК листает страны, партнёр попадает на него с «Главной»
    # и видит только свои страны (охват, а не флаг) — поэтому не `hq_only`.
    Action("view.country", "view", writes=False),
    Action("view.ratings", "view", writes=False),
    # «Обучение» (D578, #906): все, кроме контроля (D420: контроль ведёт только «Рейтинги»);
    # партнёр — свои страны (охват).
    Action("view.training", "view", writes=False),
    Action("view.calendar", "view", writes=False),
    Action("view.admin", "view", writes=False),
    # «Действия» (D526): экшн-планы и предписания — раздел УК и партнёра; кнопки
    # УК и партнёра различают действия `plan.*` и `prescription.*`.
    Action("view.actions", "view", writes=False),
    Action("view.users", "view", writes=False),
)

ACTIONS: tuple[Action, ...] = (
    # Проверки
    Action("inspection.read", "inspection", writes=False),
    Action("inspection.conduct", "inspection"),
    # Запись по проверке — только в своём пространстве и у УК (D283, D341).
    # Открыть УК запись в проверки партнёров (D406) — отдельный шаг вместе с
    # журналом действий УК у партнёра; до него граница держит своё.
    Action("inspection.accept", "inspection", own_space=True),
    Action("inspection.revise", "inspection", own_space=True),
    Action("inspection.retract", "inspection", hq_only=True, own_space=True),
    Action("inspection.move", "inspection", hq_only=True, own_space=True),
    Action("inspection.letter", "inspection", own_space=True),
    Action("inspection.import", "inspection", hq_only=True),
    # Предписания и экшн-планы
    Action("prescription.manage", "prescription", hq_only=True),
    Action("prescription.reply", "prescription", partner_only=True),
    Action("plan.manage", "plan", hq_only=True),
    Action("plan.submit", "plan", partner_only=True),
    # Методика
    Action("checklist.read", "checklist", writes=False),
    Action("checklist.edit", "checklist"),
    Action("checklist.publish", "checklist"),
    Action("checklist.manage", "checklist"),
    Action("checklist.master", "checklist"),
    # Указатель прода один на всю сеть: партнёру не выдаётся (D460), дверь
    # `apply_to_production` в его пространстве отказывала и раньше.
    Action("checklist.apply", "checklist", hq_only=True),
    Action("phrases.manage", "checklist"),
    # Сырые слова аудиторов всех пространств из накопителя бота: разделения по
    # пространствам в нём нет, поэтому партнёру не выдаётся (D460, ревью безопасности).
    Action("phrases.raw", "checklist", hq_only=True, writes=False),
    # Поездки «Календаря» (D505, D506): только своё пространство — и у УК тоже,
    # поездки партнёра УК не трогает. `trip.plan` — любые поездки пространства,
    # `trip.own` — только те, где человек сам исполнитель.
    Action("trip.plan", "trip", own_space=True),
    Action("trip.own", "trip", own_space=True),
    # Рейтинги
    Action("ratings.read", "ratings", writes=False),
    Action("ratings.manage", "ratings", hq_only=True),
    # Люди, пространства, справочник, ключи
    Action("people.manage", "people"),
    Action("people.role", "people"),
    Action("space.manage", "people", hq_only=True),
    Action("unit.create", "unit", hq_only=True),
    Action("api.manage", "api", hq_only=True),
    # Ключи внешних сервисов на экране «Подключения» (D576): отдельный код, чтобы доступ к
    # секретам не вытекал из доступа к ключам API.
    Action("keys.manage", "api", hq_only=True),
    # Бот: счётчик отказов мастера (`/stops`). Журнал отказов один на весь бот,
    # разделения по пространствам в нём нет, поэтому партнёру не выдаётся (F-104).
    Action("refusals.read", "bot", hq_only=True, writes=False),
    *_VIEWS,
)

_BY_CODE: Mapping[str, Action] = {a.code: a for a in ACTIONS}
ACTION_CODES: frozenset[str] = frozenset(_BY_CODE)

RULE_OK = "ok"
RULE_MATRIX = "matrix"
RULE_HQ_ONLY = "hq_only"
RULE_PARTNER_ONLY = "partner_only"
RULE_HQ_OBJECT = "hq_object"
RULE_FOREIGN_SPACE = "foreign_space"
RULE_UNKNOWN_ROLE = "unknown_role"


class UnknownAction(ValueError):
    """Код действия не из каталога — ошибка кода, а не отказ человеку."""


def require_action(code: str) -> Action:
    """Действие каталога по коду. Единственная проверка кода на весь проект."""
    действие = _BY_CODE.get(code)
    if действие is None:
        raise UnknownAction(f"Действия «{code}» нет в каталоге src/domain/permissions.py")
    return действие


def view_code(section_key: str) -> str:
    """Код чтения раздела веба."""
    return require_action(f"view.{section_key}").code


def _codes(*codes: str) -> frozenset[str]:
    return frozenset(require_action(c).code for c in codes)


_ALL_VIEWS_HQ = frozenset(a.code for a in _VIEWS)
_ALL_VIEWS_PARTNER = frozenset(a.code for a in _VIEWS if not a.hq_only)

#: Работа с проверками в УК: проводить, вычитывать, принимать, править, снимать,
#: переносить, письма, предписания, экшн-планы (D440 — и у девелопера).
_HQ_WORK = _codes(
    "inspection.read",
    "inspection.conduct",
    "inspection.accept",
    "inspection.revise",
    "inspection.retract",
    "inspection.move",
    "inspection.letter",
    "prescription.manage",
    "plan.manage",
    "ratings.read",
    "unit.create",
    "phrases.raw",
    "trip.plan",
)

#: Методика без главного чек-листа и указателя прода (D440).
_CHECKLISTS = _codes(
    "checklist.read", "checklist.edit", "checklist.publish", "checklist.manage", "phrases.manage"
)
#: Главный чек-лист и указатель прода — только админы (D440).
_CHECKLIST_OWNER = _codes("checklist.master", "checklist.apply")

_HQ_ADMIN = (
    _HQ_WORK
    | _CHECKLISTS
    | _CHECKLIST_OWNER
    | _ALL_VIEWS_HQ
    | _codes(
        "inspection.import",  # D335: загрузка истории — админы УК
        "ratings.manage",
        "people.manage",
        "people.role",
        "space.manage",
        "refusals.read",
    )
)

#: Партнёр (D346): сотрудник проводит проверки и видит своё; админ пространства
#: ещё ведёт людей, свои чек-листы и вычитывает свежие проверки своих (D367).
_PARTNER_AUDITOR = _ALL_VIEWS_PARTNER | _codes(
    "inspection.read",
    "inspection.conduct",
    "inspection.letter",
    "prescription.reply",
    "plan.submit",
    "checklist.read",
    "ratings.read",
    "trip.own",
)

#: Матрица: (сторона, роль учётки) → действия. Нет клетки — нет права.
MATRIX: Mapping[tuple[str, str], frozenset[str]] = {
    # Главный админ — всё, что админ, и ключи API (D440).
    (SIDE_HQ, "superadmin"): _HQ_ADMIN | _codes("api.manage", "keys.manage"),
    (SIDE_HQ, "admin"): _HQ_ADMIN,
    # Бизнес-девелопер (D440): сервис в полном объёме, кроме главного чек-листа,
    # указателя прода, стран, людей, ключей и загрузок рейтингов.
    # Загрузка проверки через Claude — и у девелопера (владелец 20.10.2026: «дай
    # нормально обкатать основной функционал»; партнёрам по-прежнему никогда, D335).
    (SIDE_HQ, "developer"): _HQ_WORK | _CHECKLISTS | _ALL_VIEWS_HQ | _codes("inspection.import"),
    # Контроль (D420): только рейтинги и свои люди (D360) — без смены ролей.
    (SIDE_HQ, "control"): _codes(
        "ratings.read", "ratings.manage", "people.manage", "view.ratings", "view.users"
    ),
    # Гость (D429, D440): вся сеть на чтение, ничего не меняет и не отправляет.
    (SIDE_HQ, "guest"): _codes(
        "inspection.read",
        "ratings.read",
        "view.overview",
        "view.registry",
        "view.calendar",
        "view.country",
        "view.ratings",
        "view.training",
        "view.users",
    ),
    (SIDE_PARTNER, "admin"): _PARTNER_AUDITOR
    | _CHECKLISTS
    | _codes("checklist.master")
    | _codes("inspection.accept", "inspection.revise", "people.manage", "people.role", "trip.plan"),
    (SIDE_PARTNER, "auditor"): _PARTNER_AUDITOR,
}

#: Закрыто в Claude (MCP) поверх матрицы, для всех ролей стороны.
#: Снятие проверки через Claude — только служебный токен на экстренный случай
#: (D341, спека D417). Методика партнёра в Claude открыта ровно как в вебе (D460,
#: уточняет D342/D417): админ ведёт свою, сотрудник только читает — это решает
#: матрица, лишнего закрытия здесь нет.
CLAUDE_CLOSED: Mapping[str, frozenset[str]] = {
    SIDE_HQ: _codes("inspection.retract"),
    SIDE_PARTNER: _codes("inspection.retract"),
}


@dataclass(frozen=True)
class Actor:
    """Кто действует: пространство и роль учётки на момент запроса."""

    tenant: str
    role: str | None
    #: Учётка веба: по ней пишется журнал действий УК у партнёра.
    user_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """Ответ `can`: можно ли и каким правилом это решено."""

    allowed: bool
    rule: str

    def __bool__(self) -> bool:
        return self.allowed


def side_of(tenant: str) -> str:
    """Сторона пространства. Пустой код — ошибка: без него граница не решается."""
    код = canonical_tenant(tenant or "")
    if not код:
        raise ValueError("Не задано пространство: без него граница пространств не решается")
    return SIDE_HQ if код == HQ_TENANT else SIDE_PARTNER


def _boundary(кто: str, действие: Action, чьё: str) -> str | None:
    """Слой 1: правило отказа границы или `None`, если граница пропускает."""
    своё = кто == чьё
    if кто == HQ_TENANT:
        if действие.partner_only:
            return RULE_PARTNER_ONLY
        if действие.own_space and not своё:
            return RULE_FOREIGN_SPACE
        return None
    if действие.hq_only:
        return RULE_HQ_ONLY
    if чьё == HQ_TENANT:
        return RULE_HQ_OBJECT
    if not своё:
        return RULE_FOREIGN_SPACE
    return None


def grants_of(role: str | None, tenant: str) -> frozenset[str]:
    """Действия роли в её пространстве. Незнакомая роль — ничего."""
    if not role:
        return frozenset()
    return MATRIX.get((side_of(tenant), role), frozenset())


def can(actor: Actor, action: str, object_tenant: str | None = None) -> Decision:
    """Может ли `actor` сделать `action` над объектом пространства `object_tenant`.

    Без `object_tenant` объект — в своём пространстве человека. Пространство
    объекта берётся из самого объекта (строки базы), а не из формы.
    """
    действие = require_action(action)
    кто = canonical_tenant(actor.tenant or "")
    side_of(кто)  # пустое пространство человека — ошибка кода
    чьё = кто if object_tenant is None else canonical_tenant(object_tenant)
    side_of(чьё)
    отказ = _boundary(кто, действие, чьё)
    if отказ is not None:
        return Decision(False, отказ)
    if (side_of(кто), actor.role or "") not in MATRIX:
        return Decision(False, RULE_UNKNOWN_ROLE)
    if действие.code in grants_of(actor.role, кто):
        return Decision(True, RULE_OK)
    return Decision(False, RULE_MATRIX)


def role_may(role: str | None, tenant: str | None, action: str) -> bool:
    """Короткий вопрос «может ли роль это в своём пространстве»."""
    if not tenant or not canonical_tenant(tenant):
        require_action(action)
        return False
    return can(Actor(tenant=tenant, role=role), action).allowed


def claude_may(role: str | None, tenant: str, action: str) -> bool:
    """Может ли роль это через Claude (MCP): матрица минус `CLAUDE_CLOSED`."""
    if action in CLAUDE_CLOSED.get(side_of(tenant), frozenset()):
        return False
    return role_may(role, tenant, action)


def is_read_only(role: str | None, tenant: str | None) -> bool:
    """Роль не меняет ничего: в её клетках нет пишущих действий (гость, D440)."""
    if not tenant:
        return True
    return not any(_BY_CODE[c].writes for c in grants_of(role, tenant))


def open_to_space(action: str, tenant: str) -> bool:
    """Граница без роли: открыто ли действие пространству вообще (`unit.create` → УК)."""
    действие = require_action(action)
    return _boundary(canonical_tenant(tenant), действие, canonical_tenant(tenant)) is None


def validate_matrix(
    matrix: Mapping[tuple[str, str], Iterable[str]] = MATRIX,
) -> list[str]:
    """Нарушения матрицы словами: код не из каталога, «только УК» у партнёра и наоборот."""
    нарушения: list[str] = []
    for (сторона, роль), коды in sorted(matrix.items()):
        if сторона not in (SIDE_HQ, SIDE_PARTNER):
            нарушения.append(f"{сторона}/{роль}: сторона не из hq/partner")
            continue
        for код in sorted(коды):
            действие = _BY_CODE.get(код)
            if действие is None:
                нарушения.append(f"{сторона}/{роль}: {код} — нет в каталоге действий")
            elif сторона == SIDE_PARTNER and действие.hq_only:
                нарушения.append(f"{сторона}/{роль}: {код} — действие только УК ({RULE_HQ_ONLY})")
            elif сторона == SIDE_HQ and действие.partner_only:
                нарушения.append(
                    f"{сторона}/{роль}: {код} — действие только партнёра ({RULE_PARTNER_ONLY})"
                )
    return нарушения
