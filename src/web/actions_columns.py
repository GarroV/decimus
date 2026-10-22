"""«Столбец стран слева, блоки по состоянию справа» — «ОСБ» и «Действия» (D611).

Шапок из рядов чипов нет: страна — строка столбца (на телефоне — выпадающий
список), очередь — блок справа со своим счётчиком. Модуль собирает для шаблонов
`actions/_columns.html` одинаковые части — столбец (`RailItem`) и блоки
(`Block`); читает данные только дверями с охватом вошедшего.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import request, url_for

from src.db import prescriptions as rx

from . import auth
from . import country as country_data

#: Ключ параметра «показать закрытые» в адресе.
PARAM_CLOSED = "closed"


@dataclass(frozen=True)
class RailItem:
    """Строка столбца стран: код ('' — «Все страны»), счётчики того, что ждёт, и просрочка."""

    code: str
    parts: tuple[tuple[str, int], ...]
    alert: int = 0


@dataclass(frozen=True)
class Block:
    """Блок справа: состояние, строки, счётчик; закрытые лежат свёрнутыми (`load_url`)."""

    key: str
    title_key: str
    rows: tuple[Any, ...]
    count: int | None = None
    load_url: str = ""


def sorted_rows(rows: Iterable[Any], *, today: date, overdue_first: bool) -> tuple[Any, ...]:
    """Строки по сроку (при равном — как пришли); просроченные сверху, если блок просит."""
    return tuple(sorted(rows, key=lambda p: (not (overdue_first and p.overdue(today)), p.due_on)))


# ── предписания ────────────────────────────────────────────────────────────

#: Блоки предписаний в порядке показа: ключ, статус базы, ключ заголовка.
RX_BLOCKS = (
    ("review", rx.STATUS_REVIEW, "rx.block.review"),
    ("approved", rx.STATUS_APPROVED, "rx.block.approved"),
    ("active", rx.STATUS_ISSUED, "rx.block.active"),
    ("drafts", rx.STATUS_DRAFT, "rx.block.drafts"),
)
#: Что показывает столбец у страны: на согласовании, согласовано, действуют.
_RX_RAIL = (
    ("review", rx.STATUS_REVIEW, "rx.rail.review"),
    ("approved", rx.STATUS_APPROVED, "rx.rail.approved"),
    ("active", rx.STATUS_ISSUED, "rx.rail.active"),
)


def rx_rail_item(code: str, rows: tuple[rx.Prescription, ...], today: date) -> RailItem:
    """Счётчики страны: сколько на согласовании, согласовано, действует; просрочено — отдельно."""
    parts = tuple(
        (text, n)
        for _, status, text in _RX_RAIL
        if (n := sum(1 for p in rows if p.status == status))
    )
    return RailItem(code, parts, sum(1 for p in rows if p.overdue(today)))


def rx_blocks(
    rows: tuple[rx.Prescription, ...],
    *,
    today: date,
    closed: tuple[rx.Prescription, ...] | None,
    closed_count: int | None,
    load_url: str,
) -> tuple[Block, ...]:
    """Открытые блоки без пустых и «Закрытые» — свёрнутые, пока их не попросили."""
    blocks = tuple(
        Block(key, title, sorted_rows(chosen, today=today, overdue_first=key == "active"))
        for key, status, title in RX_BLOCKS
        if (chosen := tuple(p for p in rows if p.status == status))
    )
    if closed is None:
        return (*blocks, Block("closed", "rx.block.closed", (), closed_count, load_url))
    return (*blocks, Block("closed", "rx.block.closed", closed, len(closed)))


def rx_screen(
    lang: str,
    *,
    endpoint: str,
    fixed: Mapping[str, str],
    count_closed: bool,
    empty_key: str,
    title_key: str,
) -> dict[str, Any]:
    """Список предписаний для «ОСБ» и вкладки «Предписания»: страна и «закрытые» живут в адресе."""
    страна = country_data.normalize_code(request.args.get("country") or "")
    закрытые_нужны = request.args.get(PARAM_CLOSED) == "1"
    reach = auth.current_reach()
    сегодня = rx.today()

    открытые = rx.list_prescriptions(reach=reach)
    закрытые = rx.list_prescriptions(reach=reach, closed=True) if закрытые_нужны else None
    страны = tuple(
        sorted(
            {p.country for p in открытые.rows}
            | {p.country for p in (закрытые.rows if закрытые else ())}
            | {страна} - {""}
        )
    )

    def в_стране(rows: tuple[rx.Prescription, ...]) -> tuple[rx.Prescription, ...]:
        return tuple(p for p in rows if not страна or p.country == страна)

    def адрес(**изменения: str) -> str:
        параметры: dict[str, Any] = {
            **fixed,
            "country": страна,
            PARAM_CLOSED: "1" if закрытые_нужны else "",
            "lang": lang,
            **изменения,
        }
        return url_for(endpoint, **{k: v for k, v in параметры.items() if v})

    видимые = в_стране(открытые.rows)
    число_закрытых = (
        rx.status_counts(reach=reach, country=страна or None)[rx.STATUS_CLOSED]
        if count_closed
        else None
    )
    закрытые_в_стране = в_стране(закрытые.rows) if закрытые else ()
    блоки = rx_blocks(
        видимые,
        today=сегодня,
        closed=закрытые_в_стране if закрытые else None,
        closed_count=число_закрытых,
        load_url=адрес(**{PARAM_CLOSED: "1"}),
    )
    столбец = (
        (
            rx_rail_item("", открытые.rows, сегодня),
            *(
                rx_rail_item(c, tuple(p for p in открытые.rows if p.country == c), сегодня)
                for c in страны
            ),
        )
        if len(страны) > 1 or страна
        else ()
    )
    return {
        "title_key": title_key,
        "rail": столбец,
        "rail_form": rail_form(
            endpoint, fixed, lang, {PARAM_CLOSED: "1" if закрытые_нужны else ""}
        ),
        "blocks": блоки,
        "countries": страны,
        "country": страна,
        "empty_key": empty_key,
        "truncated": открытые.truncated,
        "truncated_key": "rx.truncated",
        "limit": rx.LIST_LIMIT,
        "total": len(видимые) + len(закрытые_в_стране),
        "select_url": адрес,
        "archive_param": PARAM_CLOSED,
    }


def rail_form(
    endpoint: str, fixed: Mapping[str, str], lang: str, extra: Mapping[str, str]
) -> tuple[str, dict[str, str]]:
    """Форма выпадающего списка стран (телефон): куда отправить и что оставить в адресе."""
    keep = {**fixed, "lang": lang, **extra}
    return url_for(endpoint), {k: v for k, v in keep.items() if v}
