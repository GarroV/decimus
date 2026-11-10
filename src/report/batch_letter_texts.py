"""Тексты общего письма по нескольким проверкам (D739): словарь «ключ → язык → текст».

Строк внутри сборки нет — только `say(key, lang, **значения)`. Третий язык добавляется
записями сюда. Слова из одиночного письма (счёт нарушений, находки по зонам, обратная
связь аудитора, «немедленно») сюда не копируются: они приезжают готовыми от движка
(`engine/report.py letter-parts`), и вторая копия разошлась бы с первой молча.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.models import REPORT_LANGS
from .errors import ReportError

TEXTS: Mapping[str, Mapping[str, str]] = {
    "subject": {
        "ru": "Тема: Результаты проверок {units} за {period}",
        "en": "Subject: Inspection results for {units} for {period}",
    },
    "hello": {"ru": "Здравствуйте!", "en": "Hello,"},
    "lead.day": {"ru": "{date}", "en": "On {date}"},
    "lead.range": {"ru": "С {start} по {end}", "en": "Between {start} and {end}"},
    "intro": {
        "ru": "{lead} мы провели выездные проверки {n} пиццерий: {units}.",
        "en": "{lead} we carried out on-site inspections of {n} pizzerias: {units}.",
    },
    "auditor.one": {"ru": "Проверяющий: {names}", "en": "Auditor: {names}"},
    "auditor.many": {"ru": "Проверяющие: {names}", "en": "Auditors: {names}"},
    "results.title": {"ru": "Результаты проверок:", "en": "Inspection results:"},
    "table.head": {
        "ru": "Пиццерия | Дата | Оценка | Буква | D1 | D2 | D3",
        "en": "Pizzeria | Date | Score | Grade | D1 | D2 | D3",
    },
    "summary.ok": {
        "ru": "Все пиццерии соответствуют стандарту. Значительных (D2) и критических (D3) "
        "нарушений нет.",
        "en": "All pizzerias meet the standard. There are no significant (D2) or critical (D3) "
        "violations.",
    },
    "summary.failing": {
        "ru": "{k} из {n} пиццерий — оценка {grades}.",
        "en": "{k} of {n} pizzerias scored grade {grades}.",
    },
    "summary.below": {
        "ru": "{k} из {n} пиццерий ниже стандарта (оценка C).",
        "en": "{k} of {n} pizzerias are below the standard (grade C).",
    },
    "summary.totals": {
        "ru": "Всего зафиксировано: критических (D3) — {d3}, значительных (D2) — {d2}.",
        "en": "Recorded in total: critical (D3) — {d3}, significant (D2) — {d2}.",
    },
    "attached": {
        "ru": "Подробный отчёт по каждой пиццерии — с фотографиями и разбивкой по зонам — "
        "во вложении.",
        "en": "The detailed report for each pizzeria, with photographs and the breakdown by "
        "zone, is attached.",
    },
    "findings.title": {
        "ru": "Основные замечания по пиццериям:",
        "en": "Main findings by pizzeria:",
    },
    "unit.head": {
        "ru": "{unit} — {pct}%, оценка {grade}",
        "en": "{unit} — {pct}%, grade {grade}",
    },
    "unit.critical": {"ru": " — критично", "en": " — critical"},
    "unit.none": {"ru": "Нарушений не зафиксировано.", "en": "No violations recorded."},
    "todo.title": {
        "ru": "Что необходимо сделать по итогам проверок:",
        "en": "What needs to be done:",
    },
    "todo.d3": {
        "ru": "Критические нарушения (D3) — {when}:",
        "en": "Critical violations (D3) — {when}:",
    },
    "todo.d2": {
        "ru": "Значительные нарушения (D2) — до {due}:",
        "en": "Significant violations (D2) — by {due}:",
    },
    "todo.line": {"ru": "• {unit}: {text} — {zone}", "en": "• {unit}: {text} — {zone}"},
    "todo.units": {"ru": "По пиццериям:", "en": "By pizzeria:"},
    "todo.unit_line": {
        "ru": "• {unit}: критических D3 — {d3}, значительных D2 — {d2}, незначительных D1 — {d1}",
        "en": "• {unit}: critical D3 — {d3}, significant D2 — {d2}, minor D1 — {d1}",
    },
    "terms.plan": {
        "ru": "Просим подготовить план устранения выявленных отклонений.",
        "en": "Please prepare an action plan to address the identified deviations.",
    },
    "terms.due": {
        "ru": "Просим устранить все нарушения до {due}.",
        "en": "Please eliminate all violations by {due}.",
    },
    "terms.none": {
        "ru": "План устранения нарушений не требуется.",
        "en": "No action plan to address violations is required.",
    },
    "thanks": {
        "ru": "Спасибо за работу. Готовы обсудить любой пункт отчётов.",
        "en": "Thank you for your work. We are happy to walk through any item in the reports.",
    },
}


def say(key: str, lang: str, **values: object) -> str:
    """Текст по ключу на языке письма; незнакомый язык или ключ — отказ, не подмена русским."""
    if lang not in REPORT_LANGS:
        raise ReportError(
            f"Язык общего письма «{lang}» не заведён. Доступны: {', '.join(REPORT_LANGS)}"
        )
    return TEXTS[key][lang].format(**values)
