"""Plain-text message/document templates. Fixed variables, no expressions or sending."""

from __future__ import annotations

import string
from collections.abc import Mapping

KINDS = ("inspection", "prescription", "plan", "document")
LANGS = ("ru", "en")
FIELDS = {
    "inspection": ("unit", "city", "date", "letter_body"),
    "prescription": ("title", "country", "date", "due", "units", "document_body"),
    "plan": ("country", "unit", "date", "due", "plan_url"),
    "document": ("title", "country", "date", "due", "units", "addresses", "bases", "document_body"),
}


def defaults(kind: str, lang: str) -> tuple[str, str]:
    if kind not in KINDS or lang not in LANGS:
        raise ValueError("Unknown template")
    ru = lang == "ru"
    if kind == "inspection":
        return (
            "Проверка пиццерии" if ru else "Pizzeria audit"
        ) + " · {city} · {date}", "{letter_body}"
    if kind == "prescription":
        return "{title}", "{document_body}"
    if kind == "plan":
        return ("План действий" if ru else "Action plan") + " · {unit}", (
            "Пиццерия: {unit}\nПроверка: {date}\nСрок: {due}\n{plan_url}"
            if ru
            else "Pizzeria: {unit}\nInspection: {date}\nDue: {due}\n{plan_url}"
        )
    return "{title}", (
        "Страна: {country}\nДата: {date}\nСрок: {due}\nПиццерии:\n{units}\nАдреса:\n"
        "{addresses}\nОснования:\n{bases}\n\n{document_body}"
        if ru
        else (
            "Country: {country}\nDate: {date}\nDue: {due}\nPizzerias:\n{units}\n"
            "Addresses:\n{addresses}\nBased on:\n{bases}\n\n{document_body}"
        )
    )


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
