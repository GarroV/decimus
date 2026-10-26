"""Написание имени проверяющего: латиницей, одно место для всех (D644).

Имя проверяющего уходит партнёру на штамп кадра, в шапку и в отчёт, а партнёры
разные, поэтому там оно пишется латиницей. Что человек записал в карточке
латиницей (`web_users.display_name_latin`), берётся как есть; всё остальное
кириллическое переводится автоматически по ICAO 9303 — правилу российских
загранпаспортов («Жульфаев Ринат» → «Zhulfaev Rinat»). Сербские и болгарские
буквы — тем же правилом плюс их собственные. Что уже латиницей, не трогается.

Любое преобразование написания живёт только здесь (`spell_name`): им пользуются
бот, мини-апп и MCP, и подмена одной функции меняет написание везде.
"""

from __future__ import annotations

#: Русская кириллица и общие с ней буквы, ICAO 9303 (строчные). `ь` пропускается,
#: `ъ` — «ie», `й` — «i».
_RU = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "ie", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}  # fmt: skip

#: Буквы сербской кириллицы, которых нет в русской.
_SR = {"ђ": "dj", "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz"}

#: Болгарский язык читает две буквы иначе, чем русский.
_BG = {"ъ": "a", "щ": "sht"}

#: Язык, для которого действуют поправки к русскому правилу.
LANG_BG = "bg"


def transliterate(text: str, *, lang: str | None = None) -> str:
    """Кириллицу в латиницу по ICAO 9303; остальное не трогается.

    Регистр сохраняется: заглавная буква даёт слово с заглавной («Ж» → «Zh»), а
    слово, целиком набранное заглавными, остаётся таким («ЖУЛЬФАЕВ» → «ZHULFAEV»).
    `lang="bg"` включает болгарское чтение `ъ` и `щ`; без языка они читаются по
    русскому правилу.
    """
    table = {**_RU, **_SR, **(_BG if lang == LANG_BG else {})}
    return "".join(_word(part, table) for part in _split_words(text))


def _split_words(text: str) -> list[str]:
    """Слова и разделители между ними вперемешку, чтобы собрать строку обратно."""
    parts: list[str] = []
    current = ""
    for ch in text:
        if not current or ch.isalpha() == current[-1].isalpha():
            current += ch
        else:
            parts.append(current)
            current = ch
    if current:
        parts.append(current)
    return parts


def _word(word: str, table: dict[str, str]) -> str:
    letters = [ch for ch in word if ch.isalpha()]
    shouted = len(letters) > 1 and all(ch.isupper() for ch in letters)
    out: list[str] = []
    for ch in word:
        mapped = table.get(ch.lower())
        if mapped is None:
            out.append(ch)
        elif not ch.isupper():
            out.append(mapped)
        else:
            out.append(mapped.upper() if shouted else mapped.capitalize())
    return "".join(out)


def spell_name(name: str, *, lang: str | None = None) -> str:
    """Имя проверяющего в том виде, в каком оно уйдёт партнёру: латиницей."""
    return transliterate(name.strip(), lang=lang)
