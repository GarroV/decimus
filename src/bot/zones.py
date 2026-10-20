"""Зона из слов аудитора (задача T124, решения D047 и D048, правило 6).

Зону определяет человек. Правило 6 `docs/03-recording-rules.md` сформулировано
прямо: «Зону определяет человек или разбор его комментария, но не догадка
модели по внешнему виду кадра» — «стена за кассовой стойкой это зал, а не
мойка, даже если рядом стоит ведро». Спека того же требует словами аудитора:
«я хочу, чтобы зона бралась из моих слов».

Отдельного шага «выберите зону» в разговоре нет и не будет (D047): аудитор идёт
по точке с занятыми руками. Значит, единственный источник — сам комментарий, а
память о прошлой записи (D048) остаётся тем, чем её и назвал владелец: **первой
догадкой**, когда о зоне в этих словах ничего не сказано.

**Названия зон берутся из методики, а не из списка в коде.** Управляющая
компания правит `data/zones.csv`, и переименованная зона обязана начать
узнаваться сама. В коде живёт только то, чего в методике нет и быть не может, —
как эту зону называют вслух («зал» вместо полного названия зоны из методики). Список
короткий намеренно и растёт по факту, а не по фантазии: каждая строка ниже
взята либо из слов владельца, либо из формулировок боевых проверок в
`examples/`. Выдумывать за управляющую компанию, какими словами говорят
аудиторы, здесь нельзя — тем же правилом живёт словарь `recognize.fastpath`.

**Совпадение — по строке целиком, длинная сильнее короткой.** Холодильное
оборудование, названное внутри фразы про горячий цех, — это горячий цех:
строка «горячий цех» произнесена из двух слов, а название низкотемпературной
зоны не произнесено вовсе. Названы две зоны разом —
разбор не выбирает за человека и молчит: пусть подставится память, которую
видно и меняют одним нажатием.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal

from src import domain
from src.domain.errors import DomainError
from src.recognize import zone_words
from src.recognize.config import DEFAULT_MIN_CONFIDENCE
from src.recognize.cues import load_cues, matched_cues

# Разбор слов аудитора переехал в `recognize.zone_words` (#1015): им пользуется и
# MCP. Прежние имена остаются здесь — их зовут бот, веб, замеры и тесты.
ABBREVIATIONS = zone_words.ABBREVIATIONS
SPOKEN = zone_words.SPOKEN
named_places = zone_words.named_places
phrases = zone_words.phrases
qualifiers = zone_words.qualifiers
zone_from_words = zone_words.zone_from_words

logger = logging.getLogger(__name__)

#: Откуда взялась зона. Прошлая запись источником не становится никогда
#: (T264, #218), а догадка модели по виду кадра запрещена правилом 6
#: `docs/03-recording-rules.md`: `MODEL` — это зона, которую модель взяла из
#: слов аудитора и назвала уверенно (#838), и только из зон пункта.
WORDS: Final = "words"
DICTIONARY: Final = "dictionary"
#: Методика даёт пункту ровно одну зону (#838): это ответ, а не догадка.
ITEM: Final = "item"
MODEL: Final = "model"
ASK: Final = "ask"

ZoneSource = Literal["words", "dictionary", "item", "model", "ask"]

#: Порог уверенности модели, с которого её зона берётся без вопроса (#838).
#: Тот же, ниже которого сам ответ модели уходит к человеку (`needs_human`,
#: `recognize.config`): отдельного числа для зоны заводить незачем; ниже порога
#: бот спрашивает, как и раньше.
MODEL_ZONE_MIN_CONFIDENCE: Final = DEFAULT_MIN_CONFIDENCE


@dataclass(frozen=True)
class ZoneConflict:
    """Названная зона разошлась с зоной объекта из карты кадров (T263).

    Случай владельца: «холодный цех, пицца-печь». Печь живёт только в горячем
    цехе, и обе стороны сразу правдой быть не могут — либо аудитор назвал не то
    место, либо речь о другом объекте. Молча не пишется ни то, ни другое:
    расхождение называется ему до фиксации, с выбором «зона объекта или другой
    пункт».
    """

    #: Зона, названная аудитором словами.
    spoken: str
    #: Зона, которую карта кадров держит за названным объектом.
    dictionary: str
    #: Сам объект — то, чем расхождение объясняется человеку.
    phrase: str


@dataclass(frozen=True)
class ZoneResolution:
    """Одна точка вывода зоны вместо четырёх мест подстановки (T263)."""

    #: Зона, если она вывелась. `None` — её предстоит спросить.
    zone: str | None
    #: Чем она выведена: слова аудитора, словарь объектов, сам пункт, зона от
    #: модели или ничем.
    source: ZoneSource
    #: Зоны, допустимые методикой для `item_code`, — и только они. Спрашивать
    #: тем, чего движок не примет, нельзя (T266, T271).
    options: tuple[str, ...]
    #: Расхождение названной зоны со словарём, если оно есть.
    conflict: ZoneConflict | None = None


def allowed_zones(item_code: str | None, *, chat_id: int | None) -> tuple[str, ...]:
    """Зоны, которые методика даёт этому пункту, в порядке методики.

    Пункт не назван или методика такого не знает — все зоны: сузить перечень
    нечем, а показать неполный значило бы отнять у аудитора верный ответ.
    Пункт «во всех зонах» (`*` или пусто) читается так же, как читает движок
    (`ChecklistItem.applies_to`), а не вторым правилом рядом.
    """
    зоны = [zone.code for zone in domain.list_zones(chat_id=chat_id)]
    if item_code is None:
        return tuple(зоны)
    try:
        пункт = domain.get_item(item_code, chat_id=chat_id)
    except DomainError:
        return tuple(зоны)
    return tuple(code for code in зоны if пункт.applies_to(code))


def dictionary_zone(note: str, *, chat_id: int | None) -> tuple[str, str] | None:
    """Зона объекта из карты кадров и сам объект. Не вывелась — `None`.

    Публичная не для продукта, а для замера: `tools/fastpath_measure.py` и
    `tools/zone_coverage.py` обязаны звать ТУ ЖЕ выборку, которой зовёт бот.
    Своя копия правил в замере разошлась бы с продуктом при первой правке и
    дала бы число, которого на точке не бывает, — ровно тем этот замер и был
    неверен до T125.

    Зон несколько — не вывелась: объект стоит в разных цехах, и выбирать за
    человека разбор не вправе (случай стеллажа). Код, которого нет в
    справочнике зон этого издания, отбрасывается с записью в журнал: это
    опечатка управляющей компании, и молча подставленная она увела бы запись в
    несуществующее место, а отказ посреди разговора с аудитором сделал бы
    необязательный файл обязательным (D068).
    """
    known = {zone.code for zone in domain.list_zones(chat_id=chat_id)}
    hit: tuple[str, str] | None = None
    for cue in matched_cues(note, load_cues(chat_id=chat_id)):
        if not cue.zone:
            continue
        if cue.zone not in known:
            logger.warning(
                "карта кадров: у объекта «%s» зона «%s», которой нет в методике этого издания",
                cue.phrase,
                cue.zone,
            )
            continue
        if hit is None:
            hit = (cue.zone, cue.phrase)
        elif hit[0] != cue.zone:
            return None
    return hit


def resolve_zone(
    note: str,
    item_code: str | None,
    *,
    chat_id: int | None,
    model_zone: str | None = None,
    model_confidence: float | None = None,
) -> ZoneResolution:
    """Зона записи: слова, словарь объектов, пункт, модель, затем спрос (T263, #838).

    Порядок источников — весь смысл задачи, и других нет:

    1. **Названа словами** — берётся слово аудитора всегда, включая форму без
       существительного («в холодном», «на кассе») и обиходные названия мест.
    2. **Задана словарём объектов** — объект найден в карте кадров, и его
       колонка «Зона» заполнена. Одна зона = жёстко, без вопроса: пицца-печь
       это горячий цех и никакой другой (слова владельца).
    3. **Пункт даёт ровно одну зону** — она и есть ответ (#838): спрашивать
       аудитора о том, что методика уже сказала, незачем.
    4. **Зона от модели** — только из зон пункта и только при уверенности не ниже
       `MODEL_ZONE_MIN_CONFIDENCE`. `UNKNOWN`, чужая зона и слабая уверенность
       отбрасываются: правило 6 запрещает гадать по виду кадра, а модель берёт
       зону из слов аудитора.
    5. **Не вывелось — спрашивается** кнопками, и кнопки только из зон,
       допустимых методикой для пункта.

    Зона из пунктов 3 и 4 аудитором не названа: она правится в мини-приложении
    как любая другая, а признак «зону назвал человек» остаётся за словами.

    Прошлая запись источником не является ни в одной ветке (T264): именно ею
    печь и уехала в холодный цех на живом прогоне владельца. Здесь её нет не по
    забывчивости — её здесь не должно быть.

    Расхождение названной зоны со словарём не разрешается молча: зона остаётся
    названной аудитором (его слово сильнее данных), а расхождение возвращается
    в `conflict`, чтобы спросить до фиксации.
    """
    options = allowed_zones(item_code, chat_id=chat_id)
    spoken = zone_from_words(note, chat_id=chat_id)
    known = dictionary_zone(note, chat_id=chat_id)
    if spoken is not None:
        conflict = (
            ZoneConflict(spoken=spoken, dictionary=known[0], phrase=known[1])
            if known is not None and known[0] != spoken
            else None
        )
        return ZoneResolution(zone=spoken, source=WORDS, options=options, conflict=conflict)
    if known is not None:
        return ZoneResolution(zone=known[0], source=DICTIONARY, options=options)
    if item_code is not None and len(options) == 1:
        return ZoneResolution(zone=options[0], source=ITEM, options=options)
    if (
        item_code is not None
        and model_zone in options
        and model_confidence is not None
        and model_confidence >= MODEL_ZONE_MIN_CONFIDENCE
    ):
        return ZoneResolution(zone=model_zone, source=MODEL, options=options)
    return ZoneResolution(zone=None, source=ASK, options=options)
