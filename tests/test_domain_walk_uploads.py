"""D312: кадры мини-аппа в папке состояния, признак сдачи, сведения без повторного вопроса.

Ссылка на кадр собирается в путь на сервере — значит, это граница доверия:
ни один символ пути не должен прийти из запроса. Признак сдачи читают две
поверхности, и испорченные заметки не должны открывать правку сданного.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from src.bot import photos
from src.bot.info import fields_to_ask
from src.domain import check_environment, set_info, start_inspection
from src.domain.errors import DomainError, ValidationError
from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME, handed_over
from src.domain.uploads import MAX_UPLOAD_BYTES, is_upload_ref, save_upload, upload_file


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (120, 130, 140)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = _jpeg()


def test_кадр_ложится_по_отпечатку_и_повтор_не_плодит_файлы(domain_env: Path) -> None:
    settings = check_environment()

    ref = save_upload(JPEG, settings)

    assert is_upload_ref(ref)
    assert save_upload(JPEG, settings) == ref, "повтор загрузки на плохой связи — тот же кадр"
    path = upload_file(ref, settings)
    assert path is not None and path.read_bytes() == JPEG
    assert path.is_relative_to(domain_env / "uploads")


@pytest.mark.parametrize(
    "raw",
    [b"", b"GIF89a....", JPEG + b"\x00" * MAX_UPLOAD_BYTES, b"\xff\xd8\xff" + b"\x00" * 64],
    ids=["пусто", "не-jpeg", "слишком-большой", "только-заголовок"],
)
def test_не_кадр_не_сохраняется(domain_env: Path, raw: bytes) -> None:
    with pytest.raises(ValidationError):
        save_upload(raw, check_environment())


@pytest.mark.parametrize(
    "ref",
    ["walk:../../etc/passwd", "walk:" + "A" * 32, "photos/x.jpg", "walk:" + "0" * 31, "walk:"],
)
def test_чужая_ссылка_пути_не_даёт(domain_env: Path, ref: str) -> None:
    assert not is_upload_ref(ref)
    with pytest.raises(ValidationError):
        upload_file(ref, check_environment())


def test_бот_отдаёт_кадр_мини_аппа_той_же_дверью(domain_env: Path) -> None:
    ref = save_upload(JPEG, check_environment())

    assert asyncio.run(photos.fetch_bytes(None, ref)) == JPEG  # type: ignore[arg-type]
    пропавший = "walk:" + "f" * 32
    assert asyncio.run(photos.fetch_bytes(None, пропавший)) is None  # type: ignore[arg-type]


def _заметки(state: Path, chat_id: int, raw: object) -> None:
    folder = state / f"chat_{chat_id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / NOTES_FILE_NAME).write_text(json.dumps(raw), encoding="utf-8")


def test_признак_сдачи(domain_env: Path) -> None:
    assert handed_over(1) is False, "заметок нет — не сдана"
    _заметки(domain_env, 2, {HANDED_OVER_KEY: -1})
    _заметки(domain_env, 3, {HANDED_OVER_KEY: 0})
    _заметки(domain_env, 4, {"frames": []})

    assert handed_over(2) is False
    assert handed_over(3) is True, "ноль записей — законная сданная проверка"
    assert handed_over(4) is False


@pytest.mark.parametrize("raw", [{HANDED_OVER_KEY: "много"}, ["не", "объект"]])
def test_испорченные_заметки_не_открывают_правку(domain_env: Path, raw: object) -> None:
    _заметки(domain_env, 5, raw)
    with pytest.raises(DomainError):
        handed_over(5)


def test_заполненное_в_обходе_бот_не_спрашивает(domain_env: Path) -> None:
    start_inspection(9, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    до = [field.code for field, _ in fields_to_ask("ru", chat_id=9)]
    set_info(9, "INF06", "Перевесить график уборки")

    после = [field.code for field, _ in fields_to_ask("ru", chat_id=9)]

    assert "INF06" in до and "INF06" not in после
    assert len(после) == len(до) - 1
