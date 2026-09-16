"""T284: карта синонимов формулировок — где живёт выученное (D119).

Решение владельца: если аудитор сказал иначе или с ошибками и ПРЯМОГО
совпадения с методикой не нашлось, разобранная формулировка складывается в
базу как синоним пункта и работает при следующем поиске; прямое совпадение
синонима второй строки не заводит. Здесь — место и слой доступа к нему.
Кто и когда кладёт синоним, решает потребитель (T285, блок `binding`).

**Слой отдаёт КОД пункта, а не пункт.** Методики в базе нет и не будет (это
справочник домена, `data/checklist.csv`), а у каждой проверки своё издание
(D063, D064) — поэтому действует ли код в издании ТОЙ проверки, решает
вызывающий. Синоним, оставшийся от снятого пункта, просто никуда не приводит.

**Звать этот слой может только ярус выше базы.** `src.recognize` и `src.db` —
пиры в слоевом контракте (`pyproject.toml`), и импорт отсюда в быстрый путь
уронит `lint-imports`. Тот же приём, что у выгрузки кадров: сопоставлением
занимается ярус, которому доступны оба (`src.bot`), а карта приходит к нему
готовыми строками — по одной (`lookup_phrase`) или целиком (`list_phrases`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment
from .errors import SynonymError

#: Арендатор по умолчанию — то же значение, что у `directory.DEFAULT_TENANT`.
DEFAULT_TENANT = "default"

#: Происхождение записи кодом, не формулировкой (конституция, принцип 5).
#: `learned` — накоплено машиной на непрямом совпадении (D119); `manual` —
#: заведено человеком. Список закрыт и в схеме (`0012`): неизвестный код
#: сделал бы отбор «что мы навыучивали сами» неполным молча.
LEARNED = "learned"
MANUAL = "manual"
ORIGINS = frozenset({LEARNED, MANUAL})

#: Исход записи — тоже код, а не пара флагов: ветку кода вызывающий обязан
#: выбирать значением, а не разбором текста (тот же довод, что у
#: `VersionMismatchError`).
#:
#: * `REMEMBERED` — синонима не было, завели;
#: * `ALREADY_KNOWN` — был и ведёт к тому же пункту (D119: прямое совпадение
#:   синонима не заводит);
#: * `CONFLICT` — был и ведёт к ДРУГОМУ пункту; строка не тронута.
REMEMBERED = "remembered"
ALREADY_KNOWN = "already_known"
CONFLICT = "conflict"

_WHITESPACE = re.compile(r"\s+")

#: Что снимается с краёв формулировки. Внутри строки пунктуация остаётся: она
#: там разделяет слова, а по краям это след ввода — точка в конце фразы,
#: кавычки вокруг цитаты, тире перед перечислением.
_EDGES = " .,;:!?…\"'«»‹›()[]{}-–—/\\*"


def normalize_phrase(text: str) -> str:
    """Ключ поиска по карте синонимов.

    Правило одно на запись и на поиск — разойдись они хоть на знак, карта
    перестанет работать молча и только на части написаний (ровно та ловушка,
    о которой предупреждает `directory.py` про справочник точек).

    Что снимается: приведение к единой форме Unicode, края, повторные пробелы
    внутри, регистр, крайняя пунктуация. Чего НЕ снимается — опечатки: их
    разбирает потребитель, сюда формулировка приходит уже разобранной.

    NFKC не украшение: «ё», набранное составом (е + диакритика), и «ё» одним
    знаком — разные строки байт в байт, и без приведения один и тот же
    синоним, введённый с разных клавиатур, лёг бы в карту дважды.
    """
    единая = unicodedata.normalize("NFKC", text)
    схлопнутая = _WHITESPACE.sub(" ", единая.strip()).casefold()
    return схлопнутая.strip(_EDGES)


@dataclass(frozen=True)
class PhraseAlias:
    """Строка карты: как сказал человек и к какому пункту это привело."""

    item_code: str
    lang: str
    phrase: str
    key: str
    origin: str
    created_at: datetime


@dataclass(frozen=True)
class PhraseMemory:
    """Чем закончилась попытка запомнить: исход кодом и строка, лежащая в базе."""

    outcome: str
    alias: PhraseAlias


# Запросы печатают список колонок целиком, а не собирают его из общего куска
# строкой: динамическая сборка текста SQL — ровно то, что ловит S608, и здесь
# ей взяться неоткуда не по обещанию, а по устройству кода (тот же приём и то
# же объяснение в `queries.py`).
_LOOKUP_SQL = """
select item_code, lang, phrase, phrase_normalized, origin, created_at
from phrase_aliases
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
"""

# `do nothing`, а не `do update`: синоним, который уже работает, не
# переписывается ошибкой одного аудитора. Прав на UPDATE у роли приложения нет
# вовсе (миграция `0012`), то есть это свойство базы, а не дисциплина вызовов.
_REMEMBER_SQL = """
insert into phrase_aliases (tenant_code, lang, phrase_normalized, item_code, phrase, origin)
values (%(tenant)s, %(lang)s, %(key)s, %(code)s, %(phrase)s, %(origin)s)
on conflict (tenant_code, lang, phrase_normalized) do nothing
returning item_code, lang, phrase, phrase_normalized, origin, created_at
"""

_INSERT_TENANT_SQL = "insert into tenants (code) values (%s) on conflict (code) do nothing"

# Карта берётся целиком намеренно, без предела выдачи: синонимов у арендатора
# столько, сколько пунктов методики, помноженных на способы их назвать, —
# сотни строк, а не миллионы. Предел здесь означал бы карту, обрезанную молча:
# пропавший синоним выглядит как «система разучилась», а не как «выдача
# кончилась». Отбор по языку и по пункту для того и есть, чтобы спрашивать
# нужное, а не всё.
_LIST_SQL = """
select item_code, lang, phrase, phrase_normalized, origin, created_at
from phrase_aliases
where tenant_code = %(tenant)s
  and (%(lang)s::text is null or lang = %(lang)s)
  and (%(code)s::text is null or item_code = %(code)s)
order by lang, phrase_normalized
"""


def _row_to_alias(row: tuple[Any, ...]) -> PhraseAlias:
    return PhraseAlias(
        item_code=str(row[0]),
        lang=str(row[1]),
        phrase=str(row[2]),
        key=str(row[3]),
        origin=str(row[4]),
        created_at=row[5],
    )


def _lang_key(lang: str) -> str:
    """Язык одним написанием: «RU» и «ru» — один язык, а не два ключа карты."""
    return lang.strip().casefold()


def lookup_phrase(text: str, *, lang: str, tenant: str = DEFAULT_TENANT) -> PhraseAlias | None:
    """Синоним по сказанной формулировке. Не нашлось — `None`.

    Отсутствие синонима и недоступная карта — разные ответы: первое `None`,
    второе `SynonymError`. Отданная вместо отказа пустота означала бы, что при
    потерянной базе система молча разучивается и переспрашивает аудитора
    заново — то самое, от чего уходит D119.
    """
    key = normalize_phrase(text)
    if not key:
        return None
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOOKUP_SQL, {"tenant": tenant, "lang": _lang_key(lang), "key": key})
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise SynonymError(f"Карта синонимов недоступна ({type(exc).__name__}): {exc}") from exc
    return None if row is None else _row_to_alias(row)


def remember_phrase(
    text: str,
    *,
    item_code: str,
    lang: str,
    origin: str = LEARNED,
    tenant: str = DEFAULT_TENANT,
) -> PhraseMemory:
    """Запомнить формулировку синонимом пункта.

    Исход называется кодом, а не угадывается по возвращённой строке, и третий
    исход (`CONFLICT`) существует именно затем, чтобы разночтение было названо
    вслух. Переписать чужую строку — значит дать одной ошибке аудитора увести
    формулировку, которая уже работает; промолчать — значит ответить
    «запомнил», ничего не запомнив.

    Вызывать имеет смысл только там, где прямого совпадения не нашлось
    (D119). Слой этого за вызывающего не проверяет — методики он не видит, —
    но и вреда от лишнего вызова нет: известный синоним вернётся исходом
    `ALREADY_KNOWN` и второй строки не заведёт.
    """
    key = normalize_phrase(text)
    if not key:
        raise SynonymError("Формулировка пустая — синонимом её не заведёшь")
    code = item_code.strip()
    if not code:
        raise SynonymError("У синонима нет кода пункта — такая строка никуда не ведёт")
    if origin not in ORIGINS:
        raise SynonymError(
            f"Неизвестное происхождение записи «{origin}»: карта знает {', '.join(sorted(ORIGINS))}"
        )

    settings = check_environment()
    lang_key = _lang_key(lang)
    params = {
        "tenant": tenant,
        "lang": lang_key,
        "key": key,
        "code": code,
        # Дословно, как сказал человек: снимаются только края. Схлопывать
        # пробелы внутри — это уже правка показания, а разбирать промахи
        # управляющая компания будет по тому, что сказано, а не по тому, что
        # мы сочли опрятным. Ключ поиска от этого не зависит: он свой
        # (`phrase_normalized`) и приведён к единому виду.
        "phrase": text.strip(),
        "origin": origin,
    }
    try:
        with psycopg.connect(settings.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_TENANT_SQL, (tenant,))
                cur.execute(_REMEMBER_SQL, params)
                row = cur.fetchone()
                if row is not None:
                    conn.commit()
                    return PhraseMemory(REMEMBERED, _row_to_alias(row))
                # Строка уже есть — читаем её ТОЙ ЖЕ транзакцией: между
                # вставкой и отдельным запросом синоним мог бы завести
                # соседний обход, и вызывающий узнал бы о разночтении,
                # которого не было.
                cur.execute(_LOOKUP_SQL, {"tenant": tenant, "lang": lang_key, "key": key})
                известная = cur.fetchone()
            conn.commit()
    except psycopg.Error as exc:
        raise SynonymError(
            f"Синоним «{text.strip()}» не записан ({type(exc).__name__}): {exc}"
        ) from exc
    if известная is None:
        raise SynonymError(
            "Postgres не отдал синоним ни после записи, ни после конфликта — "
            "целостность транзакции нарушена"
        )
    alias = _row_to_alias(известная)
    outcome = ALREADY_KNOWN if alias.item_code == code else CONFLICT
    return PhraseMemory(outcome, alias)


def list_phrases(
    *,
    lang: str | None = None,
    item_code: str | None = None,
    tenant: str = DEFAULT_TENANT,
) -> list[PhraseAlias]:
    """Карта арендатора: целиком или отбором по языку и по пункту.

    Два разных вопроса одним запросом. «Что мы знаем на этом языке» — то, чем
    ярус выше сопоставляет сказанное, не ходя в базу на каждую фразу. «Как ещё
    называют этот пункт» — то, что спросит управляющая компания, разбирая
    промахи.
    """
    settings = check_environment()
    code = item_code.strip() if item_code else None
    params = {
        "tenant": tenant,
        "lang": _lang_key(lang) if lang else None,
        "code": code or None,
    }
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_LIST_SQL, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise SynonymError(f"Карта синонимов недоступна ({type(exc).__name__}): {exc}") from exc
    return [_row_to_alias(row) for row in rows]
