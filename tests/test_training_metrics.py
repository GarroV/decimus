"""Метрики «Обучения» (D574, D575, #906) — ядро: цифра, которую читают как факт.

Ошибка здесь молчаливая: неверный знаменатель даёт правдоподобный процент, а не сбой.
Поэтому определения проверяются на малых, посчитанных руками выборках: проценты строятся
из сумм, а не из средних процентов; просрочка не относится к завершённым; сотрудник виден
только как «ещё один человек» и в счётчики не попадает.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from src.domain import training_metrics as tm


def _r(
    user: str,
    course: str,
    status: str,
    *,
    overdue: bool = False,
    spent: int | None = None,
    score: float | None = None,
    access: str | None = None,
    done: str | None = None,
) -> tm.Result:
    def when(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None

    return tm.Result(
        user=user,
        course_id=course,
        status=status,
        is_overdue=overdue,
        time_spent=spent,
        score=score,
        access_date=when(access),
        completion_date=when(done),
    )


SAMPLE = [
    _r("u1", "c1", "complete", spent=600, access="2026-10-01", done="2026-10-03"),
    _r("u1", "c2", "passed", spent=300, score=90, access="2026-10-01", done="2026-10-02"),
    _r("u2", "c1", "in_progress", overdue=True),
    _r("u2", "c2", "failed", score=40, overdue=True),
    _r("u3", "c1", "not_started"),
    _r("u3", "c2", "attended", spent=0),
]


def test_обученность_это_завершённые_к_назначенным() -> None:
    total = tm.aggregate(SAMPLE).total
    assert total.assigned == 6
    assert total.completed == 3  # complete + passed + attended
    assert tm.trained_pct(total) == pytest.approx(50.0)


def test_разбивка_по_статусам() -> None:
    total = tm.aggregate(SAMPLE).total
    assert (total.in_progress, total.not_started, total.failed) == (1, 1, 1)


def test_просрочка_не_относится_к_завершённым() -> None:
    rows = [_r("u1", "c1", "complete", overdue=True), _r("u1", "c2", "in_progress", overdue=True)]
    assert tm.aggregate(rows).total.overdue == 1


def test_полностью_обучен_тот_у_кого_завершено_всё() -> None:
    total = tm.aggregate(SAMPLE).total
    # u1 — оба курса завершены; u2 и u3 — нет.
    assert (total.people_total, total.people_trained) == (3, 1)
    assert tm.fully_trained_pct(total) == pytest.approx(100 / 3)


def test_сдали_тест_это_passed_к_passed_и_failed() -> None:
    total = tm.aggregate(SAMPLE).total
    assert (total.passed, total.failed) == (1, 1)
    assert tm.pass_rate(total) == pytest.approx(50.0)


def test_нет_знаменателя_нет_процента() -> None:
    empty = tm.aggregate([]).total
    assert tm.trained_pct(empty) is None
    assert tm.fully_trained_pct(empty) is None
    assert tm.pass_rate(empty) is None
    assert tm.avg_time(empty) is None


def test_среднее_время_только_по_завершённым_с_временем() -> None:
    total = tm.aggregate(SAMPLE).total
    # 600 и 300; у attended время 0 — это «нет данных», а не мгновенный курс.
    assert (total.time_sum, total.time_n) == (900, 2)
    assert tm.avg_time(total) == pytest.approx(450.0)


def test_среднее_время_не_берёт_незавершённых() -> None:
    rows = [_r("u1", "c1", "in_progress", spent=9999), _r("u2", "c1", "complete", spent=100)]
    assert tm.avg_time(tm.aggregate(rows).total) == pytest.approx(100.0)


def test_средний_балл_и_дни_до_завершения() -> None:
    total = tm.aggregate(SAMPLE).total
    assert tm.avg_score(total) == pytest.approx(65.0)  # 90 и 40
    assert tm.avg_days(total) == pytest.approx(1.5)  # 2 дня и 1 день


def test_дни_не_отрицательные() -> None:
    rows = [_r("u1", "c1", "complete", access="2026-10-05", done="2026-10-01")]
    assert tm.aggregate(rows).total.days_n == 0


def test_разбивка_по_курсам() -> None:
    courses = tm.aggregate(SAMPLE).courses
    assert set(courses) == {"c1", "c2"}
    assert (courses["c1"].assigned, courses["c1"].completed) == (3, 1)
    assert (courses["c2"].assigned, courses["c2"].completed) == (3, 2)


def test_проценты_из_сумм_а_не_из_средних_процентов() -> None:
    # Пиццерия А: 1 из 1 (100%), пиццерия Б: 1 из 3 (33,3%). Среднее процентов — 66,7%,
    # а честный ответ по обеим — 2 из 4 = 50%.
    a = tm.aggregate([_r("a", "c", "complete")]).total
    b = tm.aggregate(
        [_r("b1", "c", "complete"), _r("b2", "c", "not_started"), _r("b3", "c", "not_started")]
    ).total
    assert tm.trained_pct(a + b) == pytest.approx(50.0)


def test_сумма_складывает_все_счётчики() -> None:
    a = tm.aggregate(SAMPLE).total
    both = a + a
    for f in fields(tm.Counters):
        assert getattr(both, f.name) == 2 * getattr(a, f.name), f.name


def test_неизвестный_статус_это_назначено_и_не_более() -> None:
    total = tm.aggregate([_r("u1", "c1", "pending_choice")]).total
    assert (total.assigned, total.completed, total.in_progress, total.not_started) == (1, 0, 0, 0)


def test_счётчики_не_содержат_ничего_о_человеке() -> None:
    # D575: в хранимом виде нет полей, по которым можно назвать сотрудника.
    names = {f.name for f in fields(tm.Counters)}
    assert not names & {"user", "user_id", "email", "name", "staff_id"}
    assert all(f.type in ("int", "float") for f in fields(tm.Counters))
