"""Сопоставление точек справочника `units` со сведениями о пиццериях `unit_profiles` (#316, #909).

Справочник сведений — эталон: у каждой его строки есть имя с номером («Bishkek-8»),
адрес и код Dodo. Точки `units` заведены разными путями — с сайтов стран («Bishkek — 7
Manas Ave», «Mokotów»), руками на кириллице («Тбилиси-1»), по факту проверки — и с
эталоном не связаны. Здесь чистая логика связи, без базы: какой строке эталона
соответствует точка, по какому правилу и насколько этому правилу можно верить.

Правила идут по убыванию доверия, первое давшее кандидатов решает:

1. `code` — код точки совпал с `dodo_id`. Высокое.
2. `name` — имя совпало с именем эталона без регистра и диакритики. Высокое.
3. `alias` — с именем эталона совпал синоним точки. Высокое.
4. `numbered` — имя «Город-N» на другом алфавите или с опечаткой в городе
   («Тбилиси-1», «Белград-1» → «Tbilisi-1», «Belgrade-1»); страна сверяется.
   Высокое, а без известной страны у точки — среднее.
5. `address` — имя сайта или адрес («Bishkek — 7 Manas Ave») против адреса эталона:
   улица (транслитерация, без «ул./st./проспект») и номер дома, в той же стране.
   Улица и дом — высокое; одна улица или район без номера — среднее.
6. `city` — имя точки и есть город, и в нём одна строка эталона. Среднее.

Несколько кандидатов у одного правила — `ambiguous`, ничего не выбирается: угадать
не значит связать. Ничего не нашлось — `unmatched`.

`plan` затем сводит точки в действия: оставить, дописать, переименовать, слить дубли.
Слить можно только пустую точку: у остальных есть история (проверки, переносы),
которую удаление дубля либо удалило бы, либо переписало.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from .unit_name import canonical_unit, fold_unit_name, unit_name_skeleton

HIGH = "high"
MEDIUM = "medium"

#: Армянские буквы. «ու» читается как «u» и разбирается раньше одиночных букв.
_ARMENIAN = {
    "ա": "a", "բ": "b", "գ": "g", "դ": "d", "ե": "e", "զ": "z", "է": "e", "ը": "y",
    "թ": "t", "ժ": "zh", "ի": "i", "լ": "l", "խ": "kh", "ծ": "ts", "կ": "k", "հ": "h",
    "ձ": "dz", "ղ": "gh", "ճ": "ch", "մ": "m", "յ": "y", "ն": "n", "շ": "sh", "ո": "o",
    "չ": "ch", "պ": "p", "ջ": "j", "ռ": "r", "ս": "s", "վ": "v", "տ": "t", "ր": "r",
    "ց": "ts", "ւ": "v", "փ": "p", "ք": "k", "օ": "o", "ֆ": "f",
}  # fmt: skip

#: Буквы сербской, украинской и казахской кириллицы, которых нет в основной таблице.
_EXTRA_CYRILLIC = {
    "ј": "j", "љ": "lj", "њ": "nj", "ђ": "dj", "ћ": "c", "џ": "dz", "ї": "i", "є": "e",
    "ґ": "g", "і": "i", "ғ": "g", "қ": "k", "ң": "n", "ү": "u", "ө": "o", "ұ": "u",
    "ә": "a", "һ": "h", "ў": "u",
}  # fmt: skip
_PRE = str.maketrans(_ARMENIAN | _EXTRA_CYRILLIC)

#: Слова, которые называют тип улицы или места, но не саму улицу. Сводятся тем же
#: ключом, что и слова адреса, поэтому «улица» и «ulitsa» — одно слово.
_STOP_RAW = (
    "ул улица ulitsa ulica ulice street st str strada strasse ave avenue pr prosp prospekt "
    "prospect проспект просп пр пер переулок lane bd bld blvd bulevar bulevard bulevardul "
    "boulevard calea aleja al alley alea tn pst tee mah cad cd sok sk jl kec kab road rd "
    "mkr мкр микрорайон dom дом d g gatve gt gor город city mall center centre plaza tc "
    "трц тц trk shopping residence residential tower district rayon район nr no bb blok "
    "block building bldg floor app phase foodcourt court square sq pl place in the de la "
    "of and des dei"
).split()

_NUMBERED_PAREN = re.compile(r"[-\s]*\(\s*(\d+)\s*\)")
_PAREN_TEXT = re.compile(r"\s*\([^)]*\)")
_NUMBERED_SPACE = re.compile(r"\s*-\s*(?=\d)")
_TOKEN = re.compile(r"\w+(?:[/\-]\w+)*", re.UNICODE)
_SLUG_DROP = re.compile(r"[^a-z0-9]")

#: Два слова одного ключа меньше этого — только точное равенство, без «начало слова».
_MIN_PREFIX = 4
_MIN_FUZZY = 6
_FUZZY_CUTOFF = 0.86


def _latin(text: str) -> str:
    return text.casefold().translate(_PRE)


def _word_key(word: str) -> str:
    """Ключ слова: латиницей, без диакритики, с общими разночтениями («ch»/«c» — одно)."""
    key = unit_name_skeleton(_latin(word))
    for variant, short in (("ch", "c"), ("sh", "s"), ("zh", "z"), ("dz", "z"), ("dj", "d")):
        key = key.replace(variant, short)
    return key


def _house_key(token: str) -> str:
    parts = (unit_name_skeleton(_latin(p)) for p in token.split("/"))
    return "/".join(p for p in parts if p)


_STOP = frozenset(_word_key(w) for w in _STOP_RAW)


@dataclass(frozen=True)
class AddressKey:
    """Адрес словами: ключи слов улицы и района, отдельно номера домов."""

    words: tuple[str, ...]
    houses: tuple[str, ...]


def address_key(text: str | None) -> AddressKey:
    """Разобрать имя сайта или адрес на слова улицы и номера домов."""
    words: list[str] = []
    houses: list[str] = []
    for token in _TOKEN.findall(text or ""):
        if any(ch.isdigit() for ch in token):
            house = _house_key(token)
            if house:
                houses.append(house.lstrip("0") or "0")
            continue
        for part in token.split("-"):
            key = _word_key(part)
            if len(key) >= 2 and key not in _STOP:
                words.append(key)
    return AddressKey(tuple(words), tuple(houses))


def _word_match(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= _MIN_PREFIX and long_.startswith(short):
        return True
    return len(short) >= _MIN_FUZZY and difflib.SequenceMatcher(None, a, b).ratio() >= _FUZZY_CUTOFF


def _city_key(text: str | None) -> str:
    return "".join(_word_key(w) for w in _TOKEN.findall(text or ""))


def clean_ref_name(name: str) -> str:
    """Имя эталона без шума: «Bucharest-(5)» → «Bucharest-5», «Iasi - 1» → «Iasi-1»."""
    text = _NUMBERED_PAREN.sub(lambda m: f"-{m.group(1)}", name.strip())
    text = _NUMBERED_SPACE.sub("-", text)
    return " ".join(text.split())


def _numbered_key(name: str) -> str:
    """Ключ имени «Город-N» для сверки между алфавитами; пусто, если номера нет."""
    text = clean_ref_name(name)
    if not re.search(r"\d\s*$", _PAREN_TEXT.sub("", text)):
        return ""
    return unit_name_skeleton(_PAREN_TEXT.sub("", text))


def city_slug(city: str | None) -> str | None:
    """Код города как в `units.city`: «Novi Sad» → «novisad»."""
    if not city:
        return None
    base = unicodedata.normalize("NFKD", fold_unit_name(city))
    slug = _SLUG_DROP.sub("", "".join(c for c in base if not unicodedata.combining(c)))
    return slug or None


@dataclass(frozen=True)
class Ref:
    """Строка эталона `unit_profiles`."""

    country: str
    name: str
    dodo_id: str | None = None
    city: str | None = None
    address: str | None = None

    @property
    def key(self) -> str:
        return f"{self.country}/{fold_unit_name(self.name)}"

    @property
    def clean_name(self) -> str:
        return clean_ref_name(self.name)


@dataclass(frozen=True)
class Usage:
    """Что держит точку: проверки, история переносов и прочие ссылки."""

    inspections: int = 0
    moves: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.inspections + self.moves + self.other


@dataclass(frozen=True)
class UnitRow:
    """Точка справочника `units` вместе с синонимами и тем, что на неё ссылается."""

    id: str
    name: str
    code: str | None = None
    country: str | None = None
    city: str | None = None
    aliases: tuple[str, ...] = ()
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class Match:
    """Итог поиска одной точки: кандидаты, правило, доверие, пояснение."""

    status: str  # matched | ambiguous | unmatched
    rule: str = ""
    confidence: str = ""
    refs: tuple[Ref, ...] = ()
    detail: str = ""

    @property
    def ref(self) -> Ref:
        return self.refs[0]


class RefIndex:
    """Эталон с индексами под правила. Строится один раз на весь прогон."""

    def __init__(self, refs: list[Ref]) -> None:
        self.refs = tuple(refs)
        self.by_code = {r.dodo_id: r for r in refs if r.dodo_id}
        self.by_name: dict[str, list[Ref]] = defaultdict(list)
        self.by_numbered: dict[str, list[Ref]] = defaultdict(list)
        self.by_city: dict[tuple[str, str], list[Ref]] = defaultdict(list)
        self.city_words: dict[str, set[str]] = defaultdict(set)
        self.address: dict[str, AddressKey] = {}
        for r in refs:
            self.by_name[fold_unit_name(clean_ref_name(r.name))].append(r)
            numbered = _numbered_key(r.name)
            if numbered:
                self.by_numbered[numbered].append(r)
            if r.city:
                self.by_city[(r.country, _city_key(r.city))].append(r)
                self.city_words[r.country].update(_word_key(w) for w in _TOKEN.findall(r.city))
            self.address[r.key] = address_key(r.address)


def _only(refs: list[Ref], country: str | None) -> list[Ref]:
    return [r for r in refs if country is None or r.country == country]


def _verdict(refs: list[Ref], rule: str, confidence: str, detail: str = "") -> Match | None:
    unique = list({r.key: r for r in refs}.values())
    if not unique:
        return None
    if len(unique) > 1:
        return Match("ambiguous", rule, "", tuple(unique), detail)
    return Match("matched", rule, confidence, tuple(unique), detail)


def _by_numbered(unit: UnitRow, index: RefIndex) -> Match | None:
    names = [unit.name, *unit.aliases]
    keys = {_numbered_key(n) for n in names} - {""}
    canon = canonical_unit(re.sub(r"\s*\([^)]*\)", "", unit.name))
    if canon is not None:
        keys.add(_numbered_key(canon.name))
    country = unit.country or (canon.country if canon else None)
    found = [r for k in keys for r in _only(index.by_numbered.get(k, []), country)]
    confidence = HIGH if unit.country else MEDIUM
    return _verdict(found, "numbered", confidence, "имя «Город-N» на другом алфавите")


def _by_address(unit: UnitRow, index: RefIndex) -> Match | None:
    if unit.country is None:
        return None
    cities = index.city_words[unit.country] | {_word_key(unit.city or "")}
    wanted = address_key(unit.name)
    words = tuple(w for w in wanted.words if w not in cities)
    if not words:
        return None
    street_only: list[Ref] = []
    with_house: list[Ref] = []
    for r in index.refs:
        if r.country != unit.country:
            continue
        theirs = index.address[r.key]
        if not all(any(_word_match(w, t) for t in theirs.words) for w in words):
            continue
        street_only.append(r)
        if wanted.houses and wanted.houses[0] in theirs.houses:
            with_house.append(r)
    if wanted.houses and with_house:
        return _verdict(
            with_house, "address", HIGH, f"улица {'/'.join(words)}, дом {wanted.houses[0]}"
        )
    if wanted.houses:
        return None  # улица есть, дома нет: связать нельзя, подсказка — в `hint`
    return _verdict(street_only, "address", MEDIUM, f"улица или район {'/'.join(words)} в адресе")


def _by_city(unit: UnitRow, index: RefIndex) -> Match | None:
    if unit.country is None:
        return None
    key = _city_key(unit.name)
    return _verdict(
        index.by_city.get((unit.country, key), []), "city", MEDIUM, "имя — город, в нём одна точка"
    )


def match_unit(unit: UnitRow, index: RefIndex) -> Match:
    """Найти строку эталона для точки: см. правила в докстринге модуля."""
    if unit.code and unit.code in index.by_code:
        return Match("matched", "code", HIGH, (index.by_code[unit.code],), "код совпал с dodo_id")
    found = _only(index.by_name.get(fold_unit_name(clean_ref_name(unit.name)), []), unit.country)
    result = _verdict(found, "name", HIGH, "имя совпало")
    if result is None:
        aliased = [
            r
            for a in unit.aliases
            for r in _only(index.by_name.get(fold_unit_name(clean_ref_name(a)), []), unit.country)
        ]
        result = _verdict(aliased, "alias", HIGH, "синоним совпал с именем")
    for rule in (_by_numbered, _by_address, _by_city):
        if result is not None:
            break
        result = rule(unit, index)
    return result or Match("unmatched", detail=_hint(unit, index))


def _hint(unit: UnitRow, index: RefIndex) -> str:
    if unit.country is None:
        return "страны у точки нет, по имени эталон не нашёлся"
    wanted = address_key(unit.name)
    cities = index.city_words[unit.country]
    words = tuple(w for w in wanted.words if w not in cities)
    if wanted.houses and words:
        near = [
            r.name
            for r in index.refs
            if r.country == unit.country
            and all(any(_word_match(w, t) for t in index.address[r.key].words) for w in words)
        ]
        if near:
            return f"улица совпала у {', '.join(near)}, а дом {wanted.houses[0]} — нет"
    return "в эталоне страны такой улицы, района или имени нет"


# --- сведение в действия ---------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """Одно решение по точке. `kind`: keep, fill, rename, merge, blocked, conflict,
    ambiguous, unmatched, skipped. Для merge `target` — точка, в которую вливаем."""

    kind: str
    unit: UnitRow
    match: Match
    new_name: str | None = None
    new_code: str | None = None
    new_city: str | None = None
    new_country: str | None = None
    target: UnitRow | None = None
    note: str = ""

    @property
    def writes(self) -> bool:
        return self.kind in ("fill", "rename", "merge")


def _target_city(ref: Ref, unit: UnitRow) -> str | None:
    """Код города для точки без города: из канонического имени, иначе слепок города эталона."""
    if unit.city:
        return None
    canon = canonical_unit(ref.clean_name)
    return (canon.city if canon and canon.city else None) or city_slug(ref.city)


def _winner(group: list[tuple[UnitRow, Match]], ref: Ref) -> UnitRow:
    """Кого оставить из точек, сошедшихся на одной строке эталона."""

    def weight(item: tuple[UnitRow, Match]) -> tuple[int, int, int, int]:
        unit, match = item
        return (
            int(unit.code is not None and unit.code == ref.dodo_id),
            unit.usage.total,
            int(match.rule == "name"),
            int(match.confidence == HIGH),
        )

    return max(group, key=weight)[0]


def plan(units: list[UnitRow], index: RefIndex, *, min_confidence: str = MEDIUM) -> list[Action]:
    """План по всем точкам. Ничего не пишет и не читает базу."""
    allowed = {HIGH} if min_confidence == HIGH else {HIGH, MEDIUM}
    results = [(u, match_unit(u, index)) for u in units]
    groups: dict[str, list[tuple[UnitRow, Match]]] = defaultdict(list)
    actions: dict[str, Action] = {}
    for unit, match in results:
        if match.status == "ambiguous":
            actions[unit.id] = Action("ambiguous", unit, match, note="несколько кандидатов")
        elif match.status == "unmatched":
            actions[unit.id] = Action("unmatched", unit, match, note=match.detail)
        elif match.confidence not in allowed:
            actions[unit.id] = Action("skipped", unit, match, note="доверие ниже порога")
        else:
            groups[match.ref.key].append((unit, match))
    taken = {fold_unit_name(u.name) for u in units}
    for group in groups.values():
        ref = group[0][1].ref
        winner = _winner(group, ref)
        for unit, match in group:
            if unit.id == winner.id:
                continue
            clash = unit.code and ref.dodo_id and unit.code != ref.dodo_id
            if clash or unit.usage.total:
                why = "код другой, чем у эталона" if clash else _usage_note(unit.usage)
                actions[unit.id] = Action("blocked", unit, match, target=winner, note=why)
            else:
                actions[unit.id] = Action("merge", unit, match, target=winner, note="пустой дубль")
        match = next(m for u, m in group if u.id == winner.id)
        actions[winner.id] = _one(winner, match, ref, taken)
    return [actions[u.id] for u in units]


def _usage_note(usage: Usage) -> str:
    parts = [
        f"{n} {label}"
        for n, label in (
            (usage.inspections, "проверок"),
            (usage.moves, "записей истории переносов"),
            (usage.other, "прочих ссылок"),
        )
        if n
    ]
    return "на дубль ссылаются: " + ", ".join(parts)


def _one(unit: UnitRow, match: Match, ref: Ref, taken: set[str]) -> Action:
    name = ref.clean_name
    same_name = fold_unit_name(unit.name) == fold_unit_name(name)
    new_name = None if same_name else name
    if new_name and fold_unit_name(new_name) in taken:
        return Action("conflict", unit, match, note=f"имя «{new_name}» уже занято другой точкой")
    new_code = ref.dodo_id if ref.dodo_id and unit.code is None else None
    new_country = ref.country if unit.country is None else None
    new_city = _target_city(ref, unit)
    if not (new_name or new_code or new_country or new_city):
        return Action("keep", unit, match)
    kind = "rename" if new_name else "fill"
    return Action(kind, unit, match, new_name, new_code, new_city, new_country)
