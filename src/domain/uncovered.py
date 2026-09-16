"""Накопитель непокрытых формулировок — случай, когда записи не появилось.

Задача T268. Сегодня нигде не копится ровно это: аудитор что-то сказал,
система не нашла пункт (или предложила не то), аудитор махнул рукой — и
формулировка исчезает бесследно. Существующее хранение предложений
(`state.SUGGESTIONS_KEY`, решение D077, задача T164) привязано к УЖЕ
СДЕЛАННОЙ записи и потому молчит именно там, где сигнал нужнее всего: там,
где записи не случилось вовсе. Накопитель копит ровно эти случаи, чтобы
управляющая компания потом дописала карту слов (`photo-cues.md`) по частоте,
а не по догадке.

Модуль лежит в `src/domain`, а не в `src/bot` (откуда его пишет бот) и не в
`src/mcp` (откуда его будет читать MCP-сервер отдельной задачей): контракт
слоёв `import-linter` объявляет `src.bot` и `src.mcp` пирами, и им нельзя
импортировать друг друга. Общий дом обязан лежать НИЖЕ обоих — ровно там же,
где лежит `edition.py`, снимающий снимок методики по той же причине (прочитан
как образец той же формы задачи).

Пишется в `STATE_DIR`, рядом с заметками бота (`src/bot/sidecar.py`,
`bot.json`) и состоянием проверки (`inspection.json`): база площадки может
быть не поднята, и терять сигнал из-за этого нельзя (то же рассуждение, что у
`sidecar` про `bot.json`). При завершении проверки накопитель точки не
обнуляется, а переносится в свою историю — `archive_uncovered` вызывает
слой `bot`, симметрично тому, как он же сбрасывает заметки (`sidecar.reset`).

Формат хранения и блокировка сознательно скопированы с `sidecar.py`
(`_write`/`_lock`/`_change`) — тот же приём для той же беды: любое изменение
здесь тоже тройка «прочитать, дополнить, положить обратно», и два писателя
внахлёст без блокировки теряют дополнение молча. Именно на этом `sidecar`
терял кадры в замере (36 из 60) — этот модуль ту же ошибку не повторяет.

Испорченный или нечитаемый файл — отказ (`ValidationError`), а не молчаливый
пустой накопитель: молчаливая пустота здесь означает потерянный сигнал, а
накопитель существует ровно затем, чтобы сигнал не терялся. Отсутствие файла
вовсе — законное «ещё ничего не копилось», а не то же самое: тест это
различает намеренно (см. `tests/test_domain_uncovered.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import check_environment
from .engine import CHAT_DIR_PREFIX, chat_dir
from .errors import ValidationError
from .state import state_lock

#: Файл накопителя в папке проверки — рядом с `inspection.json` и `bot.json`.
FILE_NAME = "uncovered.json"

#: Форма файла на диске. Меняется тогда же, когда меняется состав полей записи.
SCHEMA = 1

#: Исходы записи в накопителе. Как ровно кончилось дело у этой формулировки:
#: «записано» (аудитор всё же зафиксировал нарушение), «брошено» (аудитор не
#: стал разбирать — не нашлось пункта, не оказалось времени) или «отказ»
#: (движок отверг пару «пункт + зона»). Разбор карты слов без этого различия
#: не может отличить «формулировка ничему не соответствует» от «соответствует,
#: но аудитор поленился».
OUTCOME_RECORDED = "recorded"
OUTCOME_ABANDONED = "abandoned"
OUTCOME_REFUSED = "refused"
OUTCOMES = (OUTCOME_RECORDED, OUTCOME_ABANDONED, OUTCOME_REFUSED)

#: Источники зоны записи — тот же порядок шагов, что в разделе «Источники
#: зоны» блока (`docs/furca/blocks/binding.md`): слова аудитора, словарь
#: объектов, кнопки. Пустая строка — легальное четвёртое значение: зона не
#: вывелась никак (в отличие от исхода, где легального «никак» нет).
ZONE_SOURCE_WORDS = "words"
ZONE_SOURCE_DICTIONARY = "dictionary"
ZONE_SOURCE_BUTTONS = "buttons"
ZONE_SOURCES = (ZONE_SOURCE_WORDS, ZONE_SOURCE_DICTIONARY, ZONE_SOURCE_BUTTONS, "")


@dataclass(frozen=True)
class UncoveredEntry:
    """Один случай, когда формулировка аудитора не стала (или стала не так) записью.

    Состав — таблица блока `binding`, раздел «Накопитель непокрытых
    формулировок». Почти все поля легально пусты — это «ничего не было»,
    а не ошибка: система могла ничего не предложить, аудитор мог ничего не
    выбрать, зона могла не вывестись. Легально пусто ровно то, для чего в
    таблице блока написано «пусто — …»; `note` и `outcome` в их числе не
    названы, и потому единственные, что `record_uncovered` проверяет.

    `outcome` по умолчанию — пустая строка, и это НЕ означает «записано»:
    легального «никак не кончилось» у исхода нет, поэтому пустая строка здесь
    так же не проходит `record_uncovered`, как и любое другое неизвестное
    значение. Молчаливый исход по умолчанию замаскировал бы забытый параметр
    вызова под настоящий отчёт о деле.
    """

    #: Формулировка аудитора — то, что предстоит покрыть словарём. Единственное
    #: поле, которому легального «пусто» не бывает: копится ради него.
    note: str
    #: Что предложила система: пункт. Пусто — «ничего не предложила».
    suggested_code: str = ""
    #: Класс предложения. Пусто — предложения не было.
    suggested_level: str = ""
    #: Зона предложения. Пусто — предложения не было.
    suggested_zone: str = ""
    #: Уверенность предложения, доля от 0 до 1. `0.0` — предложения не было.
    confidence: float = 0.0
    #: Что выбрал аудитор в итоге. Пусто — не выбрал. Расхождение с
    #: предложенным и есть сигнал, который управляющая компания разбирает.
    chosen_code: str = ""
    #: Класс выбранного. Пусто — не выбрал.
    chosen_level: str = ""
    #: Зона записи. Пусто — не вывелась.
    zone: str = ""
    #: Как получена зона: одно из `ZONE_SOURCES`.
    zone_source: str = ""
    #: Чем кончилось дело: одно из `OUTCOMES`. Легального «пусто» нет.
    outcome: str = ""
    #: Версия методики, по которой шла проверка — без неё разбор через месяц
    #: невозможен: карта слов правится под конкретное издание чек-листа.
    checklist_version: str = ""
    #: Время в ISO-8601, UTC (`datetime.now(timezone.utc).isoformat()`).
    at: str = ""


def _uncovered_path(chat_id: int) -> Path:
    """Файл накопителя этого чата: та же папка проверки, что и у `bot.json`."""
    return chat_dir(chat_id, check_environment()) / FILE_NAME


def _decode(path: Path) -> dict[str, Any]:
    """Прочитать файл целиком. Нечитаемое или не-объект — отказ, а не пустое.

    Тот же довод, что у `sidecar._decode`: молчаливое «начнём с пустого места»
    потеряло бы всё, что в накопителе уже лежало, и узнал бы об этом только
    тот, кто месяц спустя не досчитался записей в разборе.
    """
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Накопитель непокрытых формулировок испорчен и не читается: {path} ({exc})"
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError(f"Накопитель {path} не похож на накопитель — не объект")
    return data


def _entry_from_raw(raw: Any, path: Path) -> UncoveredEntry:
    """Одна запись из файла. Форма, по которой нельзя восстановить запись, — отказ."""
    if not isinstance(raw, dict):
        raise ValidationError(f"Запись накопителя в {path} не похожа на запись: {raw!r}")
    try:
        return UncoveredEntry(
            note=str(raw["note"]),
            suggested_code=str(raw.get("suggested_code") or ""),
            suggested_level=str(raw.get("suggested_level") or ""),
            suggested_zone=str(raw.get("suggested_zone") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            chosen_code=str(raw.get("chosen_code") or ""),
            chosen_level=str(raw.get("chosen_level") or ""),
            zone=str(raw.get("zone") or ""),
            zone_source=str(raw.get("zone_source") or ""),
            outcome=str(raw.get("outcome") or ""),
            checklist_version=str(raw.get("checklist_version") or ""),
            at=str(raw.get("at") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"Запись накопителя в {path} испорчена: {exc}") from exc


def _entry_to_raw(entry: UncoveredEntry) -> dict[str, Any]:
    """Запись в форму для JSON. Обратная сторона `_entry_from_raw`, поле в поле."""
    return {
        "note": entry.note,
        "suggested_code": entry.suggested_code,
        "suggested_level": entry.suggested_level,
        "suggested_zone": entry.suggested_zone,
        "confidence": entry.confidence,
        "chosen_code": entry.chosen_code,
        "chosen_level": entry.chosen_level,
        "zone": entry.zone,
        "zone_source": entry.zone_source,
        "outcome": entry.outcome,
        "checklist_version": entry.checklist_version,
        "at": entry.at,
    }


def _load_raw(path: Path) -> tuple[list[Any], list[Any]]:
    """`open` и `history` этого файла как есть, без разбора в `UncoveredEntry`.

    Отдельно от чтения наружу (`_read_one`): здесь достаточно знать, что файл
    вообще читается и похож на накопитель, — записи внутри `record_uncovered`
    и `archive_uncovered` не разбирает и не трогает, только дописывает и
    переносит целиком. Файла нет — пустые списки: это «ещё ничего не копилось»,
    а не порча.
    """
    if not path.is_file():
        return [], []
    raw = _decode(path)
    return list(raw.get("open") or []), list(raw.get("history") or [])


def _write_file(path: Path, *, open_entries: list[Any], history: list[Any]) -> None:
    """Временный файл рядом, `os.replace` — тот же приём, что у `sidecar._write`.

    Обрезанный файл на полдороге читатель не увидит никогда: `os.replace`
    атомарен на одной файловой системе, а временный файл лежит в той же папке.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SCHEMA, "open": open_entries, "history": history}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".uncovered-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_one(path: Path) -> tuple[UncoveredEntry, ...]:
    """Записи одного файла в порядке прихода: сперва `history`, затем `open`."""
    if not path.is_file():
        return ()
    raw = _decode(path)
    history = [_entry_from_raw(item, path) for item in raw.get("history") or []]
    open_entries = [_entry_from_raw(item, path) for item in raw.get("open") or []]
    return tuple(history + open_entries)


def record_uncovered(chat_id: int, entry: UncoveredEntry) -> None:
    """Дописать случай в конец `open` этого чата.

    Идемпотентности нет намеренно: две одинаковые формулировки — это дело,
    встретившееся дважды, и счёт повторов управляющей компании нужен не
    меньше самих формулировок.

    Проверяются ровно три вещи, названные в контракте, — и только они:
    неизвестный исход, неизвестный источник зоны и пустая формулировка.
    Остальные поля легально пусты (см. `UncoveredEntry`), и отказывать на их
    пустоте значило бы отказывать на нормальном «система ничего не
    предложила».
    """
    if not entry.note:
        raise ValidationError(
            "Формулировка аудитора пуста — копить нечего: накопитель существует ровно ради неё"
        )
    if entry.outcome not in OUTCOMES:
        raise ValidationError(f"Исход «{entry.outcome}» не из {OUTCOMES}")
    if entry.zone_source not in ZONE_SOURCES:
        raise ValidationError(f"Источник зоны «{entry.zone_source}» не из {ZONE_SOURCES}")
    path = _uncovered_path(chat_id)
    with state_lock(path):
        open_entries, history = _load_raw(path)
        open_entries.append(_entry_to_raw(entry))
        _write_file(path, open_entries=open_entries, history=history)


def read_uncovered(*, chat_id: int | None = None) -> tuple[UncoveredEntry, ...]:
    """Записи в порядке прихода: сперва `history`, затем `open`.

    `chat_id` назван — только этот чат. `chat_id=None` — все чаты разом:
    перебираются папки проверок в `STATE_DIR` (тот же префикс, что и у
    `chat_dir`, — не переписан здесь строкой, чтобы два места не разошлись),
    порядок между чатами берётся по имени папки, а не по числу: имя
    сортируется всегда одинаково, а порядок обхода файловой системы — нет.

    Папка без `uncovered.json` пропускается молча — так же законно, как и
    полное отсутствие `STATE_DIR`: до первой записи это нормальное состояние
    любого чата.
    """
    settings = check_environment()
    if chat_id is not None:
        return _read_one(chat_dir(chat_id, settings) / FILE_NAME)
    if not settings.state_dir.is_dir():
        return ()
    chat_folders = sorted(
        p.name
        for p in settings.state_dir.iterdir()
        if p.is_dir() and p.name.startswith(CHAT_DIR_PREFIX)
    )
    entries: list[UncoveredEntry] = []
    for name in chat_folders:
        entries.extend(_read_one(settings.state_dir / name / FILE_NAME))
    return tuple(entries)


def archive_uncovered(chat_id: int) -> int:
    """Перенести все записи `open` этого чата в конец `history`. Вернуть, сколько перенесено.

    Идемпотентна: второй вызов находит пустой `open` и не пишет вообще ничего
    — ни лишней версии файла, ни изменения `mtime`, — а не переносит "ноль
    записей" переписыванием файла заново. Накопителя ещё не было (проверка
    прошла вовсе без непокрытых случаев) — тоже ноль, а не отказ: это такое же
    законное «нечего переносить», как и второй вызов.
    """
    path = _uncovered_path(chat_id)
    with state_lock(path):
        open_entries, history = _load_raw(path)
        if not open_entries:
            return 0
        _write_file(path, open_entries=[], history=history + open_entries)
        return len(open_entries)
