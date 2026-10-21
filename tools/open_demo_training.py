"""Обучение открытого демо (D524): тем же загрузчиком, что у продукта, из выдуманного iSpring.

`DemoIspring` повторяет `src.learning.ispring.Client` двумя методами — дерево подразделений
и прохождения курсов по пиццерии, — а заход загрузки (`src.learning.sync.run`) сворачивает их
в счётчики и кладёт в базу, как настоящий. В iSpring демо не ходит: ключей у демо нет.

Сотрудники — номера без имён (`d3-u07`), их строки живут только в памяти загрузчика, как у
настоящего (D575). Обученность у точек разная: от отличниц до отстающей с просрочками.
Одна пиццерия iSpring (`Seaside-1`) нарочно не сопоставляется с рейтингами — экран
показывает и такие отдельным блоком.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from open_demo_ratings import COUNTRIES

from src.db.learning_store import log_load
from src.domain.training_metrics import Result
from src.learning import sync
from src.learning.ispring import Department

#: Курсы демо: id и название.
COURSES = (
    ("c-onboarding", "Onboarding: working at the pizzeria"),
    ("c-hygiene", "Food safety and hygiene"),
    ("c-dough", "Dough: rolling and proofing"),
    ("c-oven", "Oven and conveyor care"),
    ("c-service", "Guest service at the counter"),
    ("c-delivery", "Delivery packing standards"),
)
#: Доля завершённых назначений у точки, сотрудников и доля просрочек.
PROFILE = {
    "Northgate-1": (0.93, 18, 0.02),
    "Northgate-2": (0.71, 16, 0.15),
    "Riverside-1": (0.82, 14, 0.08),
    "Hillcrest-1": (0.97, 12, 0.0),
    "Harbor Bay-1": (0.78, 15, 0.1),
    "Old Town-1": (0.88, 13, 0.05),
    "Lakeside-1": (0.58, 17, 0.22),
    "Westfield-1": (0.9, 11, 0.04),
    "Seaside-1": (0.66, 9, 0.12),
}
#: Пиццерия iSpring вне сети рейтингов — в блоке «не сопоставлены».
UNMATCHED = ("Seaside-1", "AM")


def _dept(n: int) -> str:
    return f"d{n}"


class DemoIspring:
    """Выдуманный iSpring для `sync.run`: те же два метода, что у `ispring.Client`."""

    def __init__(self, units: Sequence[tuple[str, str]], today: date) -> None:
        self._today = today
        self._tree: list[Department] = [
            Department("root", "Dodo Brands", None, None),
            Department("brand", "Dodo Pizza", "root", None),
        ]
        self._units: dict[str, str] = {}
        for code, (_, title, _) in COUNTRIES.items():
            self._tree.append(Department(f"c-{code}", f"Dodo Pizza - {title}", "brand", None))
        for n, (name, country) in enumerate([*units, UNMATCHED], start=1):
            city = name.rsplit("-", 1)[0]
            self._tree.append(
                Department(_dept(n), f"{name}: {city} - Dodo Pizza", f"c-{country}", None)
            )
            self._units[_dept(n)] = name
        self._tree.append(Department("office", "Kontor: Northgate - Dodo Pizza", "c-RS", None))

    def departments(self) -> list[Department]:
        return list(self._tree)

    def results(self, department_id: str) -> tuple[list[Result], dict[str, str], int]:
        name = self._units[department_id]
        share, people, late = PROFILE[name]
        rows = [
            self._row(department_id, person, k, course, share, late)
            for person in range(people)
            for k, (course, _) in enumerate(COURSES)
        ]
        return rows, dict(COURSES), 0

    def _row(
        self, dept: str, person: int, k: int, course: str, share: float, late: float
    ) -> Result:
        """Назначение курса человеку: исход детерминирован номером строки."""
        tick = ((person * 7 + k * 3) % 100) / 100
        user = f"{dept}-u{person:02d}"
        start = datetime.combine(self._today - timedelta(days=60 - person), time(9), tzinfo=UTC)
        if tick < share:
            exam = k in (1, 3)
            return Result(
                user,
                course,
                "passed" if exam else "complete",
                time_spent=900 + 300 * k + 60 * (person % 5),
                score=float(80 + (person + k) % 21) if exam else None,
                access_date=start,
                completion_date=start + timedelta(days=2 + (person + k) % 9),
            )
        if tick < share + late:
            return Result(user, course, "in_progress", is_overdue=True, access_date=start)
        if k == 1 and person % 2:
            return Result(user, course, "failed", score=55.0, access_date=start)
        return Result(user, course, "not_started" if person % 3 else "in_progress")


def seed(units: Sequence[tuple[str, str]], today: date) -> str:
    """Один заход загрузки из выдуманного iSpring; журнал загрузок — «удачно»."""
    summary = sync.run(DemoIspring(units, today), today=today)  # type: ignore[arg-type]
    log_load(ok=True, departments=summary.departments, results=summary.results)
    if summary.matched != len(units):
        raise RuntimeError(
            f"обучение демо: сопоставлено {summary.matched} пиццерий из {len(units)}"
        )
    return (
        f"training: {summary.pizzerias} pizzerias, {summary.matched} matched, "
        f"{summary.results} assignments"
    )
