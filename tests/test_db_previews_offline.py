"""Сжатая копия кадра (D219): достаточно, чтобы было видно, и не больше."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.db.errors import StorageError
from src.db.photos import _put_photo
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


class _Склад:
    def __init__(self) -> None:
        self.положено: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.положено[key] = data
        return f"s3://b/{key}"


def test_выгрузка_кадра_кладёт_один_сжатый_объект_и_обе_ссылки_на_него() -> None:
    склад = _Склад()
    исходный = _кадр(4000, 3000)

    storage_uri, preview_uri = _put_photo(склад, "i-1", "p-1", исходный)

    assert len(склад.положено) == 1
    assert storage_uri == preview_uri == "s3://b/inspections/i-1/p-1.jpg"
    (лежит,) = склад.положено.values()
    assert len(лежит) < len(исходный)
    with Image.open(io.BytesIO(лежит)) as к:
        assert max(к.size) == PREVIEW_MAX_SIDE


def test_нечитаемый_кадр_не_теряется_но_копии_не_получает() -> None:
    склад = _Склад()

    storage_uri, preview_uri = _put_photo(склад, "i-1", "p-1", b"not an image")

    assert склад.положено == {"inspections/i-1/p-1.jpg": b"not an image"}
    assert storage_uri == "s3://b/inspections/i-1/p-1.jpg"
    assert preview_uri is None
