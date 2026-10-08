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
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .errors import ValidationError

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


def is_upload_ref(ref: str) -> bool:
    """Ссылка ли это на кадр мини-аппа (а не идентификатор телеграма или путь)."""
    return _REF.match(ref) is not None


def _path(ref: str, settings: Settings) -> Path:
    hit = _REF.match(ref)
    if hit is None:
        raise ValidationError(f"«{ref}» не ссылка на кадр мини-аппа")
    digest = hit.group(1)
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


def save_upload(raw: bytes, settings: Settings) -> str:
    """Положить кадр и вернуть ссылку на него. Не JPEG, пусто, велико — отказ."""
    if not raw:
        raise ValidationError("Кадр пустой")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError(f"Кадр больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
    if not raw.startswith(JPEG_MAGIC):
        raise ValidationError("Кадр не похож на JPEG")
    _check_decodes(raw)
    ref = UPLOAD_PREFIX + hashlib.sha256(raw).hexdigest()[:32]
    path = _path(ref, settings)
    if path.is_file():
        return ref
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
    return ref


def upload_file(ref: str, settings: Settings) -> Path | None:
    """Файл кадра по ссылке. Чужая ссылка — отказ, пропавший файл — `None`."""
    path = _path(ref, settings)
    return path if path.is_file() else None
