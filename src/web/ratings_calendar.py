"""Период раздела «Рейтинги»: «‹ 2026 Q3 ›», по щелчку — календарь «с — по».

Правило владельца (скилл `interface-logic`, п. 3): период — календарь «с — по» и
стрелки, без рядов кнопок. Прежняя сетка кварталов, месяцев и списка периодов РС
(D357) снята 11.10.2026 (D395). 23.10.2026 (D630) в окно периода вернулись списки —
выпадающие, не кнопки: «Период РС» и «Неделя РКО». Календарь и списки — два входа
в один отрезок: выбор в списке ставит календарь на этот отрезок, отрезок календаря,
совпавший с периодом РС или неделей РКО, выбран в своём списке.

Месяц, квартал и период РС узнаются по отрезку (`periods.range_period`). Неделя РКО
отдельного вида ключа не имеет — это обычный отрезок `YYYY-MM-DD..YYYY-MM-DD`
(старые ссылки работают как были); узнаётся она здесь, по границам периода РКО.

Стрелка листает на длину выбранного периода и ведёт только туда, где есть
данные. Ни одного вычисления оценок — только ключи периодов (`periods`).

Периоды рейтинга внутри месяца или квартала (контролинг 05.11.2026): под отбором —
строка «целиком» и периоды рейтинга раздела (у РС — его периоды по имени, у РКО —
недели датами), задевшие выбранный месяц или квартал. Пункт открывает один период рейтинга,
а месяц или квартал едет в адресе (`within=`), чтобы строка и стрелки в ней остались
и было куда вернуться. Периоды — по тому же правилу, что данные (D396): задевшие
отрезок хотя бы днём.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.ratings import periods as rp

from .texts import t


@dataclass(frozen=True)
class Option:
    """Пункт списка периодов: ключ для адреса, подпись, выбран ли."""

    key: str
    title: str
    on: bool


@dataclass(frozen=True)
class Inside:
    """Периоды рейтинга внутри месяца или квартала: ключ и имя «целиком», пункты
    (старые первыми) и соседи выбранного для стрелок строки."""

    parent_key: str
    parent_title: str
    whole_on: bool
    items: tuple[Option, ...]
    prev: str | None
    next: str | None


@dataclass(frozen=True)
class Calendar:
    title: str
    prev: str | None
    next: str | None
    begin: date
    end: date
    rs_options: tuple[Option, ...] = ()
    rko_options: tuple[Option, ...] = ()
    inside: Inside | None = None


def _rs_title(p: rp.RatingPeriod, lang: str) -> str:
    return p.title_ru if lang == "ru" else p.title_en


def week_title(begin: date, end: date) -> str:
    """Неделя РКО словами: «12.10 — 18.10.2026»."""
    return f"{begin:%d.%m} — {end:%d.%m.%Y}"


def _is_rko_week(period: rp.ReportPeriod, rko: tuple[rp.RatingPeriod, ...]) -> bool:
    return any((p.begin_on, p.end_on) == (period.begin, period.end) for p in rko)


def _title(
    period: rp.ReportPeriod,
    rs: tuple[rp.RatingPeriod, ...],
    rko: tuple[rp.RatingPeriod, ...],
    lang: str,
) -> str:
    if period.kind == rp.KIND_MONTH:
        return f"{t(f'ratings.month.{period.begin.month}', lang)} {period.begin.year}"
    if period.kind == rp.KIND_QUARTER:
        return f"{period.begin.year} Q{(period.begin.month - 1) // 3 + 1}"
    found = next((p for p in rs if f"rs:{p.id}" == period.key), None)
    if found:
        return _rs_title(found, lang)
    if period.kind == rp.KIND_RANGE and _is_rko_week(period, rko):
        return week_title(period.begin, period.end)
    return f"{period.begin:%d.%m.%Y} — {period.end:%d.%m.%Y}"


def _same_span(p: rp.RatingPeriod, selected: rp.ReportPeriod) -> bool:
    return (p.begin_on, p.end_on) == (selected.begin, selected.end)


def _rs_options(
    selected: rp.ReportPeriod, rs: tuple[rp.RatingPeriod, ...], lang: str
) -> tuple[Option, ...]:
    """Периоды РС, новые первыми; выбран тот, что совпал с отрезком."""
    ordered = sorted(rs, key=lambda p: p.begin_on, reverse=True)
    return tuple(Option(f"rs:{p.id}", _rs_title(p, lang), _same_span(p, selected)) for p in ordered)


def _rko_options(selected: rp.ReportPeriod, rko: tuple[rp.RatingPeriod, ...]) -> tuple[Option, ...]:
    """Недели РКО, новые первыми; ключ — обычный отрезок «с..по»."""
    ordered = sorted(rko, key=lambda p: p.begin_on, reverse=True)
    return tuple(
        Option(
            _rko_key(p),
            week_title(p.begin_on, p.end_on),
            _same_span(p, selected),
        )
        for p in ordered
    )


def span_title(begin: date, end: date) -> str:
    """Неделя РКО датами в строке «внутри месяца»: «05.10 — 11.10»."""
    return f"{begin:%d.%m} — {end:%d.%m}"


def _rko_key(p: rp.RatingPeriod) -> str:
    return f"{p.begin_on.isoformat()}..{p.end_on.isoformat()}"


def _inside(
    selected: rp.ReportPeriod,
    within: rp.ReportPeriod | None,
    kind: str | None,
    rs: tuple[rp.RatingPeriod, ...],
    rko: tuple[rp.RatingPeriod, ...],
    lang: str,
) -> Inside | None:
    """Строка периодов рейтинга раздела `kind` («rs» / «rko») внутри месяца или квартала.

    Выбран месяц или квартал — он и есть «целиком». Выбран один период рейтинга и в
    адресе месяц или квартал (`within`), в который этот период входит, — строка
    остаётся. Иначе строки нет: произвольный отрезок и разделы без периодов рейтинга
    (карты, агрегаторы…) её не получают.
    """
    whole = (rp.KIND_MONTH, rp.KIND_QUARTER)
    if kind not in ("rs", "rko"):
        return None
    parent = selected if selected.kind in whole else within
    if parent is None or parent.kind not in whole:
        return None
    source = rs if kind == "rs" else rko
    touching = sorted(
        (p for p in source if p.end_on >= parent.begin and p.begin_on <= parent.end),
        key=lambda p: p.begin_on,
    )
    if not touching:
        return None
    # У РС — имя периода («Октябрь 1»), а не даты: даты периода РС мы пока выводим
    # из подписи листа контроля (1–15 и 16–конец), а настоящие в Dodo IS другие
    # (05.10–18.10, 19.10–02.11). Пока даты не берутся из Dodo IS, неверных не показываем.
    # У РКО подпись листа — сами даты недели, им верить можно.
    items = tuple(
        Option(
            f"rs:{p.id}" if kind == "rs" else _rko_key(p),
            _rs_title(p, lang) if kind == "rs" else span_title(p.begin_on, p.end_on),
            _same_span(p, selected),
        )
        for p in touching
    )
    whole_on = selected.key == parent.key
    on = next((i for i, o in enumerate(items) if o.on), None)
    if not whole_on and on is None:
        return None  # в адресе чужой месяц: выбранный период в него не входит
    prev: str | None
    nxt: str | None
    if on is None:
        prev, nxt = None, items[0].key
    else:
        prev = items[on - 1].key if on > 0 else None
        nxt = items[on + 1].key if on + 1 < len(items) else None
    return Inside(parent.key, _title(parent, rs, rko, lang), whole_on, items, prev, nxt)


def build(
    selected: rp.ReportPeriod,
    data_months: tuple[date, ...],
    rs_periods: tuple[rp.RatingPeriod, ...],
    lang: str,
    rko_periods: tuple[rp.RatingPeriod, ...] = (),
    *,
    kind: str | None = None,
    within: rp.ReportPeriod | None = None,
) -> Calendar:
    first = min(data_months, default=None)
    last = max(data_months, default=None)

    def reachable(period: rp.ReportPeriod | None) -> str | None:
        """Сосед, в котором есть хоть один месяц с данными."""
        if period is None or first is None or last is None:
            return None
        if period.end < first or period.begin > rp.month_period(last.year, last.month).end:
            return None
        return period.key

    return Calendar(
        title=_title(selected, rs_periods, rko_periods, lang),
        prev=reachable(rp.previous_period(selected, rs_periods=rs_periods)),
        next=reachable(rp.next_period(selected, rs_periods=rs_periods)),
        begin=selected.begin,
        end=selected.end,
        rs_options=_rs_options(selected, rs_periods, lang),
        rko_options=_rko_options(selected, rko_periods),
        inside=_inside(selected, within, kind, rs_periods, rko_periods, lang),
    )
