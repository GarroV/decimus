"""Накопитель непокрытых формулировок глазами управляющей компании (T270).

Бот копит в накопителе (`src/domain/uncovered.py`, T268) случаи, когда аудитор
что-то сказал, а записи из этого не вышло: пункта не нашлось, предложение было
не то, движок отказал, аудитор махнул рукой. Сам по себе накопитель — файл в
состоянии проверки; ценность у него ровно одна: по нему видно, какие слова
звучат на точке часто и до сих пор не покрыты картой кадров. Этот модуль и
есть тот взгляд — «слово → зона, встретилось N раз», как записано в контракте
блока `binding`.

**Ничего не пополняется, и это условие решения D077, а не осторожность.** По
карте кадров быстрый путь записывает находку БЕЗ подтверждения аудитора
(D064): слово, дописанное сюда автоматически, уехало бы в отчёт партнёру без
чьего-либо ведома. Поэтому здесь только счёт и порядок, а карта правится
отдельным вызовом, который делает человек.

**Готового вызова `add_photo_cue` здесь нет намеренно.** Довод тот же, по
которому его нет у предложений (`suggestions._code_note`): сказанное аудитором
— это предложение целиком, а строка карты — термин, и раздел, в который её
класть, из слов не выводится вовсе. Собранный за человека вызов подставил бы
и формулировку, и раздел, то есть решил бы за управляющую компанию ровно то,
что D077 оставляет ей.

**Формы одного слова склеиваются, формулировки — нет.** «Печь» и «печи» —
одно слово, и разнесённые по двум строкам они выглядят как два редких случая
вместо одного частого, то есть прячут тот самый сигнал, за которым сюда идут.
Склейка идёт тем же стеммером, которым ищет продукт (`recognize.cues.stems`),
— не своей копией правил: разошедшись, две копии дали бы управляющей компании
слово, по которому быстрый путь всё равно не сработает. А вот ФРАЗЫ рядом со
словом стоят дословно и похожие не склеиваются — то же правило, что у
`suggestions._Bucket.words`: по фразам правят карту, и склейка «почти
одинаковых» показала бы человеку формулировку, которой никто не произносил.

Модуль не только считает, но и читает: `read_all` переводит отказ домена в
отказ инструмента. Отказ при этом теряет путь на диске (T120) — путь уходит в
лог процесса, он остаётся на машине, — но не теряется сам: молчаливая пустота
здесь означала бы потерянный сигнал, а накопитель существует ровно затем,
чтобы сигнал не терялся.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import DomainError
from ..domain.uncovered import OUTCOMES, ZONE_SOURCES, UncoveredEntry, read_uncovered
from ..recognize.cues import stems, words_and_gaps
from .errors import ToolError

logger = logging.getLogger(__name__)

#: Сколько слов-кандидатов отдаём по умолчанию. Выдачу читает человек, а не
#: машина: хвост из слов, встретившихся однажды, он всё равно не разберёт, а
#: `truncated` скажет, что хвост есть.
DEFAULT_CANDIDATES = 50

#: Сколько РАЗНЫХ формулировок называем у одного слова. За частым словом стоят
#: десятки фраз, и вывалить их все значило бы утопить ответ ради хвоста.
#: Обрезка называется числом тут же (`other_phrases`), а не общим `truncated`:
#: тот говорит про необрезанный список СЛОВ, и подмена одного другим сказала
#: бы неправду.
PHRASES_PER_CANDIDATE = 10

#: Приписка, которой кончается любой ответ этого инструмента, — в каждом
#: исходе, включая пустой. Агент пересказывает человеку статус, и «собрано N
#: кандидатов» без неё читается как «N слов добавлено в карту».
NOT_APPLIED = (
    "Nothing was changed: the word map is never topped up automatically (decision D077) — "
    "the fast path records a finding by that map without the auditor confirming it, so a word "
    "added here on its own would reach a partner's report with nobody having seen it."
)

#: Чего в накопителе нет и почему выдача уже поэтому неполна. Оговорки уходят
#: в ответ списком, а не остаются в этом файле: читающий обязан узнать границы
#: выборки из самой выборки.
CAVEATS = (
    "The accumulator only holds cases where no record came out of what the auditor said. A "
    "formulation the system handled correctly never reaches it, so these counts are not the "
    "frequency of a word on site — they are the frequency of it going nowhere.",
    "It lives in the inspection state on the bot's machine, not in the inspections database: "
    "the database may be down on site and the signal must not be lost with it. An inspection "
    "whose state has been wiped carries no accumulator either.",
    "Word forms are folded together by the same stemmer the product searches with, and the "
    "word is shown as that stemmer sees it: lowercase, with 'ё' written 'е'. What was actually "
    "said stands verbatim beside it, in 'heard'.",
    "A cue row is written for a methodology edition, so candidates collected across two "
    "editions are corrected by different rows; the editions in the sample are named in "
    "'considered'.",
)

#: Как назвать в выдаче отсутствие источника зоны. Пустая строка легальна в
#: записи накопителя («зона не вывелась никак»), но ключом словаря она читается
#: как источник с пустым именем.
NO_ZONE_SOURCE = "none"


def _check_limit(value: int) -> int:
    """Предел выдачи. Негодный — отказ, а не молчаливая подстановка умолчания.

    Подставленное умолчание отдало бы выдачу, которой не просили, и спросивший
    прочитал бы её как ответ на свой вопрос.
    """
    if value < 1:
        raise ToolError(
            f"limit={value}: предел выдачи — целое число не меньше 1. "
            f"Без предела вовсе спрашивать не надо: умолчание {DEFAULT_CANDIDATES}"
        )
    return value


def _counted(
    counter: dict[str, int], *, key_name: str, empty_last: bool = False
) -> list[dict[str, Any]]:
    """Счётчик в список «значение → сколько раз», частое впереди.

    Порядок задан до конца намеренно: выдача, зависящая от порядка записей в
    файле, менялась бы между двумя одинаковыми вопросами, и человек прочитал
    бы это как изменение в данных. `empty_last` держит «значения не было» в
    хвосте при равном счёте: это не одно из значений, а их отсутствие.
    """
    порядок = sorted(
        counter.items(),
        key=lambda пара: (-пара[1], (empty_last and пара[0] == ""), пара[0]),
    )
    return [
        {key_name: (None if empty_last and значение == "" else значение), "count": счёт}
        for значение, счёт in порядок
    ]


@dataclass
class _Bucket:
    """Копилка одного слова: во скольких случаях оно встретилось и в каких."""

    #: Число СЛУЧАЕВ, а не произнесений: слово, дважды сказанное в одной фразе,
    #: — это одно дело, а не два. Иначе наверх поднялась бы многословная
    #: формулировка вместо частой.
    count: int = 0
    #: Формы слова, как их видит разборщик продукта, → в скольких случаях.
    forms: dict[str, int] = field(default_factory=dict)
    #: Зона случая → сколько раз. Пустая строка — зона не вывелась.
    zones: dict[str, int] = field(default_factory=dict)
    #: Исход случая → сколько раз.
    outcomes: dict[str, int] = field(default_factory=dict)
    #: Пункт, выбранный аудитором в итоге, → сколько раз. Пустых здесь нет:
    #: «не выбрал» — это отсутствие пункта, а не пункт с пустым кодом.
    codes: dict[str, int] = field(default_factory=dict)
    #: Формулировка целиком → сколько раз. Ключ дословный.
    phrases: dict[str, int] = field(default_factory=dict)

    def add(self, entry: UncoveredEntry, forms: Sequence[str]) -> None:
        self.count += 1
        for форма in forms:
            self.forms[форма] = self.forms.get(форма, 0) + 1
        self.zones[entry.zone] = self.zones.get(entry.zone, 0) + 1
        self.outcomes[entry.outcome] = self.outcomes.get(entry.outcome, 0) + 1
        if entry.chosen_code:
            self.codes[entry.chosen_code] = self.codes.get(entry.chosen_code, 0) + 1
        self.phrases[entry.note] = self.phrases.get(entry.note, 0) + 1

    def word(self) -> str:
        """Как назвать слово человеку: самая частая его форма, при равенстве — первая по алфавиту.

        Основа человеку не показывается: это внутренний ключ склейки, а не
        слово языка — показанная, она выглядит опечаткой и в карту кадров в
        таком виде не попадёт.
        """
        return sorted(self.forms.items(), key=lambda пара: (-пара[1], пара[0]))[0][0]

    def heard(self) -> dict[str, Any]:
        """Что за этим словом говорили — дословно, с числом повторов.

        По слову управляющая компания понимает, ЧТО дописывать, по фразе — что
        именно было сказано; одно не заменяет другое (тот же довод, что у T194
        в предложениях).
        """
        порядок = sorted(self.phrases.items(), key=lambda пара: (-пара[1], пара[0]))
        названные = порядок[:PHRASES_PER_CANDIDATE]
        return {
            "phrases": [{"phrase": фраза, "count": счёт} for фраза, счёт in названные],
            "other_phrases": len(порядок) - len(названные),
        }


def _outcomes(counter: dict[str, int]) -> dict[str, int]:
    """Исходы всеми известными ключами, даже нулевыми, плюс незнакомые, если встретились.

    Ноль — это сведение, а не пустое место: «ни одного отказа движка» и «про
    отказы движка здесь ничего не сказано» читаются по-разному. Незнакомый
    исход не выбрасывается: запись накопителя мог поправить руками человек, и
    молча проглоченный исход исчез бы из счёта, не исчезнув из файла.
    """
    итог = {имя: counter.get(имя, 0) for имя in OUTCOMES}
    for имя, счёт in sorted(counter.items()):
        if имя not in итог:
            итог[имя] = счёт
    return итог


def _significant(note: str) -> dict[str, list[str]]:
    """Слова формулировки, годные в кандидаты: основа → её формы в этой фразе.

    Основа берётся тем же `stems`, которым ищет продукт, и по одному слову:
    так у каждой основы остаётся форма, которую произнесли. Предлоги, союзы и
    слишком короткие слова отсеиваются там же — попав в выдачу, они заняли бы
    её верх целиком, потому что встречаются в каждой второй формулировке.
    """
    найденное: dict[str, list[str]] = {}
    for слово in words_and_gaps(note)[0]:
        основы = stems(слово)
        if len(основы) != 1:
            continue
        формы = найденное.setdefault(next(iter(основы)), [])
        if слово not in формы:
            формы.append(слово)
    return найденное


def _status(*, cases: int, candidates: int, truncated: bool) -> str:
    if cases == 0:
        return (
            "The accumulator holds no formulations at all: nothing the auditors said has gone "
            f"without a record since the inspections were last archived. {NOT_APPLIED}"
        )
    хвост = " More words were left out of this answer; see 'truncated'." if truncated else ""
    return (
        f"{cases} formulations produced no record; {candidates} candidate words come out of "
        f"them.{хвост} {NOT_APPLIED}"
    )


def build(entries: Sequence[UncoveredEntry], *, limit: int = DEFAULT_CANDIDATES) -> dict[str, Any]:
    """Накопитель → список кандидатов «слово → зона, встретилось N раз». Ничего не пишет."""
    предел = _check_limit(limit)

    копилки: dict[str, _Bucket] = {}
    без_слов: dict[str, int] = {}
    исходы: dict[str, int] = {}
    источники: dict[str, int] = {имя or NO_ZONE_SOURCE: 0 for имя in ZONE_SOURCES}
    издания: set[str] = set()
    с_зоной = без_издания = 0

    for запись in entries:
        значимые = _significant(запись.note)
        if значимые:
            for основа, формы in значимые.items():
                копилки.setdefault(основа, _Bucket()).add(запись, формы)
        else:
            без_слов[запись.note] = без_слов.get(запись.note, 0) + 1
        исходы[запись.outcome] = исходы.get(запись.outcome, 0) + 1
        ключ = запись.zone_source or NO_ZONE_SOURCE
        источники[ключ] = источники.get(ключ, 0) + 1
        if запись.zone:
            с_зоной += 1
        if запись.checklist_version:
            издания.add(запись.checklist_version)
        else:
            без_издания += 1

    порядок = sorted(копилки.values(), key=lambda копилка: (-копилка.count, копилка.word()))
    названные = порядок[:предел]

    return {
        "considered": {
            "cases": len(entries),
            # Формулировка, из которой не вышло ни одного кандидата, названа
            # числом и показана дословно ниже: потеряться молча она не имеет
            # права — накопитель заводили ровно затем, чтобы сигнал не пропадал.
            "without_candidate_words": sum(без_слов.values()),
            "outcomes": _outcomes(исходы),
            "zone_sources": источники,
            "with_zone": с_зоной,
            "without_zone": len(entries) - с_зоной,
            "checklist_versions": sorted(издания),
            "without_version": без_издания,
        },
        "candidates": [
            {
                "word": копилка.word(),
                "count": копилка.count,
                "forms": _counted(копилка.forms, key_name="form"),
                "zones": _counted(копилка.zones, key_name="zone", empty_last=True),
                "outcomes": _outcomes(копилка.outcomes),
                "chosen_codes": _counted(копилка.codes, key_name="code"),
                "heard": копилка.heard(),
            }
            for копилка in названные
        ],
        "unclassified_phrases": _counted(без_слов, key_name="phrase"),
        "applied": False,
        "truncated": len(порядок) > len(названные),
        "caveats": list(CAVEATS),
        "status": _status(
            cases=len(entries),
            candidates=len(названные),
            truncated=len(порядок) > len(названные),
        ),
    }


def read_all(*, limit: int = DEFAULT_CANDIDATES) -> dict[str, Any]:
    """Прочитать накопители всех проверок и собрать выдачу.

    Спрашивают по сети, а не по чату: чат — внутреннее имя разговора в
    мессенджере, называть его в вопросе некому, а перебрать чужие по номеру
    незачем.

    Отказ домена переводится в отказ инструмента БЕЗ пути на диске: по пути
    видно устройство каталогов деплоя и имя пользователя, под которым поднят
    сервер (T120). Сам путь и причина уходят в лог процесса — он остаётся на
    машине.
    """
    предел = _check_limit(limit)
    try:
        записи = read_uncovered()
    except DomainError as отказ:
        logger.warning("накопитель непокрытых формулировок не прочитан: %s", отказ)
        raise ToolError(
            "Накопитель непокрытых формулировок не прочитан: он испорчен либо каталог "
            "состояния недоступен. Каталог задан переменной окружения STATE_DIR; путь и "
            "причина — в логе сервера. Пустой выдачи вместо этого не будет: она означала бы "
            "«сигнала не приходило», а сигнал мог прийти и пропасть"
        ) from отказ
    return build(записи, limit=предел)
