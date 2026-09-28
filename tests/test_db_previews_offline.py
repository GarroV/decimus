"""Сжатая копия кадра (D218): достаточно, чтобы было видно, и не больше."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.db.errors import StorageError
from src.db.previews import PREVIEW_MAX_SIDE, make_preview
from src.db.storage import key_of_uri, preview_key


def _кадр(ширина: int, высота: int, *, поворот: int | None = None) -> bytes:
    картинка = Image.effect_noise((ширина, высота), 64).convert("RGB")
    выход = io.BytesIO()
    exif = Image.Exif()
    if поворот is not None:
        exif[0x0112] = поворот
    картинка.save(выход, format="JPEG", quality=95, exif=exif.tobytes())
    return выход.getvalue()


def test_большой_кадр_ужимается_до_длинной_стороны_и_становится_меньше() -> None:
    исходный = _кадр(4000, 3000)
    копия = make_preview(исходный)
    with Image.open(io.BytesIO(копия)) as к:
        assert max(к.size) == PREVIEW_MAX_SIDE
        assert к.format == "JPEG"
    assert len(копия) < len(исходный)


def test_маленький_кадр_не_растягивается() -> None:
    with Image.open(io.BytesIO(make_preview(_кадр(800, 600)))) as к:
        assert к.size == (800, 600)


def test_поворот_телефона_применяется_до_сжатия() -> None:
    # Метка 6 — «повернуть на 90°»: лежащий на боку кадр 4000×3000 встаёт.
    with Image.open(io.BytesIO(make_preview(_кадр(4000, 3000, поворот=6)))) as к:
        assert к.size[1] > к.size[0]


def test_не_картинка_отказ_а_не_пустые_байты() -> None:
    with pytest.raises(StorageError):
        make_preview(b"not an image at all")


def test_ключ_копии_отдельный_от_оригинала_и_читается_обратно() -> None:
    ключ = preview_key("i-1", "p-1")
    assert ключ == "inspections/i-1/previews/p-1.jpg"
    assert key_of_uri(f"s3://inspection-frames/{ключ}") == ключ
    with pytest.raises(StorageError):
        key_of_uri("https://storage.example/inspection-frames/key")
