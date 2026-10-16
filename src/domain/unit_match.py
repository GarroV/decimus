"""Номер точки Dodo IS для записи справочника, названной адресом или районом (D517, #909).

Справочник частично собран со страниц сайтов стран: «Bishkek — 7 Manas Ave»,
«Gwarimpa». Номер («Bishkek-8») есть в открытом API Dodo IS вместе с UUID, адресом
и алиасом точки. Здесь — сопоставление записи справочника с точкой API.

Ошибка сопоставления тихая и дорогая: точка переименуется чужим номером, и история
проверок двух пиццерий склеится под одним именем. Поэтому правило одно: совпадение
берётся, только когда кандидат ровно один; два кандидата, ноль или одна и та же
точка API у двух записей справочника — не совпадение, запись остаётся как была.

Ступени, от надёжной к слабой; следующая нужна, только если предыдущая никого не нашла:

1. `units.code` равен UUID точки API;
2. имя записи (целиком или любая часть до/после « — », « – », «, ») равно алиасу
   или транслитерации алиаса: «Gwarimpa», «Tallinn – Gonsiori»;
3. адрес: номер дома из имени записи равен номеру дома точки API И улица из имени
   похожа на улицу API с учётом алфавита («7 Manas Ave» ↔ «проспект Манаса, 7»).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any

from .unit_name import canonical_unit, unit_name_skeleton

#: Тип записи «пиццерия» в `unitinfo/all`; остальное — склады, офисы, точки без зала.
PIZZERIA_TYPE = 1

#: Улицы короче этого в сравнение не идут: «ул», «st», «pr» не отличают одну улицу от другой.
MIN_STREET_WORD = 4

#: Слова, которыми называют вид улицы, а не саму улицу. Список явный: «отбросить всё
#: короткое» теряет настоящие названия, а подстановка похожих слов склеивает улицы.
STREET_TYPES = frozenset(
    unit_name_skeleton(w)
    for w in (
        "street avenue prospekt prospect prospekta boulevard bulevar blvd road "
        "pereulok ulitsa gatve gatvė prospektas aleja alėja puiestee tanav tänav "
        "улица проспект переулок бульвар микрорайон площадь шоссе набережная "
        "mall trts трц dodo pizza"
    ).split()
)

#: «7», «32Б», «29/9», «299в»: номер дома в написанном как угодно.
_HOUSE = re.compile(r"\d+(?:\s*[/\-]\s*\d+)?[a-zа-яё]?(?![\w])", re.IGNORECASE)
_SPLIT = re.compile(r"\s+[—–]\s+|,\s+")
_WORD = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True)
class DodoUnit:
    """Пиццерия из API Dodo IS: то, что нужно для сопоставления и переименования."""

    uuid: str
    name: str
    country: str
    state: int
    alias: str
    translit_alias: str
    address: str
    locality: str
    street: str
    house: str


@dataclass(frozen=True)
class Match:
    """Итог сопоставления одной записи: точка API либо причина отказа."""

    unit: DodoUnit | None
    how: str = ""
    reason: str = ""


def parse_dodo_units(country: str, payload: list[dict[str, Any]]) -> list[DodoUnit]:
    """Пиццерии (Type=1) из ответа `unitinfo/all`; `country` — ISO alpha-2, заглавными."""
    units: list[DodoUnit] = []
    for raw in payload:
        if raw.get("Type") != PIZZERIA_TYPE or not raw.get("UUId") or not raw.get("Name"):
            continue
        details = raw.get("AddressDetails") or {}
        units.append(
            DodoUnit(
                uuid=str(raw["UUId"]).strip().lower(),
                name=str(raw["Name"]).strip(),
                country=country.upper(),
                state=int(raw.get("State") or 0),
                alias=str(raw.get("Alias") or "").strip(),
                translit_alias=str(raw.get("TranslitAlias") or "").strip(),
                address=str(raw.get("Address") or "").strip(),
                locality=str(details.get("LocalityName") or "").strip(),
                street=str(details.get("StreetName") or "").strip(),
                house=str(details.get("HouseNumber") or "").strip(),
            )
        )
    return units


def official_name(unit: DodoUnit) -> tuple[str, str | None]:
    """Имя точки для справочника и код города, если он известен.

    Номер Dodo IS латиницей берётся как есть: «Dubai 3-1» — это имя, а не «Dubai-1»,
    и сведение к `City-N` склеило бы девять дубайских точек в две. Кириллица
    («Бишкек-17») приводится к английскому канону, как всякое имя (D233).
    """
    canon = canonical_unit(unit.name)
    if unit.name.isascii():
        return unit.name, canon.city if canon else None
    if canon is None:
        return unit.name, None
    return canon.name, canon.city


def _skeleton(text: str) -> str:
    return unit_name_skeleton(text)


def _house_key(text: str) -> str:
    return re.sub(r"\s+", "", _skeleton(text))


def _houses(text: str) -> set[str]:
    return {_house_key(m.group(0)) for m in _HOUSE.finditer(text)}


def _street_words(text: str, skip: set[str]) -> set[str]:
    слова = {_skeleton(w) for w in _WORD.findall(text)}
    return {
        w for w in слова if len(w) >= MIN_STREET_WORD and w not in STREET_TYPES and w not in skip
    }


def _related(a: str, b: str) -> bool:
    """Одно слово — начало другого: «manas» ↔ «manasa», «kiev» ↔ «kievskaya»."""
    короче, длиннее = sorted((a, b), key=len)
    return len(короче) >= MIN_STREET_WORD and длиннее.startswith(короче)


def _parts(name: str) -> set[str]:
    части = {name, *(p for p in _SPLIT.split(name))}
    return {_skeleton(p) for p in части if len(_skeleton(p)) >= 3}


def _by_alias(name: str, candidates: list[DodoUnit]) -> list[DodoUnit]:
    ключи = _parts(name)
    return [
        c for c in candidates if ключи & {_skeleton(c.alias), _skeleton(c.translit_alias)} - {""}
    ]


def _by_address(name: str, candidates: list[DodoUnit]) -> list[DodoUnit]:
    дома = _houses(name)
    if not дома:
        return []
    found: list[DodoUnit] = []
    for c in candidates:
        город = {_skeleton(w) for w in _WORD.findall(c.locality)}
        слова = _street_words(name, город)
        улицы = _street_words(f"{c.street} {c.address}", set())
        # Номер дома у API иногда пуст, а стоит в конце адреса («улица Шевченко, 80»).
        дома_api = {_house_key(c.house)} if c.house else _houses(c.address)
        if дома & дома_api and any(_related(a, b) for a in слова for b in улицы):
            found.append(c)
    return found


def match_unit(name: str, code: str | None, candidates: list[DodoUnit]) -> Match:
    """Точка API для записи справочника или причина, по которой совпадения нет."""
    if code:
        по_коду = [c for c in candidates if c.uuid == code.strip().lower()]
        if len(по_коду) == 1:
            return Match(по_коду[0], "code")
    for how, find in (("алиас", _by_alias), ("адрес", _by_address)):
        found = find(name, candidates)
        if len(found) == 1:
            if code and code.strip().lower() != found[0].uuid:
                return Match(
                    None, reason=f"code записи не равен UUID найденной точки {found[0].name}"
                )
            return Match(found[0], how)
        if len(found) > 1:
            names = ", ".join(sorted(c.name for c in found))
            return Match(None, reason=f"неоднозначно ({how}): {names}")
    return Match(None, reason="в API Dodo IS не найдена")


def claimed_twice(matches: dict[Any, Match]) -> dict[Any, Match]:
    """Две записи справочника на одну точку API — обе остаются как были.

    Какая из двух настоящая, по данным не видно; переименовать обе значило бы
    завести дубль, а переименовать одну — угадать.
    """
    by_uuid: dict[str, list[Any]] = defaultdict(list)
    for key, m in matches.items():
        if m.unit is not None:
            by_uuid[m.unit.uuid].append(key)
    result = dict(matches)
    for uuid, keys in by_uuid.items():
        if len(keys) > 1:
            for key in keys:
                unit = matches[key].unit
                result[key] = Match(
                    None, reason=f"две записи на одну точку {unit.name if unit else uuid}"
                )
    return result


def merge_registry(
    registry: list[tuple[str, str, str, bool]], api: list[DodoUnit]
) -> list[DodoUnit]:
    """Кандидаты для сопоставления: свод пиццерий первым, API — адрес и недостающее.

    `registry` — строки `agg.units`: (UUID, страна, номер Dodo IS, работает). Номер,
    страна и состояние берутся из свода; адрес, алиас и транслит — из API по тому же
    UUID. Точка, которой нет в своде, остаётся из API как есть; точка свода, которой
    нет в API, годится только для сопоставления по `code`.
    """
    api_by_uuid = {u.uuid: u for u in api}
    merged: dict[str, DodoUnit] = dict(api_by_uuid)
    for uuid, country, name, working in registry:
        key = uuid.strip().lower()
        base = api_by_uuid.get(key)
        merged[key] = replace(
            base or DodoUnit(key, name, country, int(working), "", "", "", "", "", ""),
            name=name,
            country=country,
            state=int(working),
        )
    return list(merged.values())
