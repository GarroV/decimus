"""Уборка кадров мини-аппа, не попавших ни в одну проверку (F-033, #531).

Кадр уходит на сервер сразу после снимка, а запись — потом. Брошенный
черновик оставляет кадр в `STATE_DIR/uploads/` без единой ссылки на него, и
раньше такие кадры лежали бессрочно. Здесь они убираются по сроку.

**Что считается привязанным — и не трогается никогда:**

* ссылка в любом JSON папки чата (`chat_*/*.json`): открытая проверка, заметки
  бота — всё, что ещё может уйти в отчёт;
* ссылка из базы (`photos.telegram_file_id`) — её передаёт вызывающий: сданная
  проверка, кадр которой, может быть, ещё не лёг в хранилище (#459).

Не знает вызывающий, что в базе, — уборку не зовёт вовсе: удалить кадр сданной
проверки хуже, чем подержать брошенный ещё сутки.

**Срок** — `UNATTACHED_TTL_SEC` от последнего касания файла. Касание — присылка
и приложение кадра (`uploads._touch`), поэтому срок длиннее любого живого
ожидания: кадр без связи ждёт на телефоне до 3 суток (D442), а потом ещё
может полежать в черновике.

Метки «кто прислал» старше срока убираются тоже: квоте нужны только сутки, а
право приложить кадр, уже висящий в проверке, даёт сама проверка.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .uploads import UPLOADS_DIR_NAME, owners_dir

#: Сколько непривязанный кадр живёт после последнего касания.
UNATTACHED_TTL_SEC = 7 * 24 * 60 * 60

#: Недописанный временный файл (`*.part`) старше часа — след оборванной записи.
STALE_PART_SEC = 60 * 60

_REF_IN_TEXT = re.compile(r"walk:([0-9a-f]{32})")
_BLOB = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class SweepResult:
    frames: int
    marks: int
    parts: int


def referenced_in_state(state_dir: Path) -> set[str]:
    """Отпечатки кадров, на которые ссылается что-то в папках чатов."""
    found: set[str] = set()
    for path in state_dir.glob("chat_*/*.json"):
        try:
            found.update(_REF_IN_TEXT.findall(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            continue
    return found


def _digests(refs: Iterable[str]) -> set[str]:
    return {hit.group(1) for ref in refs if (hit := _REF_IN_TEXT.fullmatch(ref))}


def _old(path: Path, now: float, age: float) -> bool:
    try:
        return now - path.stat().st_mtime > age
    except FileNotFoundError:
        return False


def sweep_uploads(
    settings: Settings, *, keep: Iterable[str], now: float | None = None
) -> SweepResult:
    """Убрать непривязанные кадры старше срока и просроченные метки.

    `keep` — ссылки из базы. Ссылки из папок чатов читаются здесь же.
    """
    moment = time.time() if now is None else now
    root = settings.state_dir / UPLOADS_DIR_NAME
    if not root.is_dir():
        return SweepResult(0, 0, 0)
    attached = _digests(keep) | referenced_in_state(settings.state_dir)
    frames = parts = 0
    for path in root.glob("??/*"):
        if path.suffix == ".part":
            if _old(path, moment, STALE_PART_SEC):
                path.unlink(missing_ok=True)
                parts += 1
            continue
        if path.suffix != ".jpg" or not _BLOB.match(path.stem) or path.stem in attached:
            continue
        # Время смотрится у самого удаления: кадр, приложенный за миг до него,
        # освежён (`uploads.own_upload`) и остаётся.
        if _old(path, moment, UNATTACHED_TTL_SEC):
            path.unlink(missing_ok=True)
            frames += 1
    marks = 0
    for mark in owners_dir(settings).glob("*/*"):
        if _old(mark, moment, UNATTACHED_TTL_SEC):
            mark.unlink(missing_ok=True)
            marks += 1
    return SweepResult(frames, marks, parts)
