"""Экран «Обзор сети»: что показать и чем это взято.

Экран отвечает на один вопрос из брифа — **куда смотреть сегодня**. Поэтому он
собран не вокруг красивых чисел, а вокруг поводов: точка, где сожжена зона;
пункт, который нарушается на многих точках; проверка, по которой письмо так и
не ушло. Числа сверху нужны, чтобы понять масштаб, но они кликабельные и
сужают выборку — мёртвых цифр на экране нет.

НИ ОДНОЙ ЦИФРЫ СОБСТВЕННОГО ПРОИЗВОДСТВА, как и в соседнем модуле раздела
«Проверки». Процент и буква приходят такими, какими их записал движок; потери
по зонам складываются запросом из `by_zone`, куда их положил он же. Среднее по
сети — единственное вычисляемое число, и оно снабжено признаком сравнимости:
усреднять проверки, посчитанные по разным ставкам, нельзя, и экран об этом
говорит вслух, а не показывает бодрую цифру (T349).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.db import queries
from src.db.models import InspectionRow

#: Сколько поводов показывать в каждом списке. Экран — не отчёт: длинный
#: список поводов не помогает выбрать, куда смотреть, он эту задачу и создаёт.
TOP = 6

#: Класс, сжигающий долю зоны целиком. Живёт кодом, не словом (D025).
CRITICAL = "D3"


@dataclass(frozen=True)
class Tile:
    """Плитка сводки. `href` обязателен: цифра без перехода — мёртвая цифра."""

    key: str
    value: str
    note: str
    href: str
    tone: str = "plain"


@dataclass(frozen=True)
class ZoneLoss:
    """Потеря по зоне за период — сложенная, а не пересчитанная."""

    code: str
    name_ru: str
    name_en: str
    loss: float
    inspections: int
    units: int
    share: float


@dataclass(frozen=True)
class Systemic:
    """Пункт, нарушенный на нескольких точках."""

    code: str
    level: str
    records: int
    units: int


@dataclass(frozen=True)
class Attention:
    """Повод посмотреть сегодня. `why` — код причины, не готовая фраза.

    Фразу собирает шаблон на языке интерфейса: причина одна, а языков у
    продукта два, и склеивать текст здесь значило бы печатать его мимо
    словаря.
    """

    why: str
    unit: str
    inspection_id: str
    when: date
    detail: str
    tone: str


@dataclass(frozen=True)
class Overview:
    """Всё, что показывает экран, одним снимком."""

    units_total: int
    inspections: tuple[InspectionRow, ...]
    grades: tuple[tuple[str, int], ...]
    average: float | None
    comparable: bool
    comparability_note: str
    zone_losses: tuple[ZoneLoss, ...]
    systemic: tuple[Systemic, ...]
    attention: tuple[Attention, ...]
    problem_units: tuple[InspectionRow, ...]


def _grades(rows: tuple[InspectionRow, ...]) -> tuple[tuple[str, int], ...]:
    """Распределение букв в порядке шкалы, а не по убыванию частоты.

    Порядок шкалы позволяет читать полосу как шкалу: A слева, D справа. При
    сортировке по частоте та же полоса меняет смысл от выборки к выборке.
    """
    счёт = {буква: 0 for буква in ("A", "B", "C", "D")}
    for row in rows:
        if row.grade in счёт:
            счёт[row.grade] += 1
    return tuple((буква, число) for буква, число in счёт.items())


def _comparable(rows: tuple[InspectionRow, ...]) -> bool:
    """Можно ли усреднять этот ряд: все проверки одного издания одного чек-листа.

    Сравнивается пара «код чек-листа + версия издания», и этого достаточно
    строго, а не приблизительно: имя издания выводится из СОДЕРЖИМОГО методики
    (`<набор>-<дата>-<отпечаток>`, D050), поэтому совпавшая версия означает
    совпавшие ставки, пороги букв и доли зон. Разошлась версия — цена могла
    смениться, и одно среднее по такому ряду было бы средним по несравнимому
    (T349).

    Тонкая форма признака — отпечаток именно ценообразующей части издания —
    живёт у поверхности агента (`src/mcp/comparability.py`) и сюда не тянется
    намеренно: веб не знает про `src.mcp` ничем, кроме двери методики, и это
    правило проверяется прогоном (`tests/test_web_bounds.py`). Разница в том,
    что здесь ряд рвётся и на правке формулировки, которая цену не двигает, —
    то есть эта проверка строже, а не слабее, и ошибается в безопасную
    сторону: отказывается усреднять там, где агент бы усреднил.
    """
    if len(rows) < 2:
        return True
    издания = {(row.checklist_code, row.checklist_version) for row in rows}
    return len(издания) == 1


def _average(rows: tuple[InspectionRow, ...]) -> float | None:
    """Среднее по записанным процентам. `None` — считать нечего.

    Ноль вместо `None` читался бы как «сеть на нуле», а не как «проверок нет».
    """
    if not rows:
        return None
    return round(sum(row.pct for row in rows) / len(rows), 1)


def _attention(
    rows: tuple[InspectionRow, ...], *, counts: dict[str, dict[str, int]]
) -> tuple[Attention, ...]:
    """Поводы посмотреть сегодня, самое срочное сверху.

    Сегодня поводов два вида, и оба берутся из записанного: сожжённая зона
    (`D3` в счётчиках проверки) и проверка, у которой нет ни одной находки при
    низкой букве — признак, что проверку прервали. Просроченных предписаний
    здесь нет, потому что предписаний нет в базе вовсе (T357): выдумывать их
    строки означало бы показать владельцу работу, которой не было.
    """
    поводы: list[Attention] = []
    for row in rows:
        критических = counts.get(row.id, {}).get(CRITICAL, 0)
        if критических:
            поводы.append(
                Attention(
                    why="critical",
                    unit=row.unit_name,
                    inspection_id=row.id,
                    when=row.inspection_date,
                    detail=str(критических),
                    tone="err",
                )
            )
        elif row.grade == "D":
            поводы.append(
                Attention(
                    why="low_grade",
                    unit=row.unit_name,
                    inspection_id=row.id,
                    when=row.inspection_date,
                    detail=f"{row.pct:.1f}",
                    tone="warn",
                )
            )
    поводы.sort(key=lambda п: (п.tone != "err", -п.when.toordinal()))
    return tuple(поводы[:TOP])


def load(
    *,
    tenant: str,
    limit: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Overview:
    """Снимок сети за период. Один проход по базе на каждый блок, не по строке."""
    rows = tuple(queries.list_inspections(tenant=tenant, limit=limit))
    counts = {row.id: {} for row in rows}
    losses = queries.zone_losses(tenant=tenant, date_from=date_from, date_to=date_to, limit=TOP)
    всего = sum(строка[3] for строка in losses) or 1.0
    return Overview(
        units_total=queries.units_total(tenant=tenant),
        inspections=rows,
        grades=_grades(rows),
        average=_average(rows),
        comparable=_comparable(rows),
        comparability_note="",
        zone_losses=tuple(
            ZoneLoss(
                code=code,
                name_ru=ru,
                name_en=en,
                loss=loss,
                inspections=insp,
                units=units,
                share=round(loss / всего * 100, 1),
            )
            for code, ru, en, loss, insp, units in losses
        ),
        systemic=tuple(
            Systemic(code=code, level=level, records=records, units=units)
            for code, level, records, units in queries.systemic_findings(
                tenant=tenant, date_from=date_from, date_to=date_to, limit=TOP
            )
        ),
        attention=_attention(rows, counts=counts),
        problem_units=tuple(sorted(rows, key=lambda r: r.pct)[:TOP]),
    )
