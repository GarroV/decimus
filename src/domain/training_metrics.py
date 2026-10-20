"""Метрики экрана «Обучение» — определения в одном месте (D574, D575, #906; docs/20-training.md).

Исходные строки — результаты прохождения курсов сотрудниками пиццерии из iSpring. Здесь
они сворачиваются в **счётчики** (`Counters`), и только счётчики идут дальше: в базу, на
экран. Сотрудник виден только внутри `aggregate` — как ключ, по которому считаются
«люди» и «полностью обучены»; наружу не выходит ни его идентификатор, ни число-отпечаток
(D575: данных о сотрудниках у нас нет).

**Определения** (одна строка — одно назначение курса человеку):

- назначено — все строки; завершено — `complete`, `passed`, `attended`;
- просрочено — строка с `isOverdue`, которая не завершена;
- обученность % = завершено / назначено; полностью обучены % = люди, у которых завершено
  всё назначенное, / люди; сдали тест % = `passed` / (`passed` + `failed`);
- среднее время — по завершённым, у которых `timeSpent` больше нуля (ноль — «нет данных»);
- средний балл — по строкам с `awardedScore`; дни до завершения — по завершённым с обеими
  датами, неотрицательные.

**Проценты считаются из сумм, никогда не как среднее процентов:** страна и сеть — это
`Counters`, сложенные сложением (`+`), а процент берётся уже у суммы.

Неизвестный статус (`pending_choice` и др.) — «назначено» и ничего более: он не завершён
и не сдан, но и не прячется из знаменателя.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import datetime

COMPLETED = frozenset({"complete", "passed", "attended"})
IN_PROGRESS = frozenset({"in_progress"})
NOT_STARTED = frozenset({"not_started"})
FAILED = frozenset({"failed"})
PASSED = frozenset({"passed"})

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class Result:
    """Одно назначение курса человеку. Живёт только в памяти загрузчика."""

    user: str
    course_id: str
    status: str
    is_overdue: bool = False
    time_spent: int | None = None
    score: float | None = None
    access_date: datetime | None = None
    completion_date: datetime | None = None


@dataclass(frozen=True)
class Counters:
    """Счётчики пиццерии (или пиццерии и курса); поле — столбец таблицы снимков.

    Только числа: проверка `test_счётчики_не_содержат_ничего_о_человеке`.
    """

    assigned: int = 0
    completed: int = 0
    in_progress: int = 0
    not_started: int = 0
    failed: int = 0
    passed: int = 0
    overdue: int = 0
    people_total: int = 0
    people_trained: int = 0
    time_sum: int = 0
    time_n: int = 0
    score_sum: float = 0.0
    score_n: int = 0
    days_sum: float = 0.0
    days_n: int = 0

    def __add__(self, other: Counters) -> Counters:
        return Counters(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )


COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(Counters))


@dataclass(frozen=True)
class Aggregate:
    """Итог по пиццерии: всего и по каждому курсу."""

    total: Counters = field(default_factory=Counters)
    courses: dict[str, Counters] = field(default_factory=dict)


def _counters(rows: Iterable[Result]) -> Counters:
    assigned = completed = in_progress = not_started = failed = passed = overdue = 0
    time_sum = time_n = score_n = days_n = 0
    score_sum = days_sum = 0.0
    for row in rows:
        assigned += 1
        done = row.status in COMPLETED
        completed += done
        in_progress += row.status in IN_PROGRESS
        not_started += row.status in NOT_STARTED
        failed += row.status in FAILED
        passed += row.status in PASSED
        overdue += row.is_overdue and not done
        if done and row.time_spent and row.time_spent > 0:
            time_sum += row.time_spent
            time_n += 1
        if row.score is not None:
            score_sum += row.score
            score_n += 1
        if done and row.access_date and row.completion_date:
            days = (row.completion_date - row.access_date).total_seconds() / SECONDS_PER_DAY
            if days >= 0:
                days_sum += days
                days_n += 1
    return Counters(
        assigned=assigned,
        completed=completed,
        in_progress=in_progress,
        not_started=not_started,
        failed=failed,
        passed=passed,
        overdue=overdue,
        time_sum=time_sum,
        time_n=time_n,
        score_sum=score_sum,
        score_n=score_n,
        days_sum=days_sum,
        days_n=days_n,
    )


def aggregate(results: Iterable[Result]) -> Aggregate:
    """Свернуть результаты одной пиццерии в счётчики; людей считает здесь же и забывает."""
    rows = list(results)
    by_course: dict[str, list[Result]] = {}
    by_user: dict[str, list[Result]] = {}
    for row in rows:
        by_course.setdefault(row.course_id, []).append(row)
        by_user.setdefault(row.user, []).append(row)
    trained = sum(1 for own in by_user.values() if all(r.status in COMPLETED for r in own))
    base = _counters(rows)
    total = Counters(
        **{
            **{f.name: getattr(base, f.name) for f in fields(base)},
            "people_total": len(by_user),
            "people_trained": trained,
        }
    )
    return Aggregate(total=total, courses={cid: _counters(own) for cid, own in by_course.items()})


def percent(part: float, whole: float) -> float | None:
    """Доля в процентах; нет знаменателя — `None` (экран пишет прочерк, не ноль)."""
    return None if whole <= 0 else part / whole * 100


def trained_pct(c: Counters) -> float | None:
    return percent(c.completed, c.assigned)


def fully_trained_pct(c: Counters) -> float | None:
    return percent(c.people_trained, c.people_total)


def pass_rate(c: Counters) -> float | None:
    return percent(c.passed, c.passed + c.failed)


def _mean(total: float, n: int) -> float | None:
    return None if n <= 0 else total / n


def avg_time(c: Counters) -> float | None:
    """Среднее время на завершённый курс, секунды."""
    return _mean(c.time_sum, c.time_n)


def avg_score(c: Counters) -> float | None:
    return _mean(c.score_sum, c.score_n)


def avg_days(c: Counters) -> float | None:
    return _mean(c.days_sum, c.days_n)
