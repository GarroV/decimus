"""Общее письмо партнёру по нескольким проверкам одной страны (D739).

Одиночное письмо (`letters.py`) остаётся как есть; это — дополнительная возможность для
выезда, где в одной стране проверили несколько пиццерий. Две вещи здесь важнее остальных.

**Правило выбора — ядро (`check_selection`).** Только принятые проверки одной страны и
одного пространства, не меньше двух, а между самой ранней и самой поздней датой обхода
не больше `MAX_SPREAD_DAYS` дней: так в письмо случайно не попадает прошлый выезд.
Нарушение — отказ с объяснением (`BatchLetterError.code` и факты), а не тихое отсечение
лишнего. Проверка стоит на сервере у каждой двери (веб, MCP): браузер её не заменяет.

**Сборка — только из записанного, без пересчёта.** Каждая проверка идёт тем же путём,
что одиночное письмо: методика прибивается к версии проверки, движок сверяется с
записанной оценкой, наружу идёт записанная оценка. Не сошлась хоть одна — общего письма
нет, а в отказе названо, какая и почему. Слова проверки (находки, обратная связь
аудитора, срок) приходят от движка (`engine/report.py letter-parts`); этот модуль только
складывает их в один текст: таблицу результатов, итог одной фразой и «что сделать»
строит код по фактам, модель цифр не пишет.

**Срок «устранить до» один на всё письмо** и считается как у одиночного письма — от
самой поздней проверки: ответ аудитора о плане действий, а нет его — дата проверки плюс
стандартный срок методики (`plan_due_days`). Правила сроков прорабатываются отдельно
(#1580); здесь заведено только это.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..db.models import InspectionDetail
from .batch_letter_texts import say
from .engine_call import clean as _clean
from .letters import (
    BLANK_TEXT_FIELD,
    FEEDBACK_LANG_FIELD,
    FINDING_TEXT_FIELD,
    PLAN_DUE_FIELD,
    REPORT_SCRIPT,
    LetterError,
    Papers,
    _blank_wordings,
    _lang,
    _methodology,
    _run,
    _template,
    _verify,
    _wording_langs,
    current_edition,
    refuse_uploaded,
    state_json,
)

#: Сколько дней может быть между самой ранней и самой поздней проверкой общего письма.
MAX_SPREAD_DAYS = 7
#: Меньше двух проверок общего письма не бывает — для одной есть одиночное.
MIN_INSPECTIONS = 2

#: Оценки, при которых пиццерия «не прошла»: критическое нарушение сжигает зону (D3).
FAILING_GRADES = ("D", "F")
BELOW_GRADE = "C"

#: Чего не хватает общему письму, когда у проверок записаны РАЗНЫЕ сроки плана действий:
#: в письмо идёт срок самой поздней, остальные в нём не видны.
PLAN_DUE_DIFFERS_FIELD = "action plan deadlines differ between inspections"

#: Коды отказов правила выбора и сборки; словами их называет интерфейс (RU/EN).
REFUSAL_CODES = (
    "too_few",
    "duplicate",
    "not_accepted",
    "uploaded",
    "retracted",
    "other_space",
    "other_country",
    "spread",
    "unit_failed",
)


class BatchLetterError(LetterError):
    """Общее письмо по этому выбору собрать нельзя, и вот почему.

    `code` — один из `REFUSAL_CODES`, `facts` — то, что нужно для фразы (интерфейс
    собирает её на своём языке); `str()` — та же причина по-русски, как у соседних
    отказов письма: MCP отдаёт её клиенту как есть.
    """

    def __init__(self, code: str, message: str, **facts: object) -> None:
        super().__init__(message)
        self.code = code
        self.facts = facts


def _label(detail: InspectionDetail) -> str:
    row = detail.inspection
    return f"{row.unit_name} ({row.inspection_date.strftime('%d.%m.%Y')})"


def check_selection(
    details: Sequence[InspectionDetail], *, tenant: str, country: str = ""
) -> tuple[InspectionDetail, ...]:
    """Правило выбора проверок для общего письма; годный выбор — по датам, старые первыми.

    `tenant` — пространство того, кто собирает письмо: проверки других пространств в
    письмо не входят (D726). `country` — страна экрана, с которого письмо открыто; пусто —
    страна берётся из проверок, но она обязана быть одной и известной.
    """
    rows = [d.inspection for d in details]
    if len({r.id for r in rows}) != len(rows):
        raise BatchLetterError(
            "duplicate", "Одна и та же проверка названа в выборе дважды — письмо не собрано"
        )
    if len(rows) < MIN_INSPECTIONS:
        raise BatchLetterError(
            "too_few",
            f"Для общего письма нужно не меньше {MIN_INSPECTIONS} проверок, выбрано {len(rows)}. "
            f"Одну проверку отправляют одиночным письмом",
            n=len(rows),
            minimum=MIN_INSPECTIONS,
        )
    for detail, row in zip(details, rows, strict=True):
        if row.tenant_code != tenant:
            raise BatchLetterError(
                "other_space",
                f"Проверка {_label(detail)} принадлежит другому пространству — в общее письмо "
                f"входят только проверки своего",
                unit=row.unit_name,
            )
        if row.retracted:
            raise BatchLetterError(
                "retracted",
                f"Проверка {_label(detail)} снята из истории — в общее письмо она не входит",
                unit=row.unit_name,
            )
        if row.on_review:
            raise BatchLetterError(
                "not_accepted",
                f"Проверка {_label(detail)} ещё не принята (идёт вычитка) — в общее письмо "
                f"входят только принятые",
                unit=row.unit_name,
            )
        if row.is_uploaded:
            raise BatchLetterError(
                "uploaded",
                f"Проверка {_label(detail)} загружена задним числом — письма по ней нет (D310)",
                unit=row.unit_name,
            )
    countries = {r.unit_country.strip().upper() for r in rows}
    if country:
        countries.add(country.strip().upper())
    if len(countries) != 1 or "" in countries:
        raise BatchLetterError(
            "other_country",
            "Проверки относятся к разным странам или страна пиццерии не указана — общее письмо "
            "собирается по одной стране",
            countries=", ".join(sorted(c for c in countries if c)),
        )
    first = min(r.inspection_date for r in rows)
    last = max(r.inspection_date for r in rows)
    days = (last - first).days
    if days > MAX_SPREAD_DAYS:
        raise BatchLetterError(
            "spread",
            f"Между самой ранней ({first.strftime('%d.%m.%Y')}) и самой поздней "
            f"({last.strftime('%d.%m.%Y')}) проверкой {days} дн., а общее письмо — не больше "
            f"{MAX_SPREAD_DAYS}: так в него не попадает прошлый выезд. Уберите лишние проверки",
            first=first.isoformat(),
            last=last.isoformat(),
            days=days,
            maximum=MAX_SPREAD_DAYS,
        )
    return tuple(
        sorted(
            details,
            key=lambda d: (d.inspection.inspection_date, d.inspection.unit_name, d.inspection.id),
        )
    )


# --- сборка: слова проверки от движка ------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """Одна проверка общего письма: записанная строка и слова от движка (сверка пройдена)."""

    detail: InspectionDetail
    parts: Mapping[str, Any]
    #: Коды невосстановленного именно по этой проверке (`letters.build` знает те же).
    caveats: tuple[str, ...] = ()


def piece_for(detail: InspectionDetail, *, lang: str, papers: Papers) -> Piece:
    """Слова одной проверки: методика версии проверки, сверка оценки, части письма от движка.

    Любой отказ одиночного пути (чужой язык, нет методики, оценка не сошлась) становится
    отказом общего письма с названием пиццерии и даты: «какая и почему».
    """
    try:
        refuse_uploaded(detail)
        каталог, _ = _methodology(detail.inspection.checklist_version, papers)
        вход = state_json(detail, lang=lang)
        with tempfile.TemporaryDirectory(prefix="mcp-batch-letter-") as рядом:
            состояние = Path(рядом) / "inspection.json"
            состояние.write_text(вход, encoding="utf-8")
            _verify(detail, каталог, состояние)
            код, вывод, ошибки = _run(
                REPORT_SCRIPT,
                ["letter-parts", f"--lang={lang}"],
                data_dir=каталог,
                state=состояние,
                fallback=current_edition(detail, papers),
            )
            if код != 0:
                raise LetterError(
                    f"Движок не собрал части письма: "
                    f"{_clean(вывод + ошибки, каталог, состояние.parent)}"
                )
        try:
            parts = json.loads(вывод)
            parts["unit"], parts["grade"], parts["pct"], parts["counts"]["D3"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise LetterError(
                "Движок ответил на сборку частей письма не разбираемым JSON"
            ) from None
    except LetterError as отказ:
        raise BatchLetterError(
            "unit_failed",
            f"Общее письмо не собрано: проверка {_label(detail)} — {отказ}",
            unit=detail.inspection.unit_name,
            date=detail.inspection.inspection_date.isoformat(),
            reason=str(отказ),
        ) from None
    caveats = [
        *([FINDING_TEXT_FIELD] if _wording_langs(detail, lang=lang) else []),
        *([BLANK_TEXT_FIELD] if _blank_wordings(detail) else []),
        *([FEEDBACK_LANG_FIELD] if parts.get("feedback_skipped") else []),
    ]
    return Piece(detail=detail, parts=parts, caveats=tuple(caveats))


# --- склейка: только факты, без модели ------------------------------------------------


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def period_text(first: date, last: date) -> str:
    """Период для темы: «04.11.2026» или «13–16.10.2026»; в другом месяце — с обеими датами."""
    if first == last:
        return _day(first)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day:02d}–{last.strftime('%d.%m.%Y')}"
    if first.year == last.year:
        return f"{first.strftime('%d.%m')}–{last.strftime('%d.%m.%Y')}"
    return f"{_day(first)}–{_day(last)}"


def _pct(value: object) -> str:
    return f"{float(str(value)):g}"


def table_text(pieces: Sequence[Piece], lang: str) -> str:
    """Сводная таблица текстом: пиццерия, дата, оценка, буква, D1, D2, D3 — из записанного."""
    rows = [say("table.head", lang)]
    for piece in pieces:
        row, counts = piece.detail.inspection, piece.parts["counts"]
        rows.append(
            f"{row.unit_name} | {_day(row.inspection_date)} | {_pct(row.pct)}% | {row.grade} | "
            f"{counts['D1']} | {counts['D2']} | {counts['D3']}"
        )
    return "\n".join(rows)


def summary_text(pieces: Sequence[Piece], lang: str) -> str:
    """Итог одной фразой по фактам таблицы; цифр, которых нет в записи, здесь не бывает."""
    n = len(pieces)
    failing = [
        p.detail.inspection.grade for p in pieces if p.detail.inspection.grade in FAILING_GRADES
    ]
    below = [p for p in pieces if p.detail.inspection.grade == BELOW_GRADE]
    d2 = sum(p.parts["counts"]["D2"] for p in pieces)
    d3 = sum(p.parts["counts"]["D3"] for p in pieces)
    if not failing and not below and d2 == 0 and d3 == 0:
        return say("summary.ok", lang)
    sentences = []
    if failing:
        grades = "/".join(sorted(set(failing)))
        sentences.append(say("summary.failing", lang, k=len(failing), n=n, grades=grades))
    if below:
        sentences.append(say("summary.below", lang, k=len(below), n=n))
    if d2 or d3:
        sentences.append(say("summary.totals", lang, d3=d3, d2=d2))
    return " ".join(sentences)


def _unit_block(piece: Piece, lang: str, template: int) -> str:
    row, parts = piece.detail.inspection, piece.parts
    heads = parts["feedback_heads"]
    critical = say("unit.critical", lang) if parts["counts"]["D3"] else ""
    head = say("unit.head", lang, unit=row.unit_name, pct=_pct(row.pct), grade=row.grade) + critical
    lines = [head]
    strengths = f"{heads['strengths']}\n{parts['strengths']}" if parts["strengths"] else ""
    growth = f"{heads['growth']}\n{parts['growth']}" if parts["growth"] else ""
    if template == 1 and strengths:
        lines.append(strengths)
    lines.append(parts["summary"] if parts["summary"] else say("unit.none", lang))
    tail = [growth] if template == 1 else [strengths, growth]
    lines.extend(part for part in tail if part)
    return "\n\n".join(lines)


def todo_text(pieces: Sequence[Piece], lang: str, due: str) -> str:
    """«Что сделать»: срочное (D3, D2), затем по пиццериям, затем общие сроки одним блоком."""
    total = {level: sum(p.parts["counts"][level] for p in pieces) for level in ("D1", "D2", "D3")}
    blocks = [say("todo.title", lang)]
    for level, head in (
        ("D3", say("todo.d3", lang, when=pieces[0].parts["immediately"])),
        ("D2", say("todo.d2", lang, due=due)),
    ):
        lines = [
            say(
                "todo.line",
                lang,
                unit=p.detail.inspection.unit_name,
                text=f["text"],
                zone=f["zone"],
            )
            for p in pieces
            for f in p.parts["urgent"][level]
        ]
        if lines:
            blocks.append("\n".join([head, *lines]))
    if sum(total.values()):
        per_unit = [
            say(
                "todo.unit_line",
                lang,
                unit=p.detail.inspection.unit_name,
                **{level.lower(): p.parts["counts"][level] for level in ("D1", "D2", "D3")},
            )
            for p in pieces
            if sum(p.parts["counts"].values())
        ]
        blocks.append("\n".join([say("todo.units", lang), *per_unit]))
        blocks.append(f"{say('terms.plan', lang)} {say('terms.due', lang, due=due)}")
    else:
        blocks.append(say("terms.none", lang))
    return "\n\n".join(blocks)


def _auditors(pieces: Sequence[Piece]) -> list[str]:
    seen: list[str] = []
    for piece in pieces:
        name = str(piece.parts.get("auditor") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def compose(pieces: Sequence[Piece], *, lang: str, template: int) -> str:
    """Текст общего письма из частей проверок; порядок — по датам, как в таблице."""
    rows = [p.detail.inspection for p in pieces]
    first, last = min(r.inspection_date for r in rows), max(r.inspection_date for r in rows)
    units = ", ".join(r.unit_name for r in rows)
    lead = (
        say("lead.day", lang, date=_day(first))
        if first == last
        else say("lead.range", lang, start=_day(first), end=_day(last))
    )
    # Срок — от самой поздней проверки, как в одиночном письме (от неё же его и считает движок).
    latest = max(
        pieces, key=lambda p: (p.detail.inspection.inspection_date, p.detail.inspection.pushed_at)
    )
    due = str(latest.parts["plan_due"])
    auditors = _auditors(pieces)
    intro = say("intro", lang, lead=lead, n=len(pieces), units=units)
    if auditors:
        intro += "\n" + say(
            "auditor.one" if len(auditors) == 1 else "auditor.many", lang, names=", ".join(auditors)
        )
    sections = [
        say("subject", lang, units=units, period=period_text(first, last)),
        say("hello", lang),
        intro,
        f"{say('results.title', lang)}\n{table_text(pieces, lang)}",
        summary_text(pieces, lang),
        say("attached", lang),
        f"{say('findings.title', lang)}\n\n"
        + "\n\n".join(_unit_block(p, lang, template) for p in pieces),
        todo_text(pieces, lang, due),
        say("thanks", lang),
    ]
    return "\n\n".join(sections)


# --- вход: правило + сборка ---------------------------------------------------------


def build(
    details: Sequence[InspectionDetail],
    *,
    tenant: str,
    papers: Papers,
    lang: str | None = None,
    template: int | None = None,
    country: str = "",
) -> dict[str, object]:
    """Собрать общее письмо: правило выбора, сверка каждой проверки движком, текст.

    Ответ по форме близок к одиночному (`letters.build`): `letter`, `lang`, `template`,
    `not_restored` и `ready_to_send`, плюс состав письма — проверки, пиццерии, срок,
    партнёры и аудиторы. Если в выбор вошли проверки разных партнёров, это не запрет, а
    `partners` из нескольких имён: предупреждение показывает интерфейс.
    """
    ordered = check_selection(details, tenant=tenant, country=country)
    latest = max(ordered, key=lambda d: (d.inspection.inspection_date, d.inspection.pushed_at))
    язык = _lang(latest, lang)
    шаблон = _template(template)
    pieces = tuple(piece_for(d, lang=язык, papers=papers) for d in ordered)
    text = compose(pieces, lang=язык, template=шаблон)
    last = next(p for p in pieces if p.detail is latest)
    due = str(last.parts["plan_due"])
    named_differ = any(
        p is not last and p.detail.info and str(p.parts["plan_due"]) != due for p in pieces
    )
    by_code: dict[str, list[str]] = {}
    for piece in pieces:
        for code in piece.caveats:
            by_code.setdefault(code, []).append(piece.detail.inspection.unit_name)
    if not latest.info:
        by_code.setdefault(PLAN_DUE_FIELD, []).append(latest.inspection.unit_name)
    if named_differ:
        by_code.setdefault(PLAN_DUE_DIFFERS_FIELD, []).append(latest.inspection.unit_name)
    partners = sorted(
        {p.detail.inspection.partner.strip() for p in pieces if p.detail.inspection.partner.strip()}
    )
    return {
        "lang": язык,
        "template": шаблон,
        "letter": text,
        "inspection_ids": [d.inspection.id for d in ordered],
        "units": [d.inspection.unit_name for d in ordered],
        "dates": [d.inspection.inspection_date.isoformat() for d in ordered],
        "plan_due": due,
        "partners": partners,
        "auditors": _auditors(pieces),
        "score_verified": True,
        "not_restored": list(by_code),
        "caveat_units": {code: units for code, units in by_code.items()},
        "ready_to_send": not by_code,
        "status": (
            "batch letter built from the recorded inspections; every score matches the one recorded"
            if not by_code
            else "batch letter built and every score matches, but it is NOT ready to send as it "
            "stands: see not_restored and caveat_units"
        ),
    }
