"""«Начало работы» партнёра (D756, D759 п.6): какие шаги у роли и что из них сделано.

Чистое решение без базы и без Flask — по образцу `home_board.compose`: факты читает
`onboarding_facts`, а здесь они превращаются в список шагов. Так «что считать
сделанным» проверяется тестом, а не глазами.

Шаги бывают трёх видов, и слово «сделайте» говорится только про первый:

* `todo` — человек делает сам (привязать бота, завести сотрудников, провести проверку);
* `waiting` — ждёт управляющую компанию: страны пространства, пиццерии справочника и
  чек-лист партнёр завести не может (D284, D233, `unit.create`). Сказать «сделайте»
  было бы неправдой;
* `done` — сделано.

«Не знаю» (`None`: база не прочиталась) шаг не показывает и сделанным не считает: как
у `connect_reminder`, напоминание — только по факту. Подключение Claude необязательно:
оно показывается, но карточку не держит.

Готовность пространства (`space_rows`) — ОДНА функция на двоих: по ней партнёр видит
«ждёт УК», а управляющая компания — «есть / нет» в карточке пространства. Второй
копии правила нет.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.permissions import SIDE_PARTNER, role_may, side_of
from src.domain.tenants import canonical_tenant

BOT = "bot"
PEOPLE = "people"
COUNTRIES = "countries"
UNITS = "units"
CHECKLIST = "checklist"
INSPECTION = "inspection"
CLAUDE = "claude"

DONE = "done"
TODO = "todo"
WAITING = "waiting"
UNKNOWN = "unknown"

#: Роль, которая ведёт людей пространства (`people.manage`): шаг «завести сотрудников» — ей.
_PEOPLE_ACTION = "people.manage"
#: Действие «вести проверку»: бот и первая проверка нужны только тем, кто их ведёт (D420).
_CONDUCT_ACTION = "inspection.conduct"


@dataclass(frozen=True)
class SpaceFacts:
    """Что есть в пространстве партнёра; `None` — не прочиталось."""

    countries: bool | None
    units: bool | None
    checklist: bool | None


@dataclass(frozen=True)
class Facts:
    """Всё, что знает карточка о человеке и его пространстве; `None` — не прочиталось."""

    bot_bound: bool | None
    claude_connected: bool | None
    people_added: bool | None
    first_inspection: bool | None
    space: SpaceFacts


@dataclass(frozen=True)
class Step:
    """Один шаг: ключ (он же ключ текста), состояние, обязательность."""

    key: str
    state: str
    required: bool = True


def _ours(done: bool | None, key: str, *, required: bool = True) -> Step:
    """Шаг, который делает сам человек."""
    state = UNKNOWN if done is None else (DONE if done else TODO)
    return Step(key, state, required)


def _theirs(done: bool | None, key: str) -> Step:
    """Шаг, который делает управляющая компания: не сделан — «ждёт», а не «сделайте»."""
    state = UNKNOWN if done is None else (DONE if done else WAITING)
    return Step(key, state)


def space_rows(space: SpaceFacts) -> tuple[Step, ...]:
    """Готовность пространства: страны, пиццерии, чек-лист. Одна на партнёра и на УК."""
    return (
        _theirs(space.countries, COUNTRIES),
        _theirs(space.units, UNITS),
        _theirs(space.checklist, CHECKLIST),
    )


def space_ready(space: SpaceFacts) -> bool:
    """Пространство готово к работе: все три строки есть (непрочитанная — не «есть»)."""
    return all(row.state == DONE for row in space_rows(space))


def steps_for(role: str, tenant: str, facts: Facts, *, bot_available: bool) -> tuple[Step, ...]:
    """Шаги роли. У управляющей компании их нет: онбординг партнёрский (решение 12.11.2026).

    `bot_available` — настроен ли бот на площадке: без него шаг «привязать бота» не нужен.
    Непрочитанные шаги в список не попадают.
    """
    код = canonical_tenant(tenant or "")
    if not код or side_of(код) != SIDE_PARTNER:
        return ()
    conducts = role_may(role, код, _CONDUCT_ACTION)
    steps: list[Step] = []
    if conducts and bot_available:
        steps.append(_ours(facts.bot_bound, BOT))
    if role_may(role, код, _PEOPLE_ACTION):
        steps.append(_ours(facts.people_added, PEOPLE))
    steps.extend(space_rows(facts.space))
    if conducts:
        steps.append(_ours(facts.first_inspection, INSPECTION))
    steps.append(_ours(facts.claude_connected, CLAUDE, required=False))
    return tuple(step for step in steps if step.state != UNKNOWN)


def needs_attention(steps: tuple[Step, ...]) -> bool:
    """Нужна ли карточка: хоть один обязательный шаг не сделан (свой или ждёт УК)."""
    return any(step.required and step.state in (TODO, WAITING) for step in steps)
