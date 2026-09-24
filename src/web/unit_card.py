"""Карточка точки: где пиццерия сейчас, куда движется и что у неё не чинится.

Ни одна цифра здесь не считается заново. Проценты, буквы, доли зон и потери
приходят такими, какими их записал движок при завершении проверки, — экран
только раскладывает записанное (CLAUDE.md, «Оценку не считать заново»).
Единственное, что этот модуль вычисляет сам, — высота столбика на полосе
движения, и это свойство картинки, а не оценка.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from ..db import queries
from ..db.models import FindingRow, InspectionRow

#: Сколько последних проверок показывает полоса движения и по скольким
#: считается повтор. Цифра из прототипа владельца: шесть обходов — это около
#: полутора лет плановых проверок, на таком окне повтор уже видно, а случайное
#: совпадение ещё не выглядит системой.
ОКНО = 6

#: Столбик ниже этого не рисуется: проверка с худшим процентом ряда обязана
#: остаться видимой полоской, иначе она читается как «проверки не было».
МИНИМУМ_СТОЛБИКА = 6.0


@dataclass(frozen=True)
class Bar:
    """Один столбик полосы движения оценки."""

    inspection_id: str
    on: date
    pct: float
    grade: str
    #: Высота в процентах поля. Считается от обрезанной шкалы (см. `_floor`),
    #: поэтому сама по себе цифрой оценки не является и на экран не выводится.
    height: float
    #: Того же издания методики, что и последняя проверка. Разошлось —
    #: столбик стоит рядом, но сравнивать его высоту с соседями нельзя.
    comparable: bool


@dataclass(frozen=True)
class WeakZone:
    """Слабый блок последней проверки."""

    code: str
    name: str
    share: float
    loss: float
    #: Зона обнулена нарушением класса D3: её доля сгорела целиком.
    zeroed: bool


@dataclass(frozen=True)
class Repeat:
    """Нарушение, встретившееся в окне больше одного раза."""

    code: str
    text: str
    zone: str
    #: По отметке на каждую проверку окна, слева старая. `True` — в той
    #: проверке нарушение записано.
    marks: tuple[bool, ...]
    times: int


@dataclass(frozen=True)
class UnitCard:
    """Всё, что показывает экран точки, одним снимком."""

    name: str
    city: str
    country: str
    partner: str
    audits_count: int
    last: InspectionRow | None
    bars: tuple[Bar, ...]
    #: Нижняя граница шкалы столбиков. Обрезанная ось без подписи — вранье
    #: картинкой, поэтому граница уезжает на экран и подписывается там.
    floor: float
    comparable: bool
    weak: tuple[WeakZone, ...] = ()
    last_findings: tuple[FindingRow, ...] = ()
    repeats: tuple[Repeat, ...] = ()


def _floor(rows: tuple[InspectionRow, ...]) -> float:
    """Нижняя граница шкалы движения.

    Полный диапазон 0–100 для оценок 89–99 показывает шесть одинаковых
    столбиков и прячет ровно то, ради чего блок нужен. Ось обрезается, но
    граница возвращается наружу и подписывается на экране: обрезанная ось,
    о которой не сказано, преувеличивает разницу и читается как обвал.
    """
    if not rows:
        return 0.0
    низ = min(row.pct for row in rows)
    return max(0.0, math.floor((низ - 2) / 5) * 5)


def _bars(
    rows: tuple[InspectionRow, ...], *, floor: float, издание: tuple[str, str] | None
) -> tuple[Bar, ...]:
    """Столбики от старой проверки к свежей."""
    высота_поля = 100.0 - floor
    столбики = []
    for row in rows:
        доля = 100.0 if высота_поля <= 0 else (row.pct - floor) / высота_поля * 100.0
        столбики.append(
            Bar(
                inspection_id=row.id,
                on=row.inspection_date,
                pct=row.pct,
                grade=row.grade,
                height=round(max(МИНИМУМ_СТОЛБИКА, min(100.0, доля)), 1),
                comparable=(
                    издание is None
                    or (row.checklist_code, row.checklist_version) == издание
                ),
            )
        )
    return tuple(столбики)


def _weak(by_zone: dict[str, object], *, lang: str, limit: int = 5) -> tuple[WeakZone, ...]:
    """Зоны последней проверки, где потеряны проценты, — тяжёлые первыми.

    Читается снимок зоны, записанный движком: ключ потерь — `loss`. Имя поля
    здесь не угадывается, его сторожит `tests/test_db_zone_snapshot_keys.py`:
    экран уже показывал «потерь не записано» при записанных двадцати двух
    процентах, потому что спрашивал несуществующий ключ (#354).
    """
    зоны = []
    for код, снимок in by_zone.items():
        if not isinstance(снимок, dict):
            continue
        потеря = снимок.get("loss")
        if потеря is None:
            continue
        имя = снимок.get("name_en" if lang == "en" else "name_ru") or код
        зоны.append(
            WeakZone(
                code=код,
                name=str(имя),
                share=float(снимок.get("share") or 0.0),
                loss=float(потеря),
                zeroed=bool(снимок.get("zeroed")),
            )
        )
    зоны.sort(key=lambda z: (-z.loss, z.code))
    return tuple(z for z in зоны if z.loss > 0)[:limit]


def _repeats(
    findings: tuple[FindingRow, ...], *, окно: tuple[str, ...], limit: int = 8
) -> tuple[Repeat, ...]:
    """Что не чинится: коды, записанные больше чем в одной проверке окна.

    Повтор считается здесь, а не в базе, намеренно: выборка находок отдаёт
    записанное, а обобщение — ответственность спрашивающего (см. docstring
    `queries.findings_by_unit`). Считается он по КОДУ пункта, не по
    формулировке: формулировки переводятся и правятся, коды нет.
    """
    место = {ид: n for n, ид in enumerate(окно)}
    отметки: dict[str, list[bool]] = {}
    образец: dict[str, FindingRow] = {}
    for f in findings:
        n = место.get(f.inspection_id)
        if n is None:
            continue
        ряд = отметки.setdefault(f.code, [False] * len(окно))
        ряд[n] = True
        образец.setdefault(f.code, f)
    повторы = [
        Repeat(
            code=код,
            text=(образец[код].text or "").strip(),
            zone=образец[код].zone,
            marks=tuple(ряд),
            times=sum(ряд),
        )
        for код, ряд in отметки.items()
        if sum(ряд) > 1
    ]
    повторы.sort(key=lambda r: (-r.times, r.code))
    return tuple(повторы)[:limit]


def load(*, tenant: str, unit: str, lang: str = "ru", окно: int = ОКНО) -> UnitCard:
    """Снимок одной точки. Пусто — значит проверок не было, и так и сказано."""
    ряд = tuple(queries.list_inspections(tenant=tenant, unit=unit, limit=max(окно, 1)))
    if not ряд:
        return UnitCard(
            name=unit,
            city="",
            country="",
            partner="",
            audits_count=0,
            last=None,
            bars=(),
            floor=0.0,
            comparable=True,
        )
    # Выборка отдаёт свежие первыми; полоса движения читается слева направо от
    # старой к новой, как в любом графике времени.
    по_времени = tuple(reversed(ряд))
    последняя = ряд[0]
    издание = (последняя.checklist_code, последняя.checklist_version)
    floor = _floor(по_времени)
    столбики = _bars(по_времени, floor=floor, издание=издание)
    detail = queries.get_inspection(последняя.id, tenant=tenant)
    находки = tuple(queries.findings_by_unit(tenant=tenant, unit=unit, limit=окно * 60))
    # География — у точки, а не у шапки проверки: город в шапке аудитор пишет
    # строкой, и «Belgrade» с «Белградом» разъезжаются (docstring
    # `queries.unit_geography`). Пусто в справочнике — показываем шапку, это
    # лучше пустого места, но источником считается справочник.
    страна, город = queries.unit_geography(tenant=tenant).get(последняя.unit_name, ("", ""))
    return UnitCard(
        name=последняя.unit_name,
        city=город or последняя.city,
        country=страна,
        partner=последняя.partner,
        audits_count=len(ряд),
        last=последняя,
        bars=столбики,
        floor=floor,
        comparable=all(b.comparable for b in столбики),
        weak=_weak(detail.by_zone if detail else {}, lang=lang),
        last_findings=tuple(detail.findings) if detail else (),
        repeats=_repeats(находки, окно=tuple(row.id for row in по_времени)),
    )
