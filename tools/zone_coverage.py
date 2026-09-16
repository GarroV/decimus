#!/usr/bin/env python3
"""T272: покрытие словаря зон — сколько формулировок доходит до зоны и что дописать.

Колонка «Зона» в карте кадров (`data/photo-cues.md`, T262) заполняется
управляющей компанией постепенно, строка за строкой. Без числа «постепенно»
превращается в ощущение: никто не знает, много ли осталось и что именно
дописать следующим. Этот замер отвечает на оба вопроса — и отвечает данными,
а не прикидкой.

**Что меряется.** Формулировка аудитора доходит до зоны тремя путями, и
порядок задан продуктом (`src/bot/zones.py::resolve_zone`, T263): слова
аудитора, затем словарь объектов карты кадров, затем спрос кнопкой у человека.
Третий путь здесь не считается вовсе — его даёт человек, и считать его в
покрытие словаря значило бы записать себе в заслугу чужую работу. Меряются
первые два, порознь.

**Чем этот замер отличается от `tools/fastpath_measure.py`.** Тот меряет, как
часто быстрый путь ОТВЕЧАЕТ ПУНКТОМ; здесь — как часто вообще известна зона.
Зона нужна не только быстрому пути: по ней движок проверяет допустимость пары
«пункт + зона» (T271), ею упорядочен перечень кандидатов (T265), и без неё
разговор с аудитором становится длиннее на один вопрос. Слить два замера в
один нельзя: они меряют разные вещи и двигаются в разные стороны.

**Третий раздел — то, ради чего замер и заведён.** Он берёт формулировки, у
которых зоны не вышло, смотрит, какие строки карты они всё-таки задели, и
называет те из них, у которых колонка «Зона» пуста, по частоте. Это и есть
готовый список «дописать сюда, и покроется столько-то»: не догадка о том, что
полезно, а перечень строк, на которых замер уже споткнулся.

**Корпус — боевые записи `examples/` и накопитель непокрытых формулировок**
(`src/domain/uncovered.py`, T268), если он есть. Первое — то, что аудиторы уже
сказали на двух прошедших проверках; второе — то, что они говорят сейчас и что
до записи не дошло. Накопителя может не быть вовсе, и это законный исход, а не
отказ: до первой проверки на новой машине его никто не заводил.

**Зона выводится продуктовыми функциями, а не своей копией правил.**
`zone_from_words` и `dictionary_zone` — те самые, которыми зону выводит бот.
Копия разошлась бы с продуктом при первой правке и дала бы число, которого на
точке не бывает; ровно этим был неверен замер быстрого пути до T125.

Ни одного обращения к сети: вывод зоны детерминированный, замер бесплатный.

Запуск:  python tools/zone_coverage.py [--root PATH]

Окружение: `AUDIT_DATA_DIR` инструмент подставляет себе сам (методика
репозитория), `STATE_DIR` обязан задать запускающий — его требует любое
обращение к методике (`src/domain/config.py`).

Коды возврата: 0 — норма, 2 — замерять не по чему: ни боевых записей, ни
накопителя, либо окружение не настроено.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("AUDIT_DATA_DIR", str(ROOT / "data"))
sys.path.insert(0, str(ROOT))

from src.bot.zones import dictionary_zone, zone_from_words  # noqa: E402
from src.domain.errors import DomainError  # noqa: E402
from src.domain.uncovered import read_uncovered  # noqa: E402
from src.recognize.config import NO_CHAT  # noqa: E402
from src.recognize.cues import Cue, load_cues, matched_cues  # noqa: E402
from tools.fastpath_measure import (  # noqa: E402
    FROM_DICTIONARY,
    FROM_NOWHERE,
    FROM_WORDS,
    fingerprint,
    load_records,
)

#: Сколько строк «дописать сюда» печатаем. Список читает человек, и хвост из
#: строк, задетых однажды, он всё равно не разберёт.
ROWS_TO_NAME = 15


@dataclass(frozen=True)
class Said:
    """Одна формулировка корпуса и откуда она взялась."""

    note: str
    source: str


@dataclass(frozen=True)
class Reached:
    """Дошла ли формулировка до зоны и каким путём."""

    said: Said
    zone: str | None
    source: str
    #: Строки карты, задетые формулировкой, у которых колонка «Зона» пуста.
    #: Считаются только там, где зоны не вышло: там, где она вышла, дописывать
    #: нечего.
    blank_rows: tuple[str, ...]


def corpus(root: Path) -> tuple[Said, ...]:
    """Боевые записи `examples/` плюс накопитель, если он есть.

    Накопителя нет — не отказ: до первой проверки на машине его никто не
    заводил. А вот испорченный накопитель отказом остаётся: молчаливая пустота
    на его месте означала бы потерянный сигнал, и замер отчитался бы по одним
    только `examples/`, не сказав об этом ни слова.
    """
    said = [Said(note=r.note, source=f"examples/{r.source}") for r in load_records(root)]
    said.extend(Said(note=e.note, source="накопитель") for e in read_uncovered())
    return tuple(said)


def _blank_rows(note: str, cues: Sequence[Cue]) -> tuple[str, ...]:
    """Задетые строки карты без зоны. Строка с зоной сюда не попадает: дописывать нечего."""
    return tuple(cue.phrase for cue in matched_cues(note, tuple(cues)) if not cue.zone)


def reach(said: Sequence[Said], cues: Sequence[Cue]) -> tuple[Reached, ...]:
    """Довести каждую формулировку до зоны продуктовым правилом: слова, затем словарь."""
    out: list[Reached] = []
    for one in said:
        spoken = zone_from_words(one.note, chat_id=NO_CHAT)
        if spoken:
            out.append(Reached(said=one, zone=spoken, source=FROM_WORDS, blank_rows=()))
            continue
        known = dictionary_zone(one.note, chat_id=NO_CHAT)
        if known:
            out.append(Reached(said=one, zone=known[0], source=FROM_DICTIONARY, blank_rows=()))
            continue
        out.append(
            Reached(
                said=one,
                zone=None,
                source=FROM_NOWHERE,
                blank_rows=_blank_rows(one.note, cues),
            )
        )
    return tuple(out)


def _map_section(cues: Sequence[Cue]) -> list[str]:
    """Колонка «Зона» карты: сколько строк её несут и какие зоны названы."""
    с_зоной = [cue for cue in cues if cue.zone]
    зоны = Counter(cue.zone for cue in с_зоной)
    доля = 100 * len(с_зоной) / len(cues) if cues else 0.0
    строки = [
        "Колонка «Зона» карты кадров",
        "",
        f"Строк в карте: {len(cues)}. С названной зоной: {len(с_зоной)} ({доля:.0f}%).",
        "",
        "Пустая зона — законный ответ, а не пробел в данных: объект, стоящий в разных",
        "цехах, зону не называет, и дописанная ему зона увела бы запись не туда. Поэтому",
        "доля здесь не обязана расти до ста процентов; расти обязано покрытие ниже.",
    ]
    if зоны:
        строки += [
            "",
            "| Зона | Строк карты |",
            "|---|---|",
            *(
                f"| {код} | {счёт} |"
                for код, счёт in sorted(зоны.items(), key=lambda п: (-п[1], п[0]))
            ),
        ]
    return строки


def _reach_section(reached: Sequence[Reached]) -> list[str]:
    """Сколько формулировок дошло до зоны и каким путём."""
    счёт = Counter(r.source for r in reached)
    всего = len(reached)
    покрыто = счёт[FROM_WORDS] + счёт[FROM_DICTIONARY]
    по_корпусу = Counter(r.said.source for r in reached)
    строки = [
        "Формулировка → зона",
        "",
        f"Формулировок в корпусе: {всего} "
        f"({', '.join(f'{имя}: {n}' for имя, n in sorted(по_корпусу.items()))}).",
        "",
        "| Путь к зоне | Формулировок | Доля |",
        "|---|---|---|",
    ]
    for имя in (FROM_WORDS, FROM_DICTIONARY, FROM_NOWHERE):
        n = счёт[имя]
        строки.append(f"| {имя} | {n} | {100 * n / всего if всего else 0:.0f}% |")
    строки += [
        "",
        f"Зона известна без вопроса человеку: {покрыто} из {всего} "
        f"({100 * покрыто / всего if всего else 0:.0f}%). Остальное спрашивается кнопкой — "
        "это не потеря, а лишний шаг разговора.",
    ]
    return строки


def _todo_section(reached: Sequence[Reached]) -> list[str]:
    """Строки карты, дописав зону у которых, покроем больше формулировок."""
    счёт: Counter[str] = Counter()
    for r in reached:
        счёт.update(set(r.blank_rows))
    немые = [r for r in reached if r.source == FROM_NOWHERE and not r.blank_rows]
    строки = [
        "Что дописать в колонку «Зона»",
        "",
        "Строки, задетые формулировками, у которых зоны не вышло. Порядок — по числу",
        "формулировок: дописанная сверху покроет больше, чем дописанная снизу.",
    ]
    if not счёт:
        строки += [
            "",
            "Таких строк нет: у всех задетых строк зона уже названа. Формулировки без",
            "зоны не задели карту вовсе — им поможет не колонка «Зона», а новые строки.",
        ]
    else:
        названные = счёт.most_common(ROWS_TO_NAME)
        строки += [
            "",
            "| Строка карты | Формулировок ждёт |",
            "|---|---|",
            *(f"| {фраза} | {n} |" for фраза, n in названные),
        ]
        остаток = len(счёт) - len(названные)
        if остаток:
            строки.append("")
            строки.append(f"Ещё строк в хвосте: {остаток}.")
    строки += [
        "",
        f"Формулировок, не задевших карту ни одной строкой: {len(немые)}. Колонка «Зона» "
        "им не поможет — здесь не хватает самой строки карты, а заводит её управляющая "
        "компания (D066, D077).",
    ]
    return строки


def render(cues: Sequence[Cue], reached: Sequence[Reached]) -> str:
    """Отчёт целиком. Чистая функция: сеть, диск и окружение остаются снаружи."""
    return "\n".join(
        [
            f"Замер покрытия словаря зон — {date.today().isoformat()}",
            f"Карта кадров data/photo-cues.md: {fingerprint()}. Числа привязаны к ЭТОЙ "
            "версии карты (D066): после её правки замер снимается заново.",
            "",
            *_map_section(cues),
            "",
            *_reach_section(reached),
            "",
            *_todo_section(reached),
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Покрытие словаря зон: формулировка → зона")
    parser.add_argument("--root", type=Path, default=ROOT, help="корень с examples/")
    args = parser.parse_args(argv)

    try:
        cues = load_cues(chat_id=NO_CHAT)
        said = corpus(args.root)
    except DomainError as отказ:
        print(f"Замера не произошло: {отказ}", file=sys.stderr)
        return 2
    if not said:
        print(
            "Замера не произошло: ни боевых записей в examples/, ни накопителя. "
            "Данные методики лежат вне репозитория (D002) — на чужой машине это норма.",
            file=sys.stderr,
        )
        return 2
    print(render(cues, reach(said, cues)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
