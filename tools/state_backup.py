"""Бэкап тома состояния стенда (`STATE_DIR`) в каталог бэкапа (задача #233).

Том состояния не выгружается никуда. В нём лежат папки идущих проверок и файл
связок доступа `access/roster.json` — «юзернейм → числовой Telegram ID»
(`src/bot/roster.py`, `Roster`). Отметки «приглашение использовано» отдельного
журнала не имеют, они вычисляются из этого же файла (`Roster.username_used`).
Потеря файла означает: тот, чей юзернейм владелец убрал из `BOT_INVITES`
после активации, теряет доступ навсегда, а освободившийся юзернейм, занятый
посторонним, открывает ему дверь. Поэтому связки проверяются в архиве
отдельно от общего списка файлов, а не молчаливо попутно с остальным.

Бэкап площадки сегодня умеет только дампы Postgres (задача по метке
`backup.pgdump=true`), ретеншн 14 суток — отсюда умолчание `BACKUP_KEEP_DAYS`.

Запуск (в контейнере стенда):

    python tools/state_backup.py

Код возврата 0 — бэкап собран (или на свежем стенде и собирать было нечего
из связок — это законный случай), 1 — отказ. Причина отказа печатается одной
строкой в stderr, без трейсбека: трейсбек показал бы устройство площадки, а
человеку, который чинит бэкап, нужна причина, а не стек.
"""

from __future__ import annotations

import os
import sys
import tarfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Обязательные переменные окружения. Умолчаний у путей нет намеренно: тихая
#: подстановка каталога по умолчанию означала бы либо бэкап не того тома,
#: либо создание каталога без внимания человека к тому, что путь не задан.
STATE_DIR_VAR = "STATE_DIR"
BACKUP_DIR_VAR = "BACKUP_DIR"

#: Необязательная переменная — сколько суток хранить СВОИ архивы.
BACKUP_KEEP_DAYS_VAR = "BACKUP_KEEP_DAYS"
DEFAULT_KEEP_DAYS = 14

#: Имя архива и маска, по которой ретеншн узнаёт «свои» файлы в общем каталоге
#: бэкапа — рядом лежат дампы чужих проектов площадки, их трогать нельзя.
ARCHIVE_PREFIX = "decimus-state-"
ARCHIVE_SUFFIX = ".tar.gz"
ARCHIVE_GLOB = f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}"

#: Путь связок доступа внутри тома состояния — тот же, что в `src/bot/roster.py`
#: (`ROSTER_DIR`/`ROSTER_FILE`). Копия строки, а не импорт: инструмент обязан
#: остаться независимым от графа импортов продукта (тем же приёмом живёт
#: `SERVER_HEADER` в `tools/mcp_healthcheck.py`).
ROSTER_RELATIVE_PATH = "access/roster.json"

ROSTER_IN_ARCHIVE_LINE = f"Связки доступа ({ROSTER_RELATIVE_PATH}) попали в архив."
ROSTER_ABSENT_LINE = "Связок нет: на этом стенде ещё никто не приглашён."

SECONDS_PER_DAY = 86400


class BackupError(Exception):
    """Отказ бэкапа. Причина уже сформулирована человеку — без трейсбека."""


@dataclass(frozen=True)
class BackupResult:
    """Что печатать по итогам успешного прогона."""

    archive_path: Path
    file_count: int
    archive_size: int
    roster_line: str
    removed: tuple[str, ...]


def _require_dir(env: Mapping[str, str], var_name: str) -> Path:
    """Каталог из переменной окружения. Пусто, не каталог, нет пути — отказ."""
    raw = (env.get(var_name) or "").strip()
    if not raw:
        raise BackupError(f"переменная {var_name} не задана")
    path = Path(raw)
    if not path.is_dir():
        raise BackupError(f"{var_name}={raw!r} — не каталог или не существует")
    return path


def _resolve_keep_days(env: Mapping[str, str]) -> int:
    """Сколько суток хранить свои архивы. Пусто — умолчание, кривое — отказ."""
    raw = (env.get(BACKUP_KEEP_DAYS_VAR) or "").strip()
    if not raw:
        return DEFAULT_KEEP_DAYS
    try:
        value = int(raw)
    except ValueError as err:
        raise BackupError(f"{BACKUP_KEEP_DAYS_VAR}={raw!r} — не число") from err
    if value < 0:
        raise BackupError(f"{BACKUP_KEEP_DAYS_VAR}={raw!r} — не может быть отрицательным")
    return value


def _archive_name(moment: datetime) -> str:
    """Имя архива по времени UTC: `decimus-state-YYYYmmdd-HHMMSS.tar.gz`."""
    return f"{ARCHIVE_PREFIX}{moment.strftime('%Y%m%d-%H%M%S')}{ARCHIVE_SUFFIX}"


def _state_has_files(state_dir: Path) -> bool:
    return any(путь.is_file() for путь in state_dir.rglob("*"))


def _write_archive(state_dir: Path, archive_path: Path) -> list[str]:
    """Сложить содержимое `state_dir` в архив по пути `archive_path`.

    Пишет во временный файл рядом и переименовывает через `os.replace` — тем
    же приёмом и по той же причине, что `Roster._save` (`src/bot/roster.py`):
    оборванная запись не имеет права оставить на месте бэкапа обрезанный
    архив, который снаружи выглядит целым.

    Пути внутри архива — относительные от `state_dir`: абсолютный путь показал
    бы устройство каталогов площадки и потребовал бы `--strip-components` при
    восстановлении.

    Отдельная от сверки функция — намеренно: тест на сверку подменяет именно
    эту функцию, оставляя проверку читаемости архива настоящей.
    """
    tmp_path = archive_path.with_name(f".{archive_path.name}.tmp")
    имена: list[str] = []
    # Оборванная запись убирает за собой. Иначе в каталоге бэкапа остаётся
    # `.decimus-state-<время>.tar.gz.tmp`, которого не видит ни человек (имя
    # начинается с точки), ни ретеншн (маска `ARCHIVE_GLOB` его не ловит) — и
    # каждый неудачный прогон добавляет ещё один. Каталог на площадке общий с
    # чужими проектами, так что растёт при этом не только наше место.
    try:
        with tarfile.open(tmp_path, "w:gz") as архив:
            for файл in sorted(путь for путь in state_dir.rglob("*") if путь.is_file()):
                относительный = файл.relative_to(state_dir).as_posix()
                архив.add(файл, arcname=относительный)
                имена.append(относительный)
        os.replace(tmp_path, archive_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return имена


def _verify_archive(archive_path: Path, expected_names: Sequence[str]) -> None:
    """Перечитать записанный архив и сверить список имён с тем, что клали.

    Не сошлось или архив не читается — отказ: битый бэкап хуже отсутствующего,
    и вызывающий код обязан удалить файл, получив это исключение.
    """
    try:
        with tarfile.open(archive_path, "r:gz") as архив:
            найдено = архив.getnames()
    except (tarfile.TarError, OSError) as err:
        raise BackupError(f"записанный архив не читается: {err}") from err
    if sorted(найдено) != sorted(expected_names):
        raise BackupError(
            "записанный архив разошёлся с тем, что клали: "
            f"в архиве {len(найдено)} файлов, записывалось {len(expected_names)}"
        )


def _roster_line(state_dir: Path, names: Sequence[str]) -> str:
    """Строка про судьбу связок доступа. Есть в состоянии, но не в архиве — отказ.

    Это ровно та поломка, ради которой инструмент заведён: бэкап без связок
    молча сходит за полноценный.
    """
    if not (state_dir / ROSTER_RELATIVE_PATH).is_file():
        return ROSTER_ABSENT_LINE
    if ROSTER_RELATIVE_PATH not in names:
        raise BackupError(
            f"{ROSTER_RELATIVE_PATH} есть в состоянии, но не попал в архив — "
            "связки доступа потерялись бы вместе с этим бэкапом"
        )
    return ROSTER_IN_ARCHIVE_LINE


def _remove_stale_backups(backup_dir: Path, keep_days: int, keep_path: Path) -> list[str]:
    """Удалить СВОИ старые архивы. `keep_days == 0` значит «не удалять ничего».

    Маска имени (`ARCHIVE_GLOB`) — единственный признак «своего» файла: рядом
    в каталоге бэкапа лежат дампы чужих проектов площадки, и их не трогает
    ничто здесь. Только что записанный архив исключён явно и не удаляется ни
    при каких значениях `keep_days`.
    """
    if keep_days <= 0:
        return []
    порог = time.time() - keep_days * SECONDS_PER_DAY
    удалённые: list[str] = []
    for кандидат in sorted(backup_dir.glob(ARCHIVE_GLOB)):
        if кандидат == keep_path:
            continue
        if кандидат.stat().st_mtime >= порог:
            continue
        кандидат.unlink()
        удалённые.append(кандидат.name)
    return удалённые


def run_backup(env: Mapping[str, str]) -> BackupResult:
    """Собрать бэкап тома состояния по переменным окружения `env`.

    Отказ на любом шаге — `BackupError` с человеческой причиной; частично
    записанный архив за собой не оставляется.
    """
    state_dir = _require_dir(env, STATE_DIR_VAR)
    backup_dir = _require_dir(env, BACKUP_DIR_VAR)
    keep_days = _resolve_keep_days(env)

    if not _state_has_files(state_dir):
        raise BackupError(f"{STATE_DIR_VAR}={state_dir} пуст — бэкапировать нечего")

    archive_path = backup_dir / _archive_name(datetime.now(UTC))
    имена = _write_archive(state_dir, archive_path)
    try:
        _verify_archive(archive_path, имена)
        roster_line = _roster_line(state_dir, имена)
    except BackupError:
        archive_path.unlink(missing_ok=True)
        raise

    removed = tuple(_remove_stale_backups(backup_dir, keep_days, keep_path=archive_path))

    return BackupResult(
        archive_path=archive_path,
        file_count=len(имена),
        archive_size=archive_path.stat().st_size,
        roster_line=roster_line,
        removed=removed,
    )


def _print_result(result: BackupResult) -> None:
    print(f"Архив: {result.archive_path.name}")
    print(f"Файлов в архиве: {result.file_count}")
    print(f"Размер архива: {result.archive_size} байт")
    print(result.roster_line)
    for имя in result.removed:
        print(f"Удалён старый бэкап: {имя}")


def main() -> int:
    try:
        result = run_backup(os.environ)
    except BackupError as причина:
        print(f"[state-backup] не вышло: {причина}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
