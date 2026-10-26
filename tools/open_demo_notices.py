"""Предписания открытого демо: страница «ОСБ» и «Compliance notices» стран — не пустые.

Дальше всё идёт дверями продукта (`prescriptions_write`): черновик, запрос на согласование,
согласование, возврат, отправка, закрытие. Подписывают логины людей из `open_demo_people`:
пишут девелоперы, согласует ОСБ — поэтому уведомления «ждёт согласования» и «согласовано»
попадают к ним в колокольчик, как у настоящих.

Состояния — все пять очередей страницы: «На согласовании» (2), «Согласовано, не отправлено»
(1), «Действуют» (3), «Черновики» (2, один возвращён с комментарием) и «Закрытые» (1).
Основания — проверки и пиццерии страны, сроки — от дня посева. **Просроченных нет:** база не
даёт отправить предписание с прошедшим сроком, а демо пересобирается раз в час.

Письмо в почту не кладётся: отправку (`PutDraft`) подменяет заглушка — демо без Gmail, и
наружу не уходит ничего (§7 глобальных правил). Почты адресатов — `example.com`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import open_demo_people as people
import psycopg

from src.db import prescriptions_write as rx
from src.db.prescriptions import Draft, Prescription
from src.db.space import apply_space

#: Кто пишет и кто согласует: логины людей из `open_demo_people`.
AUTHORS = ("demo-developer", "nina.petrosyan")
OSB = "priya.shah"
ADMIN = "tom.walker"
#: Состояние, до которого доводится предписание.
DRAFT, REVIEW, RETURNED, APPROVED, ISSUED, CLOSED = (
    "draft", "review", "returned", "approved", "issued", "closed",
)  # fmt: skip


@dataclass(frozen=True)
class Notice:
    country: str
    units: tuple[str, ...]
    days: int  # срок — через столько дней от дня посева
    subject: str
    body: str
    state: str


NOTICES = (
    Notice(
        "RS",
        ("Northgate-1", "Northgate-2"),
        21,
        "Repeated cleanliness findings in the Northgate pizzerias",
        "Dear partner,\n\nThe last three inspections of Northgate-1 and Northgate-2 recorded the "
        "same cleanliness findings (oven conveyor, prep table fixings). Please send a corrective "
        "action plan with owners and dates, and confirm the daily cleaning checklist is signed "
        "on every shift.\n\nBest regards,\nBusiness Support",
        REVIEW,
    ),
    Notice(
        "GE",
        ("Hillcrest-1", "Harbor Bay-1"),
        28,
        "Hand-wash stations and consumables",
        "Dear partner,\n\nInspections found hand-wash stations without paper towels and soap "
        "dispensers empty at the start of the shift in Hillcrest-1 and Harbor Bay-1. Please "
        "confirm the opening checklist now includes a consumables check and share the signed "
        "log for the last two weeks.\n\nBest regards,\nBusiness Support",
        REVIEW,
    ),
    Notice(
        "AM",
        ("Old Town-1", "Lakeside-1"),
        30,
        "Cold-chain temperature records",
        "Dear partner,\n\nTemperature records for the walk-in cold room are missing for several "
        "days in Old Town-1 and Lakeside-1. Please provide the records, explain the gap and "
        "confirm who is responsible for the daily readings.\n\nBest regards,\nBusiness Support",
        APPROVED,
    ),
    Notice(
        "RS",
        ("Riverside-1",),
        14,
        "Pest-control contract renewal",
        "Dear partner,\n\nThe pest-control contract for Riverside-1 expired and no renewed "
        "agreement was shown at the last visit. Please send the new contract and the latest "
        "service report.\n\nBest regards,\nBusiness Support",
        ISSUED,
    ),
    Notice(
        "AM",
        ("Westfield-1",),
        35,
        "Opening checklist gaps in Westfield-1",
        "Dear partner,\n\nThe opening checklist in Westfield-1 was left unsigned on four of the "
        "last ten days. Please confirm the manager on duty signs it and send a sample of the "
        "completed sheets.\n\nBest regards,\nBusiness Support",
        ISSUED,
    ),
    Notice(
        "GE",
        ("Hillcrest-1",),
        7,
        "Oven maintenance log",
        "Dear partner,\n\nThe oven maintenance log in Hillcrest-1 has no entry after the "
        "technician visit. Please send the service act and update the log.\n\n"
        "Best regards,\nBusiness Support",
        ISSUED,
    ),
    Notice(
        "RS",
        ("Northgate-2",),
        10,
        "Expired sauce labels in Northgate-2",
        "Dear partner,\n\nOpened sauce containers had no opening date in the last inspection. "
        "Please confirm the labelling rule is back in place.\n\nBest regards,\nBusiness Support",
        CLOSED,
    ),
    Notice(
        "GE",
        ("Harbor Bay-1",),
        20,
        "Courier area housekeeping",
        "Dear partner,\n\nDebris and unsorted boxes were found in the courier area. Please tidy "
        "the area and add it to the closing checklist.\n\nBest regards,\nBusiness Support",
        RETURNED,
    ),
    Notice(
        "AM",
        ("Old Town-1",),
        25,
        "Staff room and lockers",
        "Dear partner,\n\nPlease check the staff room and lockers in Old Town-1 and report "
        "back.\n\nBest regards,\nBusiness Support",
        DRAFT,
    ),
)


def _ids(dsn: str) -> tuple[dict[str, str], dict[str, str]]:
    """Пиццерии по имени и последняя принятая проверка УК каждой — основания предписаний."""
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        units = {
            str(n): str(i)
            for n, i in conn.execute("select name, id::text from units where tenant_code = 'HQ'")
        }
        bases = {
            str(n): str(i)
            for n, i in conn.execute(
                "select distinct on (u.name) u.name, i.id::text from inspections i "
                "join units u on u.id = i.unit_id "
                "where i.tenant_code = 'HQ' and i.status = 'finalized' and i.retracted_at is null "
                "order by u.name, i.inspection_date desc"
            )
        }
    return units, bases


def _no_mail(_: Prescription) -> None:
    """Отправка предписания в демо: письмо в почту не кладётся."""


def _walk(ident: str, state: str, author: str) -> None:
    """Довести предписание от черновика до `state` теми же шагами, что в вебе."""
    if state == DRAFT:
        return
    rx.request_review(ident, actor=author)
    if state == REVIEW:
        return
    if state == RETURNED:
        rx.return_to_author(
            ident, actor=OSB, comment="Add the date of the second visit and a clear deadline."
        )
        return
    rx.approve(ident, actor=OSB)
    if state == APPROVED:
        return
    rx.issue(ident, actor=ADMIN, put_draft=_no_mail)
    if state == CLOSED:
        rx.close(ident, actor=ADMIN, comment="Partner confirmed the labelling rule is in place.")


def seed(dsn: str, today: date | None = None) -> int:
    """Завести предписания демо; повторный запуск на той же базе их не удваивает."""
    today = today or date.today()
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        if conn.execute("select count(*) from prescriptions").fetchone() != (0,):
            return 0
    units, bases = _ids(dsn)
    for i, notice in enumerate(NOTICES):
        author = AUTHORS[i % len(AUTHORS)]
        recipients = people.email_of(people.PARTNERS[notice.country].contact)
        ident = rx.create_draft(
            Draft(
                country=notice.country,
                due_on=today + timedelta(days=notice.days),
                recipients=recipients,
                subject=notice.subject,
                body=notice.body,
                unit_ids=tuple(units[u] for u in notice.units),
                inspection_ids=tuple(bases[u] for u in notice.units if u in bases),
            ),
            actor=author,
        )
        _walk(ident, notice.state, author)
    return len(NOTICES)
