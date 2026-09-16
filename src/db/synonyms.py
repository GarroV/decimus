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

from .config import check_environment, load_retraction_settings
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
#: * `CONFLICT` — был и ведёт к ДРУГОМУ пункту; строка не тронута;
#: * `RETRACTED` — был и СНЯТ управляющей компанией (T292): заново не
#:   заводится. Это и есть главное свойство снятия — иначе следующий обход
#:   вернул бы ровно ту ошибку, ради которой синоним снимали.
REMEMBERED = "remembered"
ALREADY_KNOWN = "already_known"
CONFLICT = "conflict"
RETRACTED = "retracted"

#: Исходы ПРАВКИ карты (T292) — того, что делает управляющая компания, а не
#: машина. Коды отдельные, а не те же самые: «запомнил» и «переправил» — разные
#: события, и слитые в один словарь они заставили бы вызывающего гадать, чем
#: кончился его вызов.
#:
#: * `ALREADY_RETRACTED` — синоним уже был снят; записанная причина НЕ
#:   переписана (иначе снятие стало бы способом править основание задним
#:   числом);
#: * `REPOINTED` — живой синоним переправлен на другой пункт;
#: * `ALREADY_POINTED` — живой синоним уже ведёт к этому пункту, ничего
#:   не менялось;
#: * `RESTORED` — снятый синоним возвращён в работу: с тем же пунктом или с
#:   другим.
#:
#: `RETRACTED` в этом ряду тоже участвует: им отвечает и само снятие. Код один
#: потому, что говорит он одно и то же — строка в базе снята.
ALREADY_RETRACTED = "already_retracted"
REPOINTED = "repointed"
ALREADY_POINTED = "already_pointed"
RESTORED = "restored"

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
    """Строка карты: как сказал человек и к какому пункту это привело.

    Поля правки (T292) заданы со значением по умолчанию не для удобства, а
    чтобы уже написанный потребитель карты (T285) продолжал собирать строку
    теми же шестью полями, что были в контракте T284: добавление поля без
    значения по умолчанию сломало бы его сборку молча и не по его вине.
    """

    item_code: str
    lang: str
    phrase: str
    key: str
    origin: str
    created_at: datetime
    #: Снят управляющей компанией (T292). `None` — синоним живой. Снятая
    #: строка не удаляется и держит свой ключ: поэтому машина не выучивает ту
    #: же формулировку заново.
    retracted_at: datetime | None = None
    #: Почему сняли. Есть ровно тогда, когда есть отметка снятия — это держит
    #: ограничение схемы, а не порядок присваиваний здесь.
    retraction_reason: str | None = None
    #: Когда человек переправил синоним на другой пункт. `None` — пункт
    #: ставился один раз, тем, кто завёл строку.
    corrected_at: datetime | None = None
    #: Зачем переправили.
    correction_reason: str | None = None
    #: Куда строка вела ДО правки — чтобы промах модели остался виден после
    #: исправления.
    previous_item_code: str | None = None


@dataclass(frozen=True)
class PhraseMemory:
    """Чем закончилась попытка запомнить: исход кодом и строка, лежащая в базе."""

    outcome: str
    alias: PhraseAlias


@dataclass(frozen=True)
class PhraseEdit:
    """Чем закончилась правка карты: исход кодом и строка ПОСЛЕ правки (T292).

    Отдельный тип от `PhraseMemory`, хотя устроен так же: запоминание и правка
    — разные события с разными исходами, и общий тип подсказывал бы, что
    исходы у них общие.
    """

    outcome: str
    alias: PhraseAlias


# Запросы печатают список колонок целиком, а не собирают его из общего куска
# строкой: динамическая сборка текста SQL — ровно то, что ловит S608, и здесь
# ей взяться неоткуда не по обещанию, а по устройству кода (тот же приём и то
# же объяснение в `queries.py`).
#: Строка карты как она есть, включая снятую. Читают этим запросом запись и
#: правка: обеим нужно видеть снятую строку — первой, чтобы не объявить пустоту
#: вместо «формулировка снята», второй, чтобы было что возвращать в работу.
_ROW_SQL = """
select item_code, lang, phrase, phrase_normalized, origin, created_at,
       retracted_at, retraction_reason, corrected_at, correction_reason, previous_item_code
from phrase_aliases
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
"""

#: А поиск видит только ЖИВЫЕ строки: снятый синоним никуда не ведёт, в этом и
#: состоит снятие. Отсечение стоит в запросе, а не в политике, — почему именно
#: так, разобрано в конце миграции `0013`.
_LOOKUP_SQL = """
select item_code, lang, phrase, phrase_normalized, origin, created_at,
       retracted_at, retraction_reason, corrected_at, correction_reason, previous_item_code
from phrase_aliases
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
  and retracted_at is null
"""

# `do nothing`, а не `do update`: синоним, который уже работает, не
# переписывается ошибкой одного аудитора. Прав на UPDATE у роли приложения нет
# вовсе (миграция `0012`), то есть это свойство базы, а не дисциплина вызовов.
_REMEMBER_SQL = """
insert into phrase_aliases (tenant_code, lang, phrase_normalized, item_code, phrase, origin)
values (%(tenant)s, %(lang)s, %(key)s, %(code)s, %(phrase)s, %(origin)s)
on conflict (tenant_code, lang, phrase_normalized) do nothing
returning item_code, lang, phrase, phrase_normalized, origin, created_at,
          retracted_at, retraction_reason, corrected_at, correction_reason, previous_item_code
"""

_INSERT_TENANT_SQL = "insert into tenants (code) values (%s) on conflict (code) do nothing"

# Карта берётся целиком намеренно, без предела выдачи: синонимов у арендатора
# столько, сколько пунктов методики, помноженных на способы их назвать, —
# сотни строк, а не миллионы. Предел здесь означал бы карту, обрезанную молча:
# пропавший синоним выглядит как «система разучилась», а не как «выдача
# кончилась». Отбор по языку и по пункту для того и есть, чтобы спрашивать
# нужное, а не всё.
_LIST_SQL = """
select item_code, lang, phrase, phrase_normalized, origin, created_at,
       retracted_at, retraction_reason, corrected_at, correction_reason, previous_item_code
from phrase_aliases
where tenant_code = %(tenant)s
  and (%(lang)s::text is null or lang = %(lang)s)
  and (%(code)s::text is null or item_code = %(code)s)
  and (%(retracted_too)s::boolean or retracted_at is null)
order by lang, phrase_normalized
"""


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _row_to_alias(row: tuple[Any, ...]) -> PhraseAlias:
    return PhraseAlias(
        item_code=str(row[0]),
        lang=str(row[1]),
        phrase=str(row[2]),
        key=str(row[3]),
        origin=str(row[4]),
        created_at=row[5],
        retracted_at=row[6],
        retraction_reason=_text_or_none(row[7]),
        corrected_at=row[8],
        correction_reason=_text_or_none(row[9]),
        previous_item_code=_text_or_none(row[10]),
    )


def _lang_key(lang: str) -> str:
    """Язык одним написанием: «RU» и «ru» — один язык, а не два ключа карты."""
    return lang.strip().casefold()


def _memory_outcome(alias: PhraseAlias, code: str) -> str:
    """Чем кончилась попытка запомнить уже занятый ключ.

    Снятая строка отвечает раньше разночтения намеренно: карта не спорит о
    пункте, она говорит, что эту формулировку сняла управляющая компания. Будь
    иначе, машина получила бы `CONFLICT`, честно переспросила бы аудитора и
    завела бы снятое заново под другим кодом — то есть снятие не значило бы
    ничего (T292).
    """
    if alias.retracted_at is not None:
        return RETRACTED
    return ALREADY_KNOWN if alias.item_code == code else CONFLICT


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
                # которого не было. Читаем ПОЛНУЮ строку, а не живую: место
                # могла занять снятая, и тогда ответ не «не нашлось», а
                # «формулировка снята».
                cur.execute(_ROW_SQL, {"tenant": tenant, "lang": lang_key, "key": key})
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
    return PhraseMemory(_memory_outcome(alias, code), alias)


def list_phrases(
    *,
    lang: str | None = None,
    item_code: str | None = None,
    tenant: str = DEFAULT_TENANT,
    include_retracted: bool = False,
) -> list[PhraseAlias]:
    """Карта арендатора: целиком или отбором по языку и по пункту.

    Два разных вопроса одним запросом. «Что мы знаем на этом языке» — то, чем
    ярус выше сопоставляет сказанное, не ходя в базу на каждую фразу. «Как ещё
    называют этот пункт» — то, что спросит управляющая компания, разбирая
    промахи.

    `include_retracted` по умолчанию выключен, и это не украшение: потребитель
    берёт карту разом и сопоставляет по ней, а попади туда снятая строка —
    снятие не значило бы ничего, поиск шёл бы мимо базы, но по тем же данным.
    Включают его затем, чтобы ПОКАЗАТЬ снятое человеку.

    В отличие от чтения снятых проверок (`list_inspections`), это именно
    фильтр, а не роль: карта синонимов не документ партнёра, прятать её от
    роли приложения не от кого. Разграничение здесь в другом — править карту
    роль приложения не может вовсе.
    """
    settings = check_environment()
    code = item_code.strip() if item_code else None
    params = {
        "tenant": tenant,
        "lang": _lang_key(lang) if lang else None,
        "code": code or None,
        "retracted_too": include_retracted,
    }
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_LIST_SQL, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise SynonymError(f"Карта синонимов недоступна ({type(exc).__name__}): {exc}") from exc
    return [_row_to_alias(row) for row in rows]


# --- правка карты: снятие и перенаправление (T292) ----------------------------
#
# ПРАВИТ НЕ ПРИЛОЖЕНИЕ. Роли приложения на этой таблице выданы только `select`
# и `insert` (`0012`), и расширять их нельзя: выученное не должно
# переписываться ошибкой одного аудитора. Поэтому правка идёт под второй
# непривилегированной ролью — `dodo_audit_admin`, той же, что снимает проверки
# из истории, — и приходит она отдельным подключением
# (`DATABASE_RETRACTION_URL`). Почему той же ролью, а не третьей, разобрано в
# миграции `0013`.
#
# Разграничение обязано держаться правами, а не тем, что этот код никто не
# позовёт из бота: под ролью приложения запросы ниже просто не выполнятся.

_RETRACT_SQL = """
update phrase_aliases
set retracted_at = now(), retraction_reason = %(reason)s
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
  and retracted_at is null
"""

_REPOINT_SQL = """
update phrase_aliases
set item_code = %(code)s, corrected_at = now(),
    correction_reason = %(reason)s, previous_item_code = %(previous)s
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
  and retracted_at is null
"""

#: Возврат снятой строки в работу БЕЗ смены пункта: сняли по ошибке. След
#: правки не трогается — правки кода не было, и записанная сюда она сделала бы
#: строку «исправленной», не исправив ничего.
_RESTORE_SQL = """
update phrase_aliases
set retracted_at = null, retraction_reason = null
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
  and retracted_at is not null
"""

#: Возврат снятой строки в работу С другим пунктом — одним запросом, а не
#: «вернуть, потом переправить»: между двумя запросами строка успела бы
#: побывать живой и ведущей к тому самому неверному пункту, ради которого её
#: снимали.
_RESTORE_REPOINTED_SQL = """
update phrase_aliases
set retracted_at = null, retraction_reason = null,
    item_code = %(code)s, corrected_at = now(),
    correction_reason = %(reason)s, previous_item_code = %(previous)s
where tenant_code = %(tenant)s and lang = %(lang)s and phrase_normalized = %(key)s
  and retracted_at is not null
"""


def _require_key(text: str) -> str:
    """Ключ правки — тот же, что у поиска и у записи.

    Разойдись они хоть на знак, управляющая компания не нашла бы для снятия
    ровно ту строку, которую видит в карте. Пустая формулировка отсекается до
    похода в базу: пустой ключ совпал бы с чем угодно.
    """
    key = normalize_phrase(text)
    if not key:
        raise SynonymError("Формулировка пустая — такой строки в карте нет")
    return key


def _require_reason(reason: str, *, действие: str) -> str:
    """Непустая причина — или явный отказ.

    Причину требует не схема, а смысл: снятая или переправленная строка без
    основания неотличима от подчистки карты (тот же довод, что у снятия
    проверки, D089). Ограничение схемы — второй заслон, и упрись вызывающий
    сперва в него, он увидел бы имя нарушенного `check` вместо того, чего
    не хватает.
    """
    записанное = (reason or "").strip()
    if not записанное:
        raise SynonymError(
            f"Не названа причина {действие}. Причина обязательна: без неё правка "
            f"карты неотличима от подчистки, а разбирать промахи по такой карте "
            f"нечем"
        )
    return записанное


def _require_item_code(item_code: str) -> str:
    code = item_code.strip()
    if not code:
        raise SynonymError("У синонима нет кода пункта — такая строка никуда не ведёт")
    return code


def _read_row(cur: psycopg.Cursor[Any], params: dict[str, Any]) -> PhraseAlias:
    """Строка карты вместе со снятой — или отказ, а не молчаливый ноль правок.

    Вызывающий просил конкретную формулировку. Ответ «затронуто ноль строк»
    выглядел бы успехом и оставил бы неверный синоним работать дальше.
    """
    cur.execute(_ROW_SQL, params)
    строка = cur.fetchone()
    if строка is None:
        raise SynonymError(
            f"В карте синонимов арендатора {params['tenant']} нет формулировки "
            f"«{params['key']}» на языке «{params['lang']}» — править нечего"
        )
    return _row_to_alias(строка)


def _apply(cur: psycopg.Cursor[Any], sql: str, params: dict[str, Any], *, что: str) -> None:
    """Выполнить правку и проверить, что тронута ровно одна строка.

    Отказ построчной политики молчалив: он не падает, а просто не видит строки
    для записи. Поэтому проверяется результат, а не отсутствие исключения
    (конституция).
    """
    cur.execute(sql, params)
    if cur.rowcount != 1:
        raise SynonymError(
            f"{что} не удалось: затронуто строк — {cur.rowcount}, ожидалась одна. "
            f"Так выглядит и отказ построчной политики: подключение обязано идти "
            f"под ролью администратора, иначе строка для записи просто не видна"
        )


def retract_phrase(
    text: str, *, lang: str, reason: str, tenant: str = DEFAULT_TENANT
) -> PhraseEdit:
    """Снять синоним с работы. Пометкой, а не удалением строки.

    Строка остаётся и держит свой ключ — в этом и состоит снятие. Удалённая
    строка освободила бы ключ, а свободный ключ означает, что машина выучит ту
    же формулировку заново на следующем же непрямом совпадении и с тем же
    неверным кодом: модель ошибётся так же. Снятие было бы обратимо системой,
    а не человеком, то есть не значило бы ничего.

    Заведённое человеком (`MANUAL`) и накопленное машиной (`LEARNED`)
    снимаются ОДИНАКОВО: неверный синоним неверен независимо от того, кто его
    завёл, а два разных снятия означали бы два места, где можно ошибиться.
    Разница между ними появляется после снятия: машина своё выучила бы заново,
    человек — нет.

    Повторный вызов записанную причину не переписывает (`ALREADY_RETRACTED`):
    иначе снятие превратилось бы в способ править основание задним числом.
    """
    key = _require_key(text)
    причина = _require_reason(reason, действие="снятия синонима")
    settings = load_retraction_settings()
    params = {"tenant": tenant, "lang": _lang_key(lang), "key": key}
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            строка = _read_row(cur, params)
            if строка.retracted_at is not None:
                return PhraseEdit(ALREADY_RETRACTED, строка)
            _apply(cur, _RETRACT_SQL, {**params, "reason": причина}, что="Снятие синонима")
            снятая = _read_row(cur, params)
            conn.commit()
    except psycopg.Error as exc:
        raise SynonymError(f"Синоним не снят ({type(exc).__name__}): {exc}") from exc
    return PhraseEdit(RETRACTED, снятая)


def repoint_phrase(
    text: str, *, lang: str, item_code: str, reason: str, tenant: str = DEFAULT_TENANT
) -> PhraseEdit:
    """Переправить синоним на другой пункт — и вернуть снятый в работу.

    Одна операция, потому что вопрос у управляющей компании один: к какому
    пункту эта формулировка ведёт и работает ли она. Исход называет, что
    именно произошло, — `REPOINTED`, `ALREADY_POINTED` или `RESTORED`, — а
    гадать по возвращённой строке вызывающему не приходится.

    Снятая строка возвращается в работу этим же вызовом намеренно. Место в
    карте она держит навсегда: машине ключ не отдадут (`RETRACTED`), человеку
    тоже — заводит синонимы приложение, а у него нет права переписывать. Не
    будь пути назад, снятое по ошибке оставалось бы мёртвым, и чинить его
    пришлось бы накатом — ровно тем, от чего уходит T292.

    Куда строка вела раньше, остаётся записанным (`previous_item_code`):
    исправленный синоним обязан отличаться от изначально верного, иначе разбор
    промахов модели упирается в карту, где все строки выглядят правильными.
    """
    key = _require_key(text)
    code = _require_item_code(item_code)
    причина = _require_reason(reason, действие="правки синонима")
    settings = load_retraction_settings()
    params = {"tenant": tenant, "lang": _lang_key(lang), "key": key}
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            строка = _read_row(cur, params)
            смена_пункта = строка.item_code != code
            правка = {**params, "code": code, "reason": причина, "previous": строка.item_code}
            if строка.retracted_at is None:
                if not смена_пункта:
                    return PhraseEdit(ALREADY_POINTED, строка)
                _apply(cur, _REPOINT_SQL, правка, что="Правка синонима")
                исход = REPOINTED
            else:
                запрос = _RESTORE_REPOINTED_SQL if смена_пункта else _RESTORE_SQL
                _apply(cur, запрос, правка, что="Возврат синонима в работу")
                исход = RESTORED
            правленая = _read_row(cur, params)
            conn.commit()
    except psycopg.Error as exc:
        raise SynonymError(f"Синоним не переправлен ({type(exc).__name__}): {exc}") from exc
    return PhraseEdit(исход, правленая)
