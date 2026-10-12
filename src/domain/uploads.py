"""Кадры, снятые в мини-аппе обхода (D312): где лежат и как на них сослаться.

Кадр из чата хранится идентификатором телеграма, и скачивает его бот. Кадр из
мини-аппа приходит байтами по HTTPS — идентификатора у него нет и взять его
негде, не отправив кадр сообщением в чат. Поэтому такой кадр ложится файлом в
папку состояния (`<STATE_DIR>/uploads/`), а в запись уходит ссылка
`walk:<отпечаток>`.

Ссылка — отпечаток содержимого, а не имя от телефона: повтор загрузки на
плохой связи даёт ту же ссылку, а не второй файл, и ни один символ ссылки не
приходит из запроса — путь из неё собирается только здесь и только из
шестнадцатеричных цифр.

Кто читает: бот на сборке отчёта (`bot/photos.fetch_bytes` — та же дверь, что
у кадров телеграма) и сам мини-апп, когда показывает кадр записи.

**Кадр помнит, кто его прислал** (F-034). Файл общий — одинаковые байты дают
одну ссылку, — а рядом на каждого приславшего лежит метка
`uploads/owners/<чат>/<отпечаток>` с размером кадра. Приложить кадр к записи
можно только свой: ссылка, подсмотренная у чужой проверки, не пропуск к
чужим байтам. Повтор своего же кадра (досылка без связи, D442) метку не
дублирует и в квоту не считается.

**Квота на чат** (F-033). За сутки с одного чата — не больше
`QUOTA_FRAMES` кадров и `QUOTA_BYTES` байт; считается по меткам. Живой обход
укладывается с запасом, а залить общий том состояния нельзя. Брошенные кадры
убирает `upload_sweep`.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .errors import DomainError, ValidationError

UPLOAD_PREFIX = "walk:"
UPLOADS_DIR_NAME = "uploads"

#: Предел одного кадра. Телефон сжимает снимок до ~0,5 МБ перед отправкой
#: (`walk-photo.js`); 10 МБ — запас на несжатый кадр, а не норма.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Начало JPEG. Других форматов не принимаем: телефон перекодирует снимок в
#: JPEG сам, а движок отчёта печатает его без преобразований.
JPEG_MAGIC = b"\xff\xd8\xff"

#: Предел кадра в пикселях. Телефон присылает до 1600 px по длинной стороне;
#: предел отсекает «бомбу» — крошечный файл, который разворачивается в
#: гигабайты на сборке отчёта.
MAX_PIXELS = 50_000_000

_REF = re.compile(r"^walk:([0-9a-f]{32})$")

#: Папка меток «кто прислал». Не две шестнадцатеричные цифры — с папками
#: кадров не пересекается.
OWNERS_DIR_NAME = "owners"

#: Окно квоты — скользящие сутки по времени меток.
QUOTA_WINDOW_SEC = 24 * 60 * 60
#: Кадров за окно с одного чата. На проде на 12.10.2026 пик — 29 кадров на
#: проверку и 66 у аудитора за день; 400 — запас в несколько раз.
QUOTA_FRAMES = 400
#: Байт за окно с одного чата. Телефон шлёт ~0,5 МБ на кадр: 400 кадров —
#: около 200 МБ; несжатые кадры по 10 МБ упрутся сюда раньше, чем в число.
QUOTA_BYTES = 300 * 1024 * 1024


class UploadQuotaError(DomainError):
    """Квота кадров чата за сутки выбрана. Текст для человека — у поверхности."""


def is_upload_ref(ref: str) -> bool:
    """Ссылка ли это на кадр мини-аппа (а не идентификатор телеграма или путь)."""
    return _REF.match(ref) is not None


def _digest(ref: str) -> str:
    hit = _REF.match(ref)
    if hit is None:
        raise ValidationError(f"«{ref}» не ссылка на кадр мини-аппа")
    return hit.group(1)


def _path(ref: str, settings: Settings) -> Path:
    digest = _digest(ref)
    return settings.state_dir / UPLOADS_DIR_NAME / digest[:2] / f"{digest}.jpg"


def _check_decodes(raw: bytes) -> None:
    """Кадр обязан разбираться как JPEG разумного размера, а не только начинаться им.

    Три байта заголовка и мусор следом приняла бы проверка по сигнатуре, а
    упала бы сборка отчёта — у партнёра на глазах и через неделю после выезда.
    """
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "JPEG":
                raise ValidationError("Кадр не похож на JPEG")
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise ValidationError("Кадр слишком большой по пикселям")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise ValidationError("Кадр не разбирается как JPEG") from exc


def owners_dir(settings: Settings) -> Path:
    return settings.state_dir / UPLOADS_DIR_NAME / OWNERS_DIR_NAME


def _mark_path(ref: str, owner: int, settings: Settings) -> Path:
    return owners_dir(settings) / str(int(owner)) / _digest(ref)


def _usage(owner: int, settings: Settings, now: float) -> tuple[int, int]:
    """Сколько кадров и байт чат прислал за окно квоты — по его меткам."""
    folder = owners_dir(settings) / str(int(owner))
    frames = size = 0
    if not folder.is_dir():
        return 0, 0
    for mark in folder.iterdir():
        try:
            if now - mark.stat().st_mtime >= QUOTA_WINDOW_SEC:
                continue
            text = mark.read_text().strip()
        except OSError:
            continue
        frames += 1
        size += int(text) if text.isdigit() else MAX_UPLOAD_BYTES
    return frames, size


def _check_quota(owner: int, incoming: int, settings: Settings) -> None:
    frames, size = _usage(owner, settings, time.time())
    if frames + 1 > QUOTA_FRAMES or size + incoming > QUOTA_BYTES:
        raise UploadQuotaError(f"квота кадров за сутки выбрана: {frames} кадров, {size} байт")


def _mark(ref: str, owner: int, size: int, settings: Settings) -> None:
    mark = _mark_path(ref, owner, settings)
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(str(size))


def _touch(path: Path) -> None:
    # Свежее время файла — уборка брошенных кадров считает возраст по нему, и
    # кадр, который только что прислали или приложили, она не тронет.
    try:
        os.utime(path)
    except OSError:
        pass


def save_upload(raw: bytes, settings: Settings, *, owner: int | None = None) -> str:
    """Положить кадр и вернуть ссылку на него. Не JPEG, пусто, велико — отказ.

    `owner` — чат, приславший кадр: ему ставится метка, и по ней же считается
    квота (`UploadQuotaError`). Без `owner` кладут только сиды и макеты.
    """
    if not raw:
        raise ValidationError("Кадр пустой")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError(f"Кадр больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
    if not raw.startswith(JPEG_MAGIC):
        raise ValidationError("Кадр не похож на JPEG")
    _check_decodes(raw)
    ref = UPLOAD_PREFIX + hashlib.sha256(raw).hexdigest()[:32]
    path = _path(ref, settings)
    if owner is not None:
        if _mark_path(ref, owner, settings).is_file() and path.is_file():
            # Повтор своего кадра (досылка, оборванный ответ) — не новый кадр.
            _touch(path)
            return ref
        _check_quota(owner, len(raw), settings)
    _store(raw, path)
    if owner is not None:
        _mark(ref, owner, len(raw), settings)
    return ref


def _store(raw: bytes, path: Path) -> None:
    if path.is_file():
        _touch(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Временный файл рядом и замена: оборванная запись не оставит полкадра под
    # ссылкой, которую уже можно приложить к записи.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def upload_file(ref: str, settings: Settings) -> Path | None:
    """Файл кадра по ссылке. Чужая ссылка — отказ, пропавший файл — `None`."""
    path = _path(ref, settings)
    return path if path.is_file() else None


def own_upload(ref: str, owner: int, settings: Settings) -> Path | None:
    """Файл кадра, если его прислал этот чат; иначе `None` — как у пропавшего.

    Чужой и пропавший кадр неотличимы снаружи: иначе ответ подсказывал бы,
    присылал ли кто-нибудь такой снимок. Свой кадр освежается — уборка не
    снимет его, пока его прикладывают.
    """
    path = upload_file(ref, settings)
    if path is None or not _mark_path(ref, owner, settings).is_file():
        return None
    _touch(path)
    return path
