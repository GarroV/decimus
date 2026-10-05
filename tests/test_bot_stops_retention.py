"""Счётчик отказов хранит 90 дней и обрезается без потери строк (#501).

`bot-stops.jsonl` рос по строке на отказ без конца. Здесь проверяется: старое
уходит, свежее остаётся, `/stops` за любой разрешённый период считает то же,
что до обрезки, а строка, дописанная посреди обрезки, не теряется при подмене
файла.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiogram.filters import CommandObject

from src.bot import stops
from src.bot.routers.stops import _days

СЕЙЧАС = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def строка(дней_назад: float, *, кто: int = 1, шаг: str = "start.unit") -> str:
    at = СЕЙЧАС - timedelta(days=дней_назад)
    return json.dumps(
        {"at": at.isoformat(), "step": шаг, "reason": "start.unit_need_number", "telegram_id": кто}
    )


def записать(path: Path, строки: list[str]) -> None:
    path.write_text("".join(s + "\n" for s in строки), encoding="utf-8")


def строк_в(path: Path) -> int:
    return len([r for r in path.read_text(encoding="utf-8").splitlines() if r.strip()])


@pytest.fixture
def счётчик(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / stops.STOPS_FILE_NAME
    monkeypatch.setattr(stops, "stops_path", lambda: path)
    monkeypatch.setattr(stops, "_now", lambda: СЕЙЧАС)
    return path


def test_обрезка_убирает_старше_срока_и_оставляет_свежее(счётчик: Path) -> None:
    записать(
        счётчик,
        [строка(200), строка(91), "не json", строка(89, кто=2), строка(1, кто=3)],
    )

    убрано = stops.prune_stops(path=счётчик, now=СЕЙЧАС)

    assert убрано == 3
    assert строк_в(счётчик) == 2


def test_счёт_за_любой_разрешённый_период_после_обрезки_тот_же(счётчик: Path) -> None:
    записать(счётчик, [строка(d, кто=d % 7) for d in range(400, 0, -3)])
    до = {
        дни: stops.count_stops(СЕЙЧАС - timedelta(days=дни), path=счётчик)
        for дни in (1, 7, 30, stops.STOPS_RETENTION_DAYS)
    }

    stops.prune_stops(path=счётчик, now=СЕЙЧАС)

    for дни, было in до.items():
        assert stops.count_stops(СЕЙЧАС - timedelta(days=дни), path=счётчик) == было, дни


def test_запись_обрезает_когда_старейшая_строка_вышла_за_срок(счётчик: Path) -> None:
    записать(счётчик, [строка(120), строка(100), строка(5)])

    stops.note_stop(42, step="finish.archive", reason="finish.no_db")

    строки = [json.loads(r) for r in счётчик.read_text(encoding="utf-8").splitlines()]
    assert [s["telegram_id"] for s in строки] == [1, 42]


def test_запись_не_переписывает_файл_когда_старого_нет(счётчик: Path) -> None:
    записать(счётчик, [строка(10), строка(5)])
    узел = счётчик.stat().st_ino

    stops.note_stop(42, step="finish.archive", reason="finish.no_db")

    assert счётчик.stat().st_ino == узел
    assert строк_в(счётчик) == 3


def test_строка_дописанная_посреди_обрезки_не_теряется(
    счётчик: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись встревает между чтением и подменой файла — и обязана дождаться подмены.

    Порядок задан, а не угадан: подмена файла сама запускает запись в другом
    потоке и ждёт её до полсекунды. Под блокировкой запись ждёт конца обрезки
    и ложится в новый файл; без блокировки она ложится в старый и пропадает.
    """
    записать(счётчик, [строка(200), строка(3)])
    настоящая_подмена = stops.os.replace
    писатели: list[threading.Thread] = []

    def подмена(src: Any, dst: Any) -> None:
        if писатели:  # встревает только одна запись, иначе без блокировки — бесконечно
            настоящая_подмена(src, dst)
            return
        писатель = threading.Thread(
            target=stops.note_stop, args=(77,), kwargs={"step": "s", "reason": "r"}
        )
        писатели.append(писатель)
        писатель.start()
        писатель.join(timeout=0.5)
        настоящая_подмена(src, dst)

    monkeypatch.setattr(stops.os, "replace", подмена)

    stops.prune_stops(path=счётчик, now=СЕЙЧАС)
    for писатель in писатели:
        писатель.join(timeout=5)

    кто = [json.loads(r)["telegram_id"] for r in счётчик.read_text(encoding="utf-8").splitlines()]
    assert 77 in кто, "строка, дописанная во время обрезки, потеряна при подмене файла"


@pytest.mark.parametrize(
    ("аргумент", "ждём"),
    [("", 7), ("90", 90), ("91", None), ("366", None)],
)
def test_период_stops_не_длиннее_срока_хранения(аргумент: str, ждём: int | None) -> None:
    команда = CommandObject(prefix="/", command="stops", args=аргумент or None)

    assert _days(команда) == ждём
