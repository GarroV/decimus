"""Доска «Ждёт действия» (D378) — ядро прав: стикер не зовёт туда, куда не пустят.

Приёмку ведёт админ (УК — D341, партнёр — свежие проверки своих, D367);
экшн-планы и предписания УК рассматривает админ УК, партнёр на них отвечает
(D371); загрузку рейтингов ведёт контролинг (D358).
"""

from __future__ import annotations

from src.web import home_board as hb

ВСЁ = hb.Counts(
    review=2,
    plans_review=3,
    plans_waiting=4,
    plans_overdue=1,
    orders_due=5,
    orders_overdue=2,
    ratings_age_days=20,
)


def виды(role: str, tenant: str, counts: hb.Counts = ВСЁ) -> list[str]:
    return [s.kind for s in hb.compose(hb.Who(role, tenant), counts, lambda kind: f"/{kind}")]


def test_админ_ук_приёмка_планы_предписания_без_рейтингов() -> None:
    assert виды("admin", "HQ") == [hb.REVIEW, hb.PLANS_REVIEW, hb.ORDERS_DUE]


def test_главный_админ_видит_и_загрузку_рейтингов() -> None:
    assert виды("superadmin", "HQ")[-1] == hb.RATINGS_STALE


def test_аудитор_ук_доски_не_имеет() -> None:
    assert hb.kinds_for(hb.Who("auditor", "HQ")) == ()
    assert виды("auditor", "HQ") == []


def test_контролинг_только_загрузка_рейтингов() -> None:
    assert виды("control", "HQ") == [hb.RATINGS_STALE]


def test_партнёр_сотрудник_отвечает_на_планы_и_предписания_но_не_принимает() -> None:
    assert виды("auditor", "acme") == [hb.PLANS_DUE, hb.ORDERS_DUE]


def test_админ_партнёра_принимает_проверки_своих() -> None:
    assert виды("admin", "acme") == [hb.REVIEW, hb.PLANS_DUE, hb.ORDERS_DUE]


def test_нулевой_счётчик_стикера_не_даёт() -> None:
    assert виды("admin", "HQ", hb.Counts(review=0, plans_review=0, orders_due=0)) == []


def test_свежая_загрузка_рейтингов_стикера_не_даёт_а_никогда_даёт() -> None:
    assert виды("control", "HQ", hb.Counts(ratings_age_days=hb.RATINGS_STALE_DAYS - 1)) == []
    assert виды("control", "HQ", hb.Counts(ratings_never=True)) == [hb.RATINGS_STALE]


def test_просроченные_идут_в_стикер_горящими() -> None:
    стикеры = hb.compose(hb.Who("auditor", "acme"), ВСЁ, lambda kind: "/")
    assert [(s.count, s.urgent) for s in стикеры] == [(4, 1), (5, 2)]
