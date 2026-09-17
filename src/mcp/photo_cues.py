"""Карта слов: правка через агента, версиями (T144, issue #115).

`photo-cues.md` — документ управляющей компании, лежащий рядом с методикой. По
нему быстрый путь (T113) решает, что записать в проверку **без подтверждения
аудитора**, то есть правка карты меняет то, что уезжает партнёру. До этой
задачи править её было нечем: у чек-листа есть и инструмент, и версии, а у
карты не было ни того, ни другого, и откат делался копией файла вне git.

Три вещи, из которых здесь всё следует.

**Хранилище то же самое.** Карта входит в отпечаток версии методики
(`DATA_FILES`, с 04.09.2026), поэтому её правка уже даёт новую версию — не
хватало только инструмента. Ход правки общий с чек-листом (`checklist.apply_edit`):
снимок версии → правка копии → проверка → новая версия рядом. Публикация
остаётся отдельным действием (D049), а значит откат — это перестановка
указателя, а не поиск копии файла.

**Правит карту этот блок, а не движок, и это не исключение из правила.**
Правило звучало «правила живут в движке, повторять их здесь нельзя» — и оно
про `checklist.csv` и `zones.csv`, чьи правила держит `engine/manage.py`.
Карту движок не читает вовсе: её читает `src.recognize.cues`, и команды для
неё у движка нет. Повторять здесь нечего.

**Проверяет правку тот, кто карту читает.** После правки кандидат разбирается
`src.recognize.cues.load_cues` — тем же кодом, который работает в продукте, — и
результат сверяется с задуманным. Свой разборщик формата означал бы, что блок
согласен сам с собой, а продукт видит другое.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ..recognize.config import NO_CHAT
from ..recognize.cues import CUES_FILE, THRESHOLDS_HEADINGS, ZONE_HEADINGS, load_cues
from .checklist import Outcome, Store, _ensure, _version_dir, apply_edit
from .errors import ChecklistError

#: Код пункта в ячейке — та же форма, по которой их находит разборщик продукта.
_CODE = re.compile(r"\b[A-Z]{3}\d{2}\b")

#: Знаки, из которых состоит строка-разделитель таблицы Markdown.
_RULE_CHARS = set("-: ")

#: Разделитель ячеек. Он же — то, чего не может быть внутри фразы: строка с
#: лишней чертой разъезжается на колонки, и разборщик читает её не так, как
#: задумывал человек.
_PIPE = "|"

#: Чем пишется «кода в этой колонке нет». Прочерк стоит в карте у объектов, о
#: которых спрашивают не всё: у стеллажа есть вопрос про грязь и нет про
#: поломку. Разборщик продукта такую ячейку просто пропускает.
_DASH = "—"

#: Ячейка, которая означает «кода нет», а не формулировку не на месте.
_BLANK = frozenset({"", "-", "–", "—", "--"})


@dataclass(frozen=True)
class _Row:
    """Строка файла карты, разобранная настолько, насколько нужно для правки.

    `header` — шапка ТОЙ таблицы, в которой лежит строка, а не первая шапка
    раздела: под одним заголовком раздела боевой карты стоят семнадцать
    таблиц, и колонки строка обязана узнавать у своей.
    """

    index: int
    section: str
    header: tuple[str, ...]
    cells: tuple[str, ...]
    codes: tuple[str, ...]


@dataclass(frozen=True)
class _Head:
    """Шапка таблицы раздела: её колонки и СТРОКА ФАЙЛА, где она стоит (T291).

    Номер строки нужен ровно одному случаю — разделу, у которого шапка есть, а
    строк ещё нет: новой строке не за что зацепиться, и опереться она обязана
    на свою шапку, а не на первую строку файла.
    """

    cells: tuple[str, ...]
    index: int


def _cells(line: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in line.strip().strip(_PIPE).split(_PIPE))


def _is_rule(cells: tuple[str, ...]) -> bool:
    return all(set(c) <= _RULE_CHARS for c in cells)


def _scan(text: str) -> tuple[list[_Row], dict[str, _Head]]:
    """Строки-подсказки файла и заголовок таблицы каждого раздела.

    Правила отбора — те же, что у разборщика продукта: раздел порогов классов
    пропускается целиком (там коды стоят в первой ячейке и подсказками не
    являются), заголовком таблицы считается строка без кодов — и заголовок
    этот запоминается КАЖДОЙ следующей строке, как его запоминает продукт.
    Словарь разделов остаётся прежним (первая шапка раздела): по нему
    заводится новая строка и отвечает чтение.
    """
    rows: list[_Row] = []
    headers: dict[str, _Head] = {}
    section = ""
    header: tuple[str, ...] = ()
    in_thresholds = False
    for index, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            section = line[3:].strip()
            in_thresholds = line.strip().startswith(THRESHOLDS_HEADINGS)
            header = ()
            continue
        if in_thresholds or not line.lstrip().startswith(_PIPE):
            continue
        cells = _cells(line)
        if len(cells) < 2 or _is_rule(cells):
            continue
        codes = tuple(dict.fromkeys(_CODE.findall(" ".join(cells[1:]))))
        if not codes:
            header = cells
            headers.setdefault(section, _Head(cells=cells, index=index))
            continue
        rows.append(_Row(index=index, section=section, header=header, cells=cells, codes=codes))
    return rows, headers


def _after_head(строки: list[str], head: _Head) -> int:
    """Первая строка ПУСТОЙ таблицы встаёт сразу за её шапкой (T291).

    Разделитель шапки (`|---|---|`) пропускается: строка, вставленная между
    шапкой и разделителем, перестаёт быть строкой таблицы — и продукт её не
    увидит вовсе, а правка при этом вернула бы успех. Разделитель не
    обязателен (карта — свободный Markdown), поэтому он именно пропускается,
    если стоит, а не требуется.
    """
    куда = head.index + 1
    if куда < len(строки):
        следующая = строки[куда]
        if следующая.lstrip().startswith(_PIPE) and _is_rule(_cells(следующая)):
            куда += 1
    return куда


def _zone_at(header: tuple[str, ...]) -> int | None:
    """Где в таблице стоит колонка «Зона» — по ЗАГОЛОВКУ, а не по номеру (T262).

    Считать колонки числом нельзя в принципе: колонка, добавленная управляющей
    компанией, сдвигает все номера разом. Заголовок колонки зоны продукт знает
    на всех языках правил (`zone_column` в `language_rules.json`), и знает его
    тот же код, который читает карту в проверке.
    """
    for место, название in enumerate(header):
        if место and название.strip().lower() in ZONE_HEADINGS:
            return место
    return None


def _named(header: tuple[str, ...]) -> tuple[int, ...]:
    """Колонки, которые называет вызывающий: все, кроме фразы и кроме зоны.

    Зона не называется, потому что кодов она не несёт и ставит её управляющая
    компания в самой карте: правка кодов обязана вернуть зону на место, а не
    потребовать её заново — иначе она молча снимала бы зону объекта.
    """
    зона = _zone_at(header)
    return tuple(место for место in range(1, len(header)) if место != зона)


def _shape(row: _Row) -> tuple[str, ...]:
    """Форма строки: её шапка, а если строка шире или уже шапки — она сама.

    Второй случай означает разъехавшуюся карту. Тогда правка ведёт себя как до
    T289 — названы все ячейки, — но молчаливой формулировки в кодовой колонке
    не пропускает: у формы без шапки кодовыми считаются все колонки.
    """
    return row.header if len(row.header) == len(row.cells) else row.cells


def _zone_value(row: _Row) -> str:
    место = _zone_at(_shape(row))
    return row.cells[место].strip() if место is not None and место < len(row.cells) else ""


def editable_cells(row: _Row) -> tuple[str, ...]:
    """Ячейки строки, которые называет правка: без фразы и без колонки зоны.

    Публично, потому что этим же разбором сборка предложений (T165) собирает
    вызов правки, а чтение карты отвечает агенту. Свой разбор в каждом из трёх
    мест означал бы предложение, которое `edit_photo_cue` отклонит по ширине.
    """
    форма = _shape(row)
    return tuple(row.cells[место] if место < len(row.cells) else "" for место in _named(форма))


def _code_bearing(rows: list[_Row], header: tuple[str, ...]) -> frozenset[int]:
    """Колонки, несущие коды у строк таблицы такой же формы.

    Кодовые колонки от колонок управляющей компании («Откуда» — кем строка
    заведена) отличаются наблюдаемым: у кодовой колонки коды в таблице ЕСТЬ.
    Списком заголовков это не решается — заголовки своих колонок УК не
    согласовывает ни с кем, и список пришлось бы вести здесь за неё.

    Строк такой формы нет вовсе — кодовыми считаются все колонки: строгость
    здесь дешевле молча принятой формулировки на месте кода.
    """
    свои = [row for row in rows if row.header == header]
    if not свои:
        return frozenset(_named(header))
    return frozenset(
        место
        for место in _named(header)
        for row in свои
        if место < len(row.cells) and cell_codes(row.cells[место])
    )


def _compose(
    header: tuple[str, ...],
    cells: tuple[str, ...],
    phrase: str,
    *,
    previous: _Row | None,
) -> tuple[str, ...]:
    """Строка целиком: фраза, названные ячейки по своим колонкам и зона.

    Зона берётся у прежней строки (правка) либо остаётся пустой (новая
    строка): пустая зона — законное значение и означает «спросить», а не
    беду данных. Ячейка под неё обязана быть в любом случае — строка другой
    ширины разъезжается по колонкам.
    """
    названные = dict(zip(_named(header), cells, strict=True))
    получилось = [phrase]
    for место in range(1, len(header)):
        if место in названные:
            получилось.append(названные[место])
        elif previous is not None and место < len(previous.cells):
            получилось.append(previous.cells[место])
        else:
            получилось.append("")
    return tuple(получилось)


def _known_codes(data_dir: Path) -> set[str]:
    """Коды пунктов методики этой версии — по её же `checklist.csv`."""
    with (data_dir / "checklist.csv").open(encoding="utf-8-sig", newline="") as f:
        return {(row.get("id") or "").strip().upper() for row in csv.DictReader(f)} - {""}


def _known_zones(data_dir: Path) -> tuple[str, ...]:
    """Коды зон этой версии — по её же `zones.csv`, в написании справочника.

    Написание важно: бот сверяет зону строки со справочником издания кодом в
    код (`src/bot/zones.py`) и чужое написание отбрасывает записью в лог — то
    есть молча для аудитора. Поэтому в карту уезжает код справочника, а не то,
    как его набрали в вызове.
    """
    with (data_dir / "zones.csv").open(encoding="utf-8-sig", newline="") as f:
        коды = [(row.get("code") or "").strip() for row in csv.DictReader(f)]
    return tuple(dict.fromkeys(code for code in коды if code))


def cell_codes(cell: str) -> tuple[str, ...]:
    """Коды пунктов ОДНОЙ ячейки таблицы, в порядке появления.

    Публично, потому что этим же разбором сборка предложений (T165) собирает
    вызов правки: ячеек в вызове ровно столько, сколько колонок в разделе, и
    свой разбор ячейки означал бы предложение, которое `edit_photo_cue`
    отклонит как строку не той ширины.
    """
    return tuple(dict.fromkeys(_CODE.findall(cell.upper())))


def _check_phrase(phrase: str) -> str:
    value = (phrase or "").strip()
    if not value:
        raise ChecklistError(
            "Не названа фраза подсказки. Пустая фраза срабатывала бы на любой комментарий "
            "или ни на одном — и то и другое молча"
        )
    if _PIPE in value or "\n" in value:
        raise ChecklistError(
            f"Во фразе «{phrase}» есть знак «{_PIPE}» или перевод строки. Такая строка "
            f"разъезжается на лишние колонки, и разборщик читает её не так, как задумано"
        )
    if _CODE.search(value):
        raise ChecklistError(
            f"Во фразе «{phrase}» стоит код пункта. Код в первой ячейке означает раздел "
            f"порогов классов, а не подсказку: такую строку разборщик продукта пропустит"
        )
    return value


def _check_codes(
    codes: list[str],
    *,
    known: set[str],
    header: tuple[str, ...],
    bearing: frozenset[int],
) -> tuple[str, ...]:
    """Ячейки строки по колонкам — или отказ, называющий, что именно не так.

    Ячеек называется столько, сколько в таблице колонок кроме фразы и кроме
    зоны, и узнаются они по ЗАГОЛОВКУ. Числом колонки считать нельзя: карта
    управляющей компании держит рядом свои колонки, и каждая новая ломала бы
    правку заново — ровно это и случилось с колонкой «Зона» (T289).
    """
    места = _named(header)
    if not codes:
        raise ChecklistError(
            "Не названо ни одного кода пункта. Подсказка без кодов — это заголовок таблицы, "
            "а не строка карты: разборщик продукта прочитает её именно так"
        )
    if len(codes) != len(места):
        названия = ", ".join(f"«{header[место]}»" for место in места) or "нет"
        зона = _zone_at(header)
        про_зону = (
            f" Колонка «{header[зона]}» правкой не задаётся и остаётся как записана."
            if зона is not None
            else ""
        )
        raise ChecklistError(
            f"Ячеек в строке этого раздела {len(места)} — {названия}, а названо {len(codes)}."
            f"{про_зону} Строка другой ширины разъезжается, и коды попадают не в те колонки — "
            f"а колонки здесь значат разное: «грязь» и «поломка» это два разных вопроса про "
            f"один объект"
        )
    if not any(_CODE.findall(cell.upper()) for cell in codes):
        raise ChecklistError(
            "Ни в одной названной ячейке нет ни одного кода пункта. Строка без кодов — это "
            "заголовок таблицы, а не строка карты: разборщик продукта прочитает её именно "
            "так. Коды выглядят как CLN05"
        )
    ячейки: list[str] = []
    for место, cell in zip(места, codes, strict=True):
        найденные = _CODE.findall(cell.upper())
        if найденные:
            чужие = sorted(set(найденные) - known)
            if чужие:
                raise ChecklistError(
                    f"Кодов {', '.join(чужие)} в методике этой версии нет. Подсказка вывела бы "
                    f"модели пункт, которого в чек-листе не существует, а быстрый путь записал "
                    f"бы его без подтверждения аудитора"
                )
            ячейки.append(", ".join(dict.fromkeys(найденные)))
            continue
        текст = (cell or "").strip()
        if место not in bearing:
            # Колонка управляющей компании: кодов она не несёт ни у одной
            # строки таблицы, и слова в ней — то, что там и написано.
            ячейки.append(текст)
            continue
        if текст not in _BLANK:
            raise ChecklistError(
                f"В колонке «{header[место]}» стоит «{текст}», а не код пункта. У других строк "
                f"этой таблицы коды в ней есть, значит колонка кодовая: сущности связываются "
                f"кодами, а не формулировками. Кода в этой колонке нет — так и напишите "
                f"«{_DASH}»"
            )
        ячейки.append(_DASH)
    return tuple(ячейки)


def _find(rows: list[_Row], phrase: str) -> _Row:
    """Строка карты с ровно этой фразой — или отказ.

    Похожей фразы здесь не ищется намеренно: подстановка «ближайшей» означала бы
    правку не той строки, а карта решает, что записывается без подтверждения
    аудитора.
    """
    нужная = phrase.strip().casefold()
    for row in rows:
        if row.cells[0].casefold() == нужная:
            return row
    raise ChecklistError(
        f"Строки «{phrase}» в карте слов нет. Строки карты называются своей фразой целиком "
        f"и дословно; перечень отдаёт photo_cues"
    )


def _cues_file(data_dir: Path) -> Path:
    return data_dir / CUES_FILE


def _text(data_dir: Path) -> str:
    path = _cues_file(data_dir)
    if not path.is_file():
        raise ChecklistError(
            f"В этой версии методики карты слов ({CUES_FILE}) нет. Файл необязательный, но "
            f"править в нём нечего, пока его не завёл человек"
        )
    return path.read_text(encoding="utf-8")


def _line(cells: tuple[str, ...]) -> str:
    return f"{_PIPE} " + f" {_PIPE} ".join(cells) + f" {_PIPE}"


def _verify(
    data_dir: Path,
    *,
    expected: dict[str, tuple[str, ...] | None],
    zones: dict[str, str] | None = None,
) -> None:
    """Сверить наблюдаемый результат разборщиком ПРОДУКТА, а не своим.

    `expected`: фраза → её коды, или `None`, если строки быть не должно.
    `zones`: фраза → зона, которую продукт обязан у неё увидеть (T293). Без
    этой сверки правка возвращала бы успех, не сделав работу: формат карты
    свободный, и строка, записанная чуть не так, тихо перестаёт быть строкой.
    """
    # `NO_CHAT`: карта читается по НАЗВАННОМУ каталогу версии из хранилища, а
    # не по изданию какой-то идущей проверки — здесь правят методику, а не
    # ведут выезд (T226).
    видно = {cue.phrase: cue for cue in load_cues(_cues_file(data_dir), chat_id=NO_CHAT)}
    for phrase, codes in expected.items():
        строка = видно.get(phrase)
        if codes is None:
            if строка is not None:
                raise ChecklistError(
                    f"Строка «{phrase}» осталась в карте после снятия: правка записана, но "
                    f"продукт видит прежнее"
                )
            continue
        if строка is None or строка.codes != codes:
            raise ChecklistError(
                f"После правки разборщик продукта видит у строки «{phrase}» коды "
                f"{None if строка is None else строка.codes}, а не {codes}. Правка записана "
                f"не так, как задумано"
            )
    for phrase, zone in (zones or {}).items():
        строка = видно.get(phrase)
        if строка is None or строка.zone != zone:
            raise ChecklistError(
                f"После правки разборщик продукта видит у строки «{phrase}» зону "
                f"«{'' if строка is None else строка.zone}», а не «{zone}». Правка записана "
                f"не так, как задумано"
            )


# --- чтение -------------------------------------------------------------------


def rows_of(store: Store, *, version: str | None = None) -> tuple[str, tuple[_Row, ...]]:
    """Строки карты слов версии — и имя самой версии, чьи это строки.

    Отдельно от `read` намеренно: `read` собирает ОТВЕТ агенту (вложенные
    словари, ключи протокола), а сборке предложений (T165) нужны сами строки с
    типами. Разобрать ответ обратно значило бы читать свой же вывод — и
    молча разъехаться с ним при первой правке формы ответа.
    """
    каталог = _version_dir(store, _ensure(store) if version is None else version)
    строки, _ = _scan(_text(каталог))
    return каталог.name, tuple(строки)


def read(store: Store, *, version: str | None = None) -> dict[str, object]:
    """Карта слов версии: разделы и строки, как их видит продукт."""
    каталог = _version_dir(store, _ensure(store) if version is None else version)
    rows, headers = _scan(_text(каталог))
    разделы: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        разделы.setdefault(row.section, []).append(
            {
                "phrase": row.cells[0],
                "codes": list(row.codes),
                # Ячейки — ровно те, что называет правка: из ответа агент
                # собирает её вызов, и лишняя ячейка вернулась бы отказом по
                # ширине. Зона стоит своим полем и правкой не задаётся.
                "cells": list(editable_cells(row)),
                "zone": _zone_value(row),
            }
        )
    return {
        "version": каталог.name,
        "file": CUES_FILE,
        "count": len(rows),
        "status": (
            f"{len(rows)} cue rows in {len(разделы)} sections; the map only adds and reorders "
            f"candidates and never trims them, and the thresholds section is not part of it. "
            f"'cells' and 'columns' are exactly what an edit names; the zone column is set by "
            f"the management company in the map itself and is kept as it is"
        ),
        "sections": [
            {
                "section": name,
                "columns": [
                    headers[name].cells[место]
                    for место in _named(headers[name].cells if name in headers else ())
                ],
                "cues": строки,
            }
            for name, строки in разделы.items()
        ],
    }


# --- правка -------------------------------------------------------------------


def add(
    store: Store,
    *,
    tenant: str,
    section: str,
    phrase: str,
    codes: list[str],
    version_name: str | None = None,
    note: str | None = None,
) -> Outcome:
    """Завести новую строку карты в названном разделе."""
    фраза = _check_phrase(phrase)

    def _mutate(кандидат: Path, _holder: Path) -> tuple[str | None, str]:
        текст = _text(кандидат)
        rows, headers = _scan(текст)
        if section.strip() not in headers:
            raise ChecklistError(
                f"Раздела «{section}» в карте слов нет. Опечатка завела бы раздел-двойник, и "
                f"половина карты разъехалась бы по двум местам. Разделы: "
                f"{', '.join(sorted(headers)) or 'нет'}"
            )
        if any(row.cells[0].casefold() == фраза.casefold() for row in rows):
            raise ChecklistError(
                f"Строка «{фраза}» в карте уже есть. Две строки с одной фразой — это правка "
                f"мимо цели: работать будет первая, а править человек станет вторую"
            )
        свои = [row for row in rows if row.section == section.strip()]
        шапка = headers[section.strip()]
        # Шапка ТОЙ таблицы, в которую строка ложится, а не первая шапка
        # раздела: под одним заголовком раздела боевой карты стоят семнадцать
        # таблиц, и новая строка встаёт в последнюю.
        заголовок = (свои[-1].header if свои else ()) or шапка.cells
        ячейки = _check_codes(
            codes,
            known=_known_codes(кандидат),
            header=заголовок,
            bearing=_code_bearing(rows, заголовок),
        )
        строки = текст.splitlines()
        # Строк у раздела ещё нет — встаём за его собственной шапкой (T291).
        # Прежний расчёт брал в этом случае ПЕРВУЮ строку всего файла, то есть
        # клал строку в чужую таблицу: раздел в вызове назван верно, отказа
        # нет, продукт видит строку под чужими колонками — а колонки значат
        # разное. Колонки при этом берутся у той же шапки, за которой строка
        # встаёт: разойдись эти два места, строка легла бы в одну таблицу с
        # колонками другой.
        куда = (свои[-1].index + 1) if свои else _after_head(строки, шапка)
        строки.insert(куда, _line(_compose(заголовок, ячейки, фраза, previous=None)))
        _cues_file(кандидат).write_text("\n".join(строки) + "\n", encoding="utf-8")
        коды = tuple(dict.fromkeys(_CODE.findall(" ".join(ячейки))))
        _verify(кандидат, expected={фраза: коды})
        return None, f"cue «{фраза}» added to section «{section.strip()}»"

    return apply_edit(
        store,
        tenant=tenant,
        tool="add_photo_cue",
        mutate=_mutate,
        version_name=version_name,
        note=note,
    )


def edit(
    store: Store,
    *,
    tenant: str,
    phrase: str,
    codes: list[str] | None = None,
    new_phrase: str | None = None,
    version_name: str | None = None,
    note: str | None = None,
) -> Outcome:
    """Поправить существующую строку: её коды, её фразу или и то и другое."""
    if codes is None and new_phrase is None:
        raise ChecklistError(
            "Не сказано, что менять: ни коды, ни фраза не названы. Правка без изменений "
            "записала бы в журнал правку, которой не было"
        )
    новая = _check_phrase(new_phrase) if new_phrase is not None else None

    def _mutate(кандидат: Path, _holder: Path) -> tuple[str | None, str]:
        текст = _text(кандидат)
        rows, _ = _scan(текст)
        строка = _find(rows, phrase)
        форма = _shape(строка)
        ячейки = (
            _check_codes(
                codes,
                known=_known_codes(кандидат),
                header=форма,
                bearing=_code_bearing(rows, форма),
            )
            if codes is not None
            else editable_cells(строка)
        )
        итоговая = новая if новая is not None else строка.cells[0]
        if новая is not None and новая.casefold() != строка.cells[0].casefold():
            занято = any(row.cells[0].casefold() == новая.casefold() for row in rows)
            if занято:
                raise ChecklistError(f"Строка «{новая}» в карте уже есть")
        строки = текст.splitlines()
        строки[строка.index] = _line(_compose(форма, ячейки, итоговая, previous=строка))
        _cues_file(кандидат).write_text("\n".join(строки) + "\n", encoding="utf-8")
        коды = tuple(dict.fromkeys(_CODE.findall(" ".join(ячейки))))
        ожидаемо: dict[str, tuple[str, ...] | None] = {итоговая: коды}
        if итоговая != строка.cells[0]:
            ожидаемо[строка.cells[0]] = None
        _verify(кандидат, expected=ожидаемо)
        return None, f"cue «{строка.cells[0]}» rewritten as «{итоговая}»"

    return apply_edit(
        store,
        tenant=tenant,
        tool="edit_photo_cue",
        mutate=_mutate,
        version_name=version_name,
        note=note,
    )


def remove(
    store: Store,
    *,
    tenant: str,
    phrase: str,
    version_name: str | None = None,
    note: str | None = None,
) -> Outcome:
    """Снять строку карты. Прежние версии остаются, поэтому откат — публикация."""

    def _mutate(кандидат: Path, _holder: Path) -> tuple[str | None, str]:
        текст = _text(кандидат)
        rows, _ = _scan(текст)
        строка = _find(rows, phrase)
        строки = текст.splitlines()
        del строки[строка.index]
        _cues_file(кандидат).write_text("\n".join(строки) + "\n", encoding="utf-8")
        _verify(кандидат, expected={строка.cells[0]: None})
        return None, f"cue «{строка.cells[0]}» removed"

    return apply_edit(
        store,
        tenant=tenant,
        tool="remove_photo_cue",
        mutate=_mutate,
        version_name=version_name,
        note=note,
    )


def set_zone(
    store: Store,
    *,
    tenant: str,
    phrase: str,
    zone: str,
    version_name: str | None = None,
    note: str | None = None,
) -> Outcome:
    """Поставить строке карты зону объекта — отдельным ходом от правки кодов (T293).

    Форму выбрало решение D125: отдельный инструмент, а не ещё одно поле у
    правки кодов. Причина названа там же — заполнение зон предстоит массовое, и
    смешанное с правкой кодов оно стирает границу между «поправил код» и
    «переназначил зону»: в журнале хранилища эти два действия перестали бы
    различаться, а различать их придётся именно тогда, когда что-то уедет
    партнёру не туда.

    **Зона сверяется со справочником зон ЭТОЙ версии.** Разбор карты сверять её
    не может — он не знает, о каком издании речь (`recognize.cues._zone`), — а
    здесь версия названа. Незнакомый код бот отбрасывает записью в лог, то есть
    молча для аудитора: на точке это выглядит как «карта не сработала», и найти
    причину человеку неоткуда.

    **Снятие называется прочерком.** Пустая зона — законное значение и означает
    «спросить», поэтому снять её надо чем-то; но пустой аргумент снимал бы зону
    молча всякий раз, когда вызов собран небрежно. Прочерк — тот же знак,
    которым карта пишет «здесь ничего нет»; в ячейку при этом уезжает ПУСТО, а
    не сам прочерк: прочерк разбор вернул бы как зону с таким названием.
    """
    значение = (zone or "").strip()
    if not значение:
        raise ChecklistError(
            f"Не названа зона. Пустой аргумент снял бы зону объекта молча; чтобы снять её "
            f"нарочно, назовите «{_DASH}» — карта пишет этим знаком «здесь ничего нет»"
        )
    снять = значение in _BLANK

    def _mutate(кандидат: Path, _holder: Path) -> tuple[str | None, str]:
        текст = _text(кандидат)
        rows, _ = _scan(текст)
        строка = _find(rows, phrase)
        форма = _shape(строка)
        место = _zone_at(форма)
        if место is None:
            raise ChecklistError(
                f"У таблицы этой строки нет колонки зоны (её заголовок — "
                f"{', '.join(f'«{имя}»' for имя in sorted(ZONE_HEADINGS))}): колонки таблицы — "
                f"{', '.join(f'«{имя}»' for имя in форма) or 'нет'}. Колонку заводит "
                f"управляющая компания в самой карте: дописанная отсюда, она сменила бы "
                f"ширину всех строк таблицы разом"
            )
        известные = _known_zones(кандидат)
        if снять:
            новая = ""
        else:
            подходящие = [код for код in известные if код.casefold() == значение.casefold()]
            if not подходящие:
                raise ChecklistError(
                    f"Зоны «{значение}» в методике этой версии нет. Бот сверяет зону строки "
                    f"со справочником издания и незнакомую отбрасывает в лог — то есть молча "
                    f"для аудитора. Зоны этой версии: {', '.join(известные) or 'нет'}"
                )
            новая = подходящие[0]
        ячейки = list(строка.cells) + [""] * max(0, len(форма) - len(строка.cells))
        ячейки[место] = новая
        строки = текст.splitlines()
        строки[строка.index] = _line(tuple(ячейки))
        _cues_file(кандидат).write_text("\n".join(строки) + "\n", encoding="utf-8")
        коды = tuple(dict.fromkeys(_CODE.findall(" ".join(editable_cells(строка)))))
        _verify(
            кандидат,
            expected={строка.cells[0]: коды},
            zones={строка.cells[0]: новая},
        )
        сказано = новая or _DASH
        return None, f"zone of cue «{строка.cells[0]}» set to «{сказано}»"

    return apply_edit(
        store,
        tenant=tenant,
        tool="set_photo_cue_zone",
        mutate=_mutate,
        version_name=version_name,
        note=note,
    )
