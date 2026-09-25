"""Раздел «Проверки»: что показать и чем это взято.

Ни одной цифры собственного производства. Процент, буква, вычеты, разбивка по
зонам и счётчики классов приезжают из базы такими, какими их положил движок при
завершении проверки, и отсюда идут прямо в шаблон. Арифметики в этом модуле нет
вовсе — это техническая гарантия принципа «оценка считается движком, и только
им», а не обещание: импорт `engine` из `src.web` роняет прогон (контракт
`engine-not-imported` в `lint-imports`).

Свой SQL поверх тех же таблиц здесь тоже не пишется: чтение — `src/db/queries`,
снятие — `src/db/retract` (D086/D089). Второго понятия «удаление» в админке не
заводится.

**«Снятых нет» и «вам их не видно» — разные ответы.** Снятые проверки видит
только администратор истории, и приходит он отдельным подключением
(`DATABASE_RETRACTION_URL`). Когда его нет, страница говорит об этом вслух, а
не показывает молча укороченный список.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.db import letters as letters_store
from src.db import move, queries, retract
from src.db.config import load_retraction_settings
from src.db.errors import DbError, MoveError
from src.db.models import InspectionDetail, InspectionRow, ItemUsage
from src.domain.models import TEXT_LANGS
from src.report.letters import LetterError
from src.report.letters import build as build_letter
from src.report.letters import sources as letter_sources

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Registry:
    """Реестр проверок вместе с ответом на вопрос «а всё ли я вижу»."""

    rows: tuple[InspectionRow, ...]
    #: Видны ли снятые проверки. `False` — не «их нет», а «подключение
    #: администратора истории не задано»; страница обязана сказать это словами.
    retracted_visible: bool

    @property
    def retracted_count(self) -> int:
        return sum(1 for row in self.rows if row.retracted)


def retraction_available() -> bool:
    """Задано ли подключение администратора истории.

    Отдельной функцией, потому что ответ нужен двум местам сразу: реестру
    (показывать ли снятые) и карточке (предлагать ли снятие). Связь с базой
    здесь не проверяется — только наличие настройки; поломка подключения
    вылезет отказом на самом вызове, и переспрашивать её заранее значило бы
    ходить в сеть дважды.
    """
    try:
        load_retraction_settings()
    except DbError:
        return False
    return True


def load_registry(*, tenant: str, limit: int) -> Registry:
    """Проверки тенанта, свежие по дате обхода — первыми."""
    if retraction_available():
        try:
            rows = queries.list_inspections(tenant=tenant, limit=limit, include_retracted=True)
            return Registry(rows=tuple(rows), retracted_visible=True)
        except DbError as exc:
            _log_admin_read_failed("реестр", exc)
    rows = queries.list_inspections(tenant=tenant, limit=limit)
    return Registry(rows=tuple(rows), retracted_visible=False)


def _log_admin_read_failed(where: str, exc: DbError) -> None:
    """Сбой подключения администратора истории — в лог, а экран живёт дальше.

    Настройка необязательная, и ронять из-за неё главный экран нельзя (#307):
    21.09.2026 неверный адрес этого подключения давал 503 «База недоступна» на
    всём реестре при живой базе, а в логе не было ни строки. Экран читается
    обычной ролью — без снятых, — а причина уходит сюда, чтобы её было где
    найти. Если лежит сама база, обычное чтение упадёт следом и честно даст 503.
    """
    logger.warning(
        "%s: чтение под администратором истории не удалось, показано без снятых: %s",
        where,
        exc,
    )


def load_card(inspection_id: str, *, tenant: str) -> InspectionDetail | None:
    """Проверка целиком: шапка, разбивка оценки, находки, информационная часть.

    `None` — проверки у тенанта нет. Тем же `None` отвечает снятая проверка,
    когда снятые не видны: «такой проверки нет» и «вам её не видно» снаружи
    неразличимы намеренно (`queries.get_inspection`).
    """
    if retraction_available():
        try:
            return queries.get_inspection(inspection_id, tenant=tenant, include_retracted=True)
        except DbError as exc:
            _log_admin_read_failed("карточка проверки", exc)
    return queries.get_inspection(inspection_id, tenant=tenant)


#: Языки, на которых письмо вообще может быть собрано. Берутся у МЕТОДИКИ
#: (`domain.models.TEXT_LANGS`), а не перечисляются здесь: свой список
#: предложил бы человеку язык, которого в методике нет, и переключение
#: кончалось бы отказом сборщика на ровном месте. Языку ИНТЕРФЕЙСА он не
#: равен и равным не станет: интерфейс и письмо — разные языки (`CLAUDE.md`).
LETTER_LANGS = TEXT_LANGS


@dataclass(frozen=True)
class Letter:
    """Письмо партнёру по записанной проверке — или причина, по которой его нет.

    Три состояния, а не два, и средним из них всё и держится. Письмо может
    собраться и при этом НЕ годиться к отправке: движок печатает связный,
    подписанный текст с верной оценкой, а шапка в нём пустая, срок подставлен
    расчётом вместо ответа аудитора или половина находок на языке записи.
    Такое письмо выглядит готовым — именно поэтому «собралось» и «можно
    отправлять» здесь разные поля, и второе показывается на экране рядом с
    текстом, а не выводится человеком из вида письма.
    """

    #: Текст письма. `None` — собрать не вышло, причина в `failure`.
    text: str | None
    #: Язык, на котором письмо собрано. По умолчанию — язык ОТЧЁТА проверки, а
    #: не язык интерфейса: партнёру пишут на его языке, а не на языке того, кто
    #: открыл админку.
    lang: str | None
    #: Откуда взята методика той версии, которой помечена проверка: снимок или
    #: боевой каталог. Человеку это важно — письмо, собранное по сегодняшней
    #: методике, несло бы партнёру другую букву под прежней датой.
    source: str | None
    #: Можно ли это отправлять как есть.
    ready: bool
    #: Что именно не восстановилось — кодами полей сборщика (`COVER_FIELDS`,
    #: `PLAN_DUE_FIELD`, `FINDING_TEXT_FIELD`, `BLANK_TEXT_FIELD`). Словами их
    #: называет уже интерфейс, на своём языке: `status` сборщика написан
    #: по-английски для инструмента модели, и на экране он был бы чужим языком
    #: посреди русской страницы.
    caveats: tuple[str, ...]
    #: Почему письма нет вовсе. Слова сборщика, без путей с диска.
    failure: str | None

    @property
    def built(self) -> bool:
        return self.text is not None


def load_letter(detail: InspectionDetail, *, lang: str | None = None) -> Letter:
    """Письмо партнёру по уже прочитанной проверке.

    Проверку сюда передают, а не читают второй раз: карточку экран берёт всё
    равно, и второе чтение той же строки означало бы, что шапка над письмом и
    само письмо собраны по двум разным снимкам одной проверки.

    **Пересборка, а не хранение.** Письмо в базе не лежит: его формирует и
    отправляет человек из почты (Q010, D035), а система держит историю
    проверок. Поэтому текст собирается заново — движком, по методике ТОЙ
    версии, которой помечена проверка, и только после того, как посчитанное
    движком сошлось с записанным в базе.

    **Своей сборки здесь нет ни строки.** Правило целиком живёт в
    `src/report/letters.py` — там же, откуда его берёт MCP. Второй экземпляр
    разошёлся бы с первым молча, а увидел бы это партнёр: у него на руках
    оказалось бы письмо, не совпадающее с тем, что система считает отправленным.

    Отказ сборщика страницу не роняет и в 500-ю не превращается: методики той
    версии может не оказаться на диске, и это обычный исход, а не поломка кода.
    Причина говорится словами.
    """
    try:
        собранное = build_letter(detail, lang=lang, papers=letter_sources())
    except LetterError as отказ:
        return Letter(
            text=None, lang=None, source=None, ready=False, caveats=(), failure=str(отказ)
        )
    # Сборщик отдаёт словарь свободной формы — он написан для инструмента
    # модели, где значения уезжают в JSON. Перечень невосстановленного
    # разбирается здесь по факту, а не по обещанию: пустой кортеж на месте
    # непонятного значения означал бы «всё восстановилось», то есть ровно ту
    # ложь, ради предотвращения которой перечень и заведён.
    сырое = собранное.get("not_restored")
    не_восстановлено = tuple(str(код) for код in сырое) if isinstance(сырое, list) else ()
    return Letter(
        text=str(собранное["letter"]),
        lang=str(собранное["lang"]),
        source=str(собранное["methodology"]),
        ready=bool(собранное["ready_to_send"]),
        caveats=не_восстановлено,
        failure=None,
    )


def retract_card(inspection_id: str, *, tenant: str, reason: str) -> retract.Retraction:
    """Снять проверку из истории. Отказ — `RetractionError` блока `db`.

    Своей проверки причины здесь нет: обязательность причины — правило снятия
    (D089), и живёт оно в `src/db/retract.py`. Продублированное здесь, оно
    разошлось бы с оригиналом при первой же правке.
    """
    return retract.retract_inspection(inspection_id, tenant=tenant, reason=reason)


def load_geography(*, tenant: str) -> dict[str, tuple[str, str]]:
    """География точек `{название: (страна, город)}` — для отбора реестра.

    Отказ базы здесь — не повод не показать реестр: без географии отбор по
    стране и городу просто не предлагается, а список проверок остаётся.
    """
    try:
        return queries.unit_geography(tenant=tenant)
    except DbError as exc:
        logger.warning("география точек недоступна, отбор по месту не показан: %s", exc)
        return {}


def load_item_usage(*, tenant: str, code: str, checklist: str) -> ItemUsage | None:
    """Как часто пункт нарушают — для панели «Методики» (D197). `None` — база молчит.

    Сводка — подсказка к правке, а не часть методики: без неё пункт правится
    так же, поэтому отказ базы не роняет экран, а называется на нём строкой.
    """
    try:
        return queries.item_usage(tenant=tenant, code=code, checklist=checklist)
    except DbError as exc:
        logger.warning("сводка пункта %s недоступна: %s", code, exc)
        return None


def move_card(
    inspection_id: str, *, tenant: str, new_date: str, new_unit_id: str, reason: str, actor: str
) -> bool:
    """Перенести проверку по дате и пиццерии (D195). Отказ — `MoveError`.

    Здесь только разбор даты из формы. Обязательность причины, запрет на
    отклонённую и чужую пиццерию — правила переноса, они живут в
    `src/db/move.py` и в самой базе.
    """
    try:
        дата = date.fromisoformat((new_date or "").strip())
    except ValueError:
        raise MoveError("Дата не указана или указана не в формате ГГГГ-ММ-ДД") from None
    return move.move_inspection(
        inspection_id,
        tenant=tenant,
        new_date=дата,
        new_unit_id=new_unit_id,
        reason=reason,
        actor=actor,
    )


def load_moves(inspection_id: str, *, tenant: str) -> tuple[move.MoveRecord, ...]:
    """История переносов карточки, свежие первыми."""
    return move.list_moves(inspection_id, tenant=tenant)


def load_units(*, tenant: str) -> tuple[tuple[str, str], ...]:
    """Пиццерии справочника для выбора при переносе: `(id, название)` по алфавиту."""
    return tuple(
        sorted(
            ((ид, имя) for имя, ид in queries.unit_ids(tenant=tenant).items()), key=lambda x: x[1]
        )
    )


def saved_letter(
    inspection_id: str, *, lang: str | None = None
) -> letters_store.SavedLetter | None:
    """Зафиксированное письмо этой проверки — или `None`, если его не фиксировали.

    Разница с `load_letter` не в источнике, а в смысле. `load_letter` собирает
    ЗАГОТОВКУ: она пересобирается каждый раз и от пересборки меняется — правка
    методики, новый шаблон, другая версия движка. Здесь — то, что человек
    прочитал, поправил и подтвердил как отправляемое, и оно не меняется ничем.

    Показывать их одинаково нельзя: у партнёра на руках лежит один-единственный
    текст, и выдать за него сегодняшнюю заготовку значит ответить на вопрос
    «что мы отправили» правдоподобной неправдой.
    """
    return letters_store.latest_letter(inspection_id, lang=lang)


def remember_letter(
    inspection_id: str, *, body: str, lang: str, saved_by: str
) -> letters_store.SavedLetter:
    """Зафиксировать письмо так, как его подтвердил человек.

    Своей проверки текста здесь нет ни строки — она в `src/db/letters.py`, там
    же, где запись. Вторая копия правил разошлась бы с первой молча.
    """
    return letters_store.save_letter(inspection_id, body=body, lang=lang, saved_by=saved_by)
