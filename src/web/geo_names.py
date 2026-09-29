"""Названия стран и городов для людей — по коду из справочника точек.

Справочник сети хранит город кодом источника (`tbilisi`, `novisad`,
`starazagora`), а страну — кодом ISO 3166-1 (`GE`). Код остаётся ключом везде —
в адресе, в отборе, в базе; здесь только то, как его показать (конституция,
принцип 5: связь кодом, перевод — словом).

Незнакомый код не ломает экран: город показывается кодом с заглавной буквы,
страна — кодом. Появится новая страна сети — дописать строку сюда.
"""

from __future__ import annotations

from ..domain.geo import CITIES, COUNTRIES


def _title(table: dict[str, dict[str, str]], code: str, lang: str) -> str | None:
    names = table.get(code)
    if names is None:
        return None
    return names.get(lang) or names.get("en")


def country_title(code: str | None, lang: str) -> str:
    """Страна словом; незнакомый код — кодом, пустой — пустой строкой."""
    if not code:
        return ""
    return _title(COUNTRIES, code.upper(), lang) or code.upper()


def city_title(code: str | None, lang: str) -> str:
    """Город словом; незнакомый код — кодом с заглавной, пустой — пустой строкой."""
    if not code:
        return ""
    return _title(CITIES, code.casefold(), lang) or code[:1].upper() + code[1:]
