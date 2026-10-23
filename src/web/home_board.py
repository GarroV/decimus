"""Задания карточки «Требует внимания» на «Главной» (D378, D398): стикеры по живым счётчикам.

Образец — доска Swarm (`MiscWidgets.tsx`): лента бумажных стикеров. Отличие —
только живые задания и объявления, утверждённые владельцем (D217: без его «да» на
текст и круг объявление не строится; первое — D629). Стикер появляется, только
когда есть что делать, и ведёт туда, где это делают.

Состав по роли — ядро: стикер не зовёт человека туда, куда его не пустят.
Решение о составе — чистая функция `compose`; счётчики читает `load_counts`, и
читает только то, что этой роли положено.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.db import action_plans, prescriptions, queries
from src.db import ratings_read as ratings
from src.db.models import ORIGIN_FIELD
from src.db.reach import Reach
from src.domain.permissions import role_may
from src.domain.tenants import CONTROL_ROLE, HQ_TENANT, SUPERADMIN_ROLE

#: Через сколько дней без загрузки РС / РКО контролингу напоминают о ней.
#: РКО приходит неделями, поэтому две недели — уже пропуск, а не пауза.
RATINGS_STALE_DAYS = 14

#: За сколько дней до срока предписание попадает на доску.
DUE_SOON_DAYS = 7

REVIEW = "review"
PLANS_REVIEW = "plans_review"
PLANS_DUE = "plans_due"
ORDERS_DUE = "orders_due"
RATINGS_STALE = "ratings_stale"
#: Объявление (D629): перепривязать Claude ради загрузки фото из папки.
MCP_RELINK = "mcp_relink"

#: Ключи Claude, выпущенные до объявления, — у тех, кому перепривязать. Выпустил
#: новый — стикер пропадает сам; круг объявления — подключённые личным ключом (D629).
MCP_RELINK_BEFORE = datetime(2026, 10, 23, 10, 30, tzinfo=UTC)


@dataclass(frozen=True)
class Who:
    """Кто смотрит: роль и пространство (HQ — УК)."""

    role: str
    tenant: str

    @property
    def hq(self) -> bool:
        return self.tenant == HQ_TENANT


@dataclass(frozen=True)
class Counts:
    """Живые счётчики. `None` — этой роли счётчик не читается."""

    review: int | None = None
    plans_review: int | None = None
    plans_waiting: int | None = None
    plans_overdue: int = 0
    orders_due: int | None = None
    orders_overdue: int = 0
    ratings_age_days: int | None = None
    ratings_never: bool = False


#: Показывать ли стикеры на «Главной». D542 их скрыл, D629 вернул «пока, дальше по
#: отзывам»: выключено — доска не строится и база для неё не читается.
SHOWN = True


@dataclass(frozen=True)
class Sticker:
    """Один стикер: код вида (подпись и текст — `home.board.<kind>.*`), число,
    сколько из него горит, куда ведёт."""

    kind: str
    count: int
    href: str
    urgent: int = 0


def kinds_for(who: Who) -> tuple[str, ...]:
    """Какие стикеры этой роли вообще возможны. Пусто — доски у роли нет.

    Приёмку ведёт админ (УК — свои проверки, D341; партнёр — свежие проверки
    своих сотрудников, D367). Экшн-планы и предписания УК рассматривает в
    «Действиях УК» (только админ), партнёр отвечает на них в своих разделах
    (D371). Загрузку рейтингов ведёт контролинг (D358), главный админ видит её же.
    """

    def может(code: str) -> bool:
        return role_may(who.role, who.tenant, code)

    out: list[str] = []
    # Приёмка — у тех, кому матрица открывает `inspection.accept` (D341, D367, D440).
    if может("inspection.accept"):
        out.append(REVIEW)
    if может("plan.manage"):  # УК рассматривает планы и следит за сроками предписаний
        out += [PLANS_REVIEW, ORDERS_DUE]
    if может("plan.submit"):  # партнёр сдаёт планы и отвечает на предписания (D371)
        out += [PLANS_DUE, ORDERS_DUE]
    # Напоминание о загрузке рейтингов — работа контролинга (D358) и главного
    # админа: выбор доски, а не право (загружать может и админ УК).
    if может("ratings.manage") and who.role in (CONTROL_ROLE, SUPERADMIN_ROLE):
        out.append(RATINGS_STALE)
    return tuple(out)


def compose(who: Who, counts: Counts, href: Callable[[str], str]) -> tuple[Sticker, ...]:
    """Стикеры, которые есть что делать, в порядке срочности вида."""
    kinds = kinds_for(who)
    out: list[Sticker] = []

    def add(kind: str, count: int | None, urgent: int = 0) -> None:
        if kind in kinds and count:
            out.append(Sticker(kind, count, href(kind), urgent))

    add(REVIEW, counts.review)
    add(PLANS_REVIEW, counts.plans_review)
    add(PLANS_DUE, counts.plans_waiting, counts.plans_overdue)
    add(ORDERS_DUE, counts.orders_due, counts.orders_overdue)
    if RATINGS_STALE in kinds and (
        counts.ratings_never
        or (counts.ratings_age_days is not None and counts.ratings_age_days >= RATINGS_STALE_DAYS)
    ):
        out.append(Sticker(RATINGS_STALE, counts.ratings_age_days or 0, href(RATINGS_STALE)))
    return tuple(out)


def announcements(
    token_issued_at: datetime | None, href: Callable[[str], str]
) -> tuple[Sticker, ...]:
    """Объявления, утверждённые владельцем, — по признаку человека, а не по роли.

    Перепривязать Claude (D629) — тому, чей живой личный ключ выпущен до объявления.
    """
    if token_issued_at is not None and token_issued_at < MCP_RELINK_BEFORE:
        return (Sticker(MCP_RELINK, 1, href(MCP_RELINK)),)
    return ()


def _review(reach: Reach, who: Who) -> int:
    """Ждут приёмки именно этого человека: УК — проверки УК, партнёр — свежие
    проверки своих сотрудников из обхода (D367). Чужие ждущие в охвате видны
    на чтение, но решать их не ему."""
    ряд = queries.list_inspections(reach=reach, limit=500, on_review=True)
    return sum(
        1
        for row in ряд
        if row.on_review
        and row.tenant_code == who.tenant
        and (who.hq or row.origin == ORIGIN_FIELD)
    )


def load_counts(reach: Reach, who: Who, *, now: datetime) -> Counts:
    """Счётчики для доски — только те, что этой роли положены."""
    kinds = kinds_for(who)
    today = now.date()
    поля: dict[str, object] = {}
    if REVIEW in kinds:
        поля["review"] = _review(reach, who)
    if PLANS_REVIEW in kinds or PLANS_DUE in kinds:
        запросы = action_plans.list_requests(reach=reach).rows
        if PLANS_REVIEW in kinds:
            поля["plans_review"] = sum(
                1 for r in запросы if r.status == action_plans.STATUS_ON_REVIEW
            )
        if PLANS_DUE in kinds:
            ждут = [r for r in запросы if r.status == action_plans.STATUS_REQUESTED]
            поля["plans_waiting"] = len(ждут)
            поля["plans_overdue"] = sum(1 for r in ждут if r.overdue(today))
    if ORDERS_DUE in kinds:
        горят = [
            p
            for p in prescriptions.list_prescriptions(reach=reach).rows
            if p.status == prescriptions.STATUS_ISSUED
            and p.due_on <= today + timedelta(days=DUE_SOON_DAYS)
        ]
        поля["orders_due"] = len(горят)
        поля["orders_overdue"] = sum(1 for p in горят if p.overdue(today))
    if RATINGS_STALE in kinds:
        загружено = ratings.last_loaded()
        if загружено:
            последняя = max(загружено.values())
            поля["ratings_age_days"] = (now - последняя).days
        else:
            поля["ratings_never"] = True
    return Counts(**поля)  # type: ignore[arg-type]
