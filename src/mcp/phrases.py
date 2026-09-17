"""Карта синонимов формулировок глазами управляющей компании (T294).

Машина учится на непрямых попаданиях: сказал аудитор иначе или с опечатками —
разобранная формулировка ложится в карту синонимом пункта и работает при
следующем поиске (D119, T285). Выученное этим и ценно, и опасно: неверно
привязанная формулировка молча ведёт к чужому пункту на каждой следующей
проверке, а увидеть её было негде — карта лежала в базе и наружу не
показывалась.

Три правила, которые здесь важнее удобства.

**Отдельное действие — отдельный инструмент** (D125). Посмотреть, снять и
переправить — три вызова с тремя именами, а не один с флагом: флаг означал бы,
что необратимое действие достигается опечаткой в аргументах читающего вызова.

**Карта открывается правом МЕТОДИКИ, а не правом на историю партнёра.** В ней
лежат сырые формулировки аудиторов всех точек без разделения по смыслу, а
правит её тот же человек, что правит чек-лист, — управляющая компания. Тот же
довод и то же место права, что у накопителя непокрытых слов
(`uncovered.py`): партнёрскому токену карта не открывается заодно с историей
его пиццерий. Право на снятие ПРОВЕРКИ (`MCP_RETRACTION_TOKENS`) здесь ни при
чём: там отзывается выданный партнёру документ, здесь правится внутренняя
память продукта.

**Снять — не значит стереть.** Снятие ставит пометку и держит ключ за строкой:
освободи его — и машина выучит ту же формулировку заново, с тем же неверным
кодом. Обратно в работу строку возвращает только человек и только
`repoint_learned_phrase`. Всё это делает слой `db.synonyms` (T292); здесь
граница инструмента: сверка пункта с методикой, перевод отказов на слова
человека и заслон от чужого текста в ответе.

Запросов к базе в этом модуле нет.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from ..db.errors import ConfigError as DbConfigError
from ..db.errors import SynonymError
from . import checklist as store_api
from .checklist import Store
from .errors import ToolError

#: Сколько строк карты показываем, если предел не назван. Карта растёт сама, на
#: каждой непрямой находке, и выдача целиком однажды станет простынёй, которую
#: агент перескажет выборочно и молча.
DEFAULT_PHRASES = 200

#: Отказ на стенде, где базы нет вовсе. Своим текстом, а не пустой картой:
#: «ничего не выучено» и «карту неоткуда прочитать» — разные ответы, и первый
#: агент перескажет человеку как факт о продукте.
NOT_CONNECTED = (
    "Карта синонимов на этом стенде не подключена: не задана переменная окружения "
    "DATABASE_URL. Это законная настройка, а не поломка — проверку бот проводит и без "
    "базы, — но выученные формулировки тогда негде и хранить. Это отказ чтения, а не "
    "пустая карта"
)

#: Отказ на стенде, где карта читается, но не правится. Переменная своя: правку
#: карты роль приложения не делает вовсе — ни снять, ни переправить, — и
#: приходит она отдельным подключением под ролью администратора истории.
CURATION_NOT_CONNECTED = (
    "Правка карты синонимов на этом стенде не настроена: не задана переменная окружения "
    "DATABASE_RETRACTION_URL. Выученное не переписывается ролью приложения намеренно: "
    "иначе ошибка одного аудитора стирала бы память продукта. Снятие и правка идут "
    "отдельным подключением (роль dodo_audit_admin). Это отказ настройки, а не отказ в "
    "правке"
)

#: Чем отказ базы приходит наружу. Текст чужого отказа в ответ не попадает
#: никогда: в сообщении драйвера бывает адрес базы и путь к сокету, а ответ
#: инструмента уходит в модель, то есть за пределы машины (T120).
FOREIGN_FAILURE = (
    "Карта синонимов не ответила ({вид}). Это отказ базы, а не отказ по существу: "
    "подробности остались в логе сервера, он не уезжает с машины. Ни одна строка карты "
    "при этом не осталась наполовину снятой — правка идёт одной транзакцией, и повторный "
    "вызов доделает начатое"
)


@contextmanager
def _карта(*, правка: bool) -> Iterator[None]:
    """Обращение к слою карты: чужие отказы переводятся, чужой текст не уходит.

    Отказ различается по ПРОИСХОЖДЕНИЮ текста, а не разбором строки: `db`
    отвечает одним типом (`SynonymError`) и на отказ по существу («причина не
    названа», «такой формулировки в карте нет»), и на беду окружения — а в
    тексте второго он приводит сообщение драйвера целиком. `__cause__` есть
    ровно там, где чужое исключение обёрнуто, то есть ровно там, где в текст
    подставлен чужой текст (тот же приём и та же причина, что в
    `retraction._retract`).

    Отказы по существу написаны блоком `db` целиком и приходят человеку его
    словами: пересказ здесь разошёлся бы с ними при первой же правке.
    """
    try:
        yield
    except DbConfigError:
        raise ToolError(CURATION_NOT_CONNECTED if правка else NOT_CONNECTED) from None
    except SynonymError as отказ:
        if отказ.__cause__ is not None:
            raise ToolError(FOREIGN_FAILURE.format(вид=type(отказ.__cause__).__name__)) from None
        raise ToolError(str(отказ)) from None


def _слой() -> Any:
    """Слой карты синонимов. Импорт ленивый, как у чтения проверок.

    `src.db.synonyms` тянет `psycopg`, и жадный импорт ронял бы сбор всего
    `tests/` в окружении, где зависимость блока не поставлена (тот же приём и
    та же причина, что в `tools._read`).
    """
    from ..db import synonyms

    return synonyms


def _время(значение: datetime | None) -> str | None:
    return None if значение is None else значение.isoformat()


def _предел(limit: int | None) -> int:
    """Предел выдачи — или отказ. Ноль прочитался бы как «в карте ничего нет»."""
    if limit is None:
        return DEFAULT_PHRASES
    if limit < 1:
        raise ToolError(
            f"Предел limit={limit} не имеет смысла: выдача из нуля строк читается как "
            f"пустая карта. Без предела показывается {DEFAULT_PHRASES} строк, а полное "
            f"число выдача называет сама"
        )
    return limit


def _пункт_методики(store: Store, code: str) -> str:
    """Код пункта, как он записан в действующей методике, — или отказ.

    Сверка идёт ДО базы намеренно. Синоним, переправленный на несуществующий
    код, перестал бы работать молча: быстрый путь не нашёл бы пункта, а в карте
    строка выглядела бы исправленной — то есть промах модели был бы скрыт
    правкой, ничего не исправившей.
    """
    пункт = store_api.read_item(store, code=code, version=store_api.current_version(store))
    return пункт["id"].strip()


def _вид(alias: Any) -> dict[str, object]:
    """Строка карты для агента. Снятая отличима от работающей полями, а не тоном."""
    return {
        "phrase": alias.phrase,
        "key": alias.key,
        "item_code": alias.item_code,
        "lang": alias.lang,
        "origin": alias.origin,
        "created_at": _время(alias.created_at),
        "retracted_at": _время(alias.retracted_at),
        "retraction_reason": alias.retraction_reason,
        "corrected_at": _время(alias.corrected_at),
        "correction_reason": alias.correction_reason,
        "previous_item_code": alias.previous_item_code,
    }


def _пусто(*, tenant: str, lang: str | None, item_code: str | None) -> dict[str, object]:
    """Пустая выдача, которая говорит, ПОЧЕМУ она пустая.

    Отбор по языку, которого в карте нет, и карта, в которой нет ничего, — это
    разные ответы: первый означает опечатку в отборе, второй — что продукт ещё
    ничего не выучил. Неразличимые, они оба читаются как «машина ничего не
    знает», и управляющая компания идёт разбирать промахи не туда.

    Второй запрос делается только здесь, на пустой выдаче: платить за него на
    каждом просмотре незачем.
    """
    with _карта(правка=False):
        вся = _слой().list_phrases(tenant=tenant, include_retracted=True)
    языки = sorted({строка.lang for строка in вся})
    отбор = ", ".join(
        часть
        for часть in (
            f"lang={lang}" if lang else "",
            f"item_code={item_code}" if item_code else "",
        )
        if часть
    )
    if not вся:
        статус = (
            "no learned phrases for this tenant at all: nothing has been learned yet. This "
            "is an empty map, not a failed read"
        )
    elif отбор:
        статус = (
            f"no learned phrase matches this filter ({отбор}); rows in the map, retracted "
            f"ones included: {len(вся)}"
        )
    else:
        # Отбора не было, а выдача пуста — значит работающих строк не осталось
        # вовсе: все сняты. Сказать это прямо важнее, чем повторить «ничего не
        # нашлось»: иначе снятая целиком карта читается как невыученная.
        статус = (
            f"no learned phrase is working right now: every row in the map is retracted "
            f"(rows: {len(вся)}). Ask with include_retracted to see them and to bring back "
            f"one that was retracted by mistake"
        )
    return {
        "phrases": [],
        "total": 0,
        "shown": 0,
        "truncated": False,
        "languages_in_map": языки,
        "status": статус,
    }


def learned_phrases(
    *,
    tenant: str,
    store: Store,
    lang: str | None = None,
    item_code: str | None = None,
    include_retracted: bool = False,
    limit: int | None = None,
) -> dict[str, object]:
    """Что продукт выучил на словах аудиторов: карта синонимов этого арендатора.

    Снятые строки по умолчанию не показываются — ровно как их не видит поиск.
    Показать их отдельно нужно затем, чтобы разбирать промахи и возвращать в
    работу снятое по ошибке; для этого есть `include_retracted`.

    Выдача ничего не выводит и не считает: строки отдаются такими, какими их
    записал продукт, — вместе с тем, откуда строка взялась (`origin`) и куда
    она вела до правки (`previous_item_code`).
    """
    del store  # карта лежит в базе, а не в хранилище версий методики
    предел = _предел(limit)
    with _карта(правка=False):
        строки = _слой().list_phrases(
            tenant=tenant,
            lang=lang,
            item_code=item_code,
            include_retracted=include_retracted,
        )
    if not строки:
        return {"tenant": tenant, **_пусто(tenant=tenant, lang=lang, item_code=item_code)}
    показанные = строки[:предел]
    обрезано = len(строки) > предел
    снятых = sum(1 for строка in строки if строка.retracted_at is not None)
    видно = (
        f"retracted rows are shown too ({снятых} of them)"
        if include_retracted
        else "retracted rows are hidden; ask with include_retracted to see them"
    )
    обрезка = (
        f"; cut off at limit={предел}, the rest is not shown"
        if обрезано
        else "; nothing is cut off"
    )
    return {
        "tenant": tenant,
        "phrases": [_вид(строка) for строка in показанные],
        "total": len(строки),
        "shown": len(показанные),
        "truncated": обрезано,
        "status": f"{len(показанные)} of {len(строки)} learned phrases, {видно}{обрезка}",
    }


def retract_learned_phrase(
    *, tenant: str, store: Store, phrase: str, lang: str, reason: str
) -> dict[str, object]:
    """Снять выученную формулировку с работы. Пометкой, а не удалением строки.

    Ключ остаётся за строкой: освободи его — и на следующем же непрямом
    совпадении машина выучит ту же формулировку заново, с тем же неверным
    кодом, то есть снятие было бы обратимо системой, а не человеком.

    Причина обязательна и записывается один раз: повторное снятие её не
    переписывает, поэтому и приходит отказом. Ответ «готово» на вызов, который
    ничего не записал, агент однажды перескажет человеку как «причина принята».
    """
    del store  # пункт здесь не называют: снимается строка, а не связь с пунктом
    слой = _слой()
    with _карта(правка=True):
        правка = слой.retract_phrase(phrase, lang=lang, reason=reason, tenant=tenant)
    строка = правка.alias
    if правка.outcome == слой.ALREADY_RETRACTED:
        raise ToolError(
            f"Формулировка «{строка.phrase}» ({строка.lang}) снята раньше, причина записана "
            f"тогда же и здесь не переписывается: снятие — не способ править основание "
            f"задним числом. Записанная причина: «{строка.retraction_reason}». Сейчас "
            f"ничего не снято. Вернуть строку в работу можно вызовом "
            f"repoint_learned_phrase — он же ставит пункт, к которому она должна вести"
        )
    return {
        "tenant": tenant,
        "phrase": строка.phrase,
        "key": строка.key,
        "lang": строка.lang,
        "item_code": строка.item_code,
        "retracted_at": _время(строка.retracted_at),
        "reason": строка.retraction_reason,
        "status": (
            "learned phrase retracted: the search no longer matches it, and no record will "
            "be proposed by it again. The row itself stays and keeps its place in the map, "
            "so the machine cannot learn the same wording back on its own. Only a person "
            "brings it back into work, and only with repoint_learned_phrase"
        ),
    }


def repoint_learned_phrase(
    *, tenant: str, store: Store, phrase: str, lang: str, item_code: str, reason: str
) -> dict[str, object]:
    """Переправить выученную формулировку на другой пункт — и вернуть снятую в работу.

    Один вызов, потому что вопрос у управляющей компании один: к какому пункту
    эта формулировка ведёт и работает ли она вообще. Что именно произошло,
    называет поле `outcome`, а не догадка по возвращённой строке.

    Пункт сверяется с ДЕЙСТВУЮЩЕЙ методикой до похода в базу: код с опечаткой
    записался бы молча, и строка выглядела бы исправленной, перестав работать.
    """
    код = _пункт_методики(store, item_code)
    слой = _слой()
    with _карта(правка=True):
        правка = слой.repoint_phrase(phrase, lang=lang, item_code=код, reason=reason, tenant=tenant)
    строка = правка.alias
    if правка.outcome == слой.ALREADY_POINTED:
        raise ToolError(
            f"Формулировка «{строка.phrase}» ({строка.lang}) и так ведёт к пункту "
            f"{строка.item_code}: ничего не изменилось и причина не записана. Если строка "
            f"ведёт не туда — назовите другой пункт; если она не должна работать вовсе — "
            f"это retract_learned_phrase"
        )
    вернули = правка.outcome == слой.RESTORED
    статус = (
        (
            "learned phrase is back in work: the search matches it again, now leading to "
            f"{строка.item_code}. Where it led before stays recorded, so the miss it came "
            "from is still visible"
        )
        if вернули
        else (
            f"learned phrase now leads to {строка.item_code}. Where it led before stays "
            "recorded in previous_item_code: a corrected row must stay tellable from one "
            "that was right from the start, or the misses of the model cannot be reviewed"
        )
    )
    return {
        "tenant": tenant,
        "phrase": строка.phrase,
        "key": строка.key,
        "lang": строка.lang,
        "item_code": строка.item_code,
        "previous_item_code": строка.previous_item_code,
        "corrected_at": _время(строка.corrected_at),
        "reason": строка.correction_reason,
        "outcome": правка.outcome,
        "status": статус,
    }
