"""Plain-text message/document templates. Fixed variables, no expressions or sending."""

from __future__ import annotations

import string
from collections.abc import Mapping

from .models import REPORT_LANGS

KINDS = ("inspection", "prescription", "plan", "document")
LANGS = REPORT_LANGS
FIELDS = {
    "inspection": ("unit", "city", "date", "letter_body"),
    "prescription": ("title", "country", "date", "due", "units", "document_body"),
    "plan": ("country", "unit", "date", "due", "plan_url"),
    "document": ("title", "country", "date", "due", "units", "addresses", "bases", "document_body"),
}


#: Встроенные (тема, тело) по виду и языку — пока их не заменила правка в админке.
#: Язык без записи — отказ в `defaults`, а не английский вместо него: полноту по
#: языкам отчёта держит `tests/test_lang_catalogs_complete.py`.
DEFAULTS: dict[str, dict[str, tuple[str, str]]] = {
    "inspection": {
        "ru": ("Проверка пиццерии · {city} · {date}", "{letter_body}"),
        "en": ("Pizzeria audit · {city} · {date}", "{letter_body}"),
    },
    "prescription": {
        "ru": ("{title}", "{document_body}"),
        "en": ("{title}", "{document_body}"),
    },
    "plan": {
        "ru": (
            "План действий · {unit}",
            "Пиццерия: {unit}\nПроверка: {date}\nСрок: {due}\n{plan_url}",
        ),
        "en": (
            "Action plan · {unit}",
            "Pizzeria: {unit}\nInspection: {date}\nDue: {due}\n{plan_url}",
        ),
    },
    "document": {
        "ru": (
            "{title}",
            "Страна: {country}\nДата: {date}\nСрок: {due}\nПиццерии:\n{units}\nАдреса:\n"
            "{addresses}\nОснования:\n{bases}\n\n{document_body}",
        ),
        "en": (
            "{title}",
            "Country: {country}\nDate: {date}\nDue: {due}\nPizzerias:\n{units}\n"
            "Addresses:\n{addresses}\nBased on:\n{bases}\n\n{document_body}",
        ),
    },
}


def defaults(kind: str, lang: str) -> tuple[str, str]:
    if kind not in KINDS or lang not in LANGS:
        raise ValueError("Unknown template")
    return DEFAULTS[kind][lang]


def check(kind: str, subject: str, body: str) -> None:
    if kind not in KINDS:
        raise ValueError("Unknown template")
    for is_header, text, limit in ((True, subject, 300), (False, body, 6000)):
        if not text.strip() or len(text) > limit:
            raise ValueError("Empty or overly long template")
        if any(ord(c) < 32 and (is_header or c not in "\n\r\t") for c in text):
            raise ValueError("Control characters are not allowed")
        try:
            pieces = list(string.Formatter().parse(text))
        except ValueError as exc:
            raise ValueError("Unbalanced template braces") from exc
        for _literal, name, spec, conv in pieces:
            allowed = set(FIELDS[kind]) - (
                {"letter_body", "document_body", "units", "addresses", "bases"}
                if is_header
                else set()
            )
            if name is not None and (name not in allowed or spec or conv):
                raise ValueError("Only listed variable names without formatting are allowed")


def render(kind: str, subject: str, body: str, values: Mapping[str, str]) -> tuple[str, str]:
    check(kind, subject, body)
    fields = {name: values.get(name, "") for name in FIELDS[kind]}
    header = subject.format_map(fields)
    if len(header) > 300 or any(ord(c) < 32 for c in header):
        raise ValueError("Rendered subject is invalid")
    return header, body.format_map(fields)


def sample(kind: str) -> dict[str, str]:
    common = {
        "unit": "Example-1",
        "city": "Example",
        "country": "Example country",
        "date": "2030-01-01",
        "due": "2030-01-10",
        "title": "Example prescription",
        "units": "Example-1",
        "addresses": "Example street 1",
        "bases": "Example-1 · 2030-01-01",
        "document_body": "Example confirmed text",
        "letter_body": "Example inspection letter",
        "plan_url": "https://example.invalid/actions?tab=plans",
    }
    return {key: common[key] for key in FIELDS[kind]}
