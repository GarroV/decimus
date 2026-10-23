"""Ужатый кадр из base64 приложен, но ответ говорит о нём прямо (#1196).

Claude ужимает снимок до миниатюры, чтобы напечатать его base64 в аргумент, и в PDF
партнёру на 560 px не читаются этикетки и сроки. Запрещать мелкий кадр нельзя —
запись без кадра хуже (D309), — а молча принимать его значило бы потерять качество
отчёта незаметно для всех.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from PIL import Image

from src.mcp import imports
from src.mcp.photo_quality import LOW_RES_LONG_SIDE, low_resolution_warning


def _jpeg(ширина: int, высота: int) -> bytes:
    буфер = io.BytesIO()
    Image.new("RGB", (ширина, высота), (200, 120, 40)).save(буфер, "JPEG")
    return буфер.getvalue()


def test_миниатюра_как_у_ужатых_claude_предупреждена_с_размером() -> None:
    предупреждение = low_resolution_warning(_jpeg(420, 560))

    assert предупреждение is not None
    assert предупреждение.startswith("low_resolution")
    assert "420×560" in предупреждение
    assert "local_attach_photos" in предупреждение and "import_upload_photos" in предупреждение


def test_нормальный_снимок_без_предупреждения() -> None:
    assert low_resolution_warning(_jpeg(LOW_RES_LONG_SIDE, 750)) is None


def test_нечитаемая_картинка_не_судится() -> None:
    assert low_resolution_warning(b"not an image") is None


def test_ответ_инструмента_несёт_предупреждение(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: двери базы и хранилища подменены — проверяется только проводка ответа.
    увидено: dict[str, Any] = {}
    monkeypatch.setattr(imports, "_only_import", lambda *_a, **_k: None)
    monkeypatch.setattr(imports, "_photo_storage", lambda: object())
    monkeypatch.setattr("src.db.imports.add_photo", lambda *_a, **_k: None)

    class _Без:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(imports, "_db", lambda: _Без())

    def вид(_ident: str, **kw: Any) -> dict[str, object]:
        увидено.update(kw)
        return {}

    monkeypatch.setattr(imports, "_view", вид)

    # Act
    imports.import_add_photo(
        tenant="HQ",
        store=None,  # type: ignore[arg-type]
        actor="t",
        inspection_id="33333333-3333-3333-3333-333333333333",
        n=1,
        image_base64=base64.b64encode(_jpeg(420, 560)).decode(),
        mime="image/jpeg",
    )

    # Assert
    assert [w.split(":")[0] for w in увидено["warnings"]] == ["low_resolution"]
