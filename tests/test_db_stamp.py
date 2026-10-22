"""Видимый штамп на кадре (D619, D621): он есть, он верен, и его нет там, где не должно быть."""

from __future__ import annotations

import io
from datetime import UTC, datetime

from PIL import Image, ImageChops, ImageStat

from src.db.photos import _put_photo
from src.db.previews import make_preview
from src.db.stamp import FONT_SHARE, StampContext, stamp_text

#: 22.10.2026 21:30 UTC: в Грузии (UTC+4) уже 23-е, в Сербии (UTC+2) ещё 22-е.
_МОМЕНТ = datetime(2026, 10, 22, 21, 30, tzinfo=UTC)


def _кадр(ширина: int = 1200, высота: int = 800) -> bytes:
    картинка = Image.new("RGB", (ширина, высота), (200, 120, 60))
    выход = io.BytesIO()
    картинка.save(выход, format="JPEG", quality=95)
    return выход.getvalue()


def _открыть(данные: bytes) -> Image.Image:
    return Image.open(io.BytesIO(данные)).convert("RGB")


def _разница(a: Image.Image, b: Image.Image, рамка: tuple[int, int, int, int]) -> int:
    """Сумма отличий двух кадров в рамке; 0 — пиксели те же."""
    дельта = ImageChops.difference(a.crop(рамка), b.crop(рамка)).convert("L")
    return int(ImageStat.Stat(дельта).sum[0])


def test_штамп_меняет_правый_нижний_угол_и_не_трогает_левый_верхний() -> None:
    без = _открыть(make_preview(_кадр()))
    со = _открыть(make_preview(_кадр(), stamp="22.10.2026 21:30 · Пиццерия · Аудитор"))
    w, h = без.size
    assert _разница(без, со, (w // 2, h * 3 // 4, w, h)) > 0, "в правом нижнем углу штампа нет"
    assert _разница(без, со, (0, 0, w // 2, h // 2)) == 0, "штамп залез в левый верхний угол"


def test_размер_шрифта_идёт_от_ширины_кадра() -> None:
    без = _открыть(make_preview(_кадр(1200, 800)))
    со = _открыть(make_preview(_кадр(1200, 800), stamp="22.10.2026 21:30 · A"))
    # Строки с отличиями — высота подложки: она около высоты шрифта плюс поля.
    дельта = ImageChops.difference(без, со).convert("L").point(lambda v: 255 if v > 40 else 0)
    рамка = дельта.getbbox()
    assert рамка is not None
    высота = рамка[3] - рамка[1]
    assert 0.6 * FONT_SHARE * 1200 < высота < 3 * FONT_SHARE * 1200


def test_текст_штампа_собирается_из_полей_и_местного_времени() -> None:
    assert (
        stamp_text(_МОМЕНТ, StampContext("Тбилиси-1", "И. Иванов", "GE"))
        == "23.10.2026 01:30 · Тбилиси-1 · И. Иванов"
    )
    assert (
        stamp_text(_МОМЕНТ, StampContext("Белград-2", "И. Иванов", "RS"))
        == "22.10.2026 23:30 · Белград-2 · И. Иванов"
    )


def test_пустой_проверяющий_выпадает_из_штампа() -> None:
    assert stamp_text(_МОМЕНТ, StampContext("Тбилиси-1", "  ", "GE")) == (
        "23.10.2026 01:30 · Тбилиси-1"
    )


def test_страна_без_пояса_идёт_по_utc_с_пометкой() -> None:
    # Индонезия: четыре пояса с разным временем — местный не угадать.
    assert stamp_text(_МОМЕНТ, StampContext("Бали-1", "И", "ID")) == (
        "22.10.2026 21:30 UTC · Бали-1 · И"
    )
    assert stamp_text(_МОМЕНТ, StampContext("Точка", "И", None)).startswith("22.10.2026 21:30 UTC")


def test_страна_с_несколькими_поясами_одного_времени_идёт_по_местному() -> None:
    # Кипр: Никосия и Фамагуста показывают одно время.
    assert stamp_text(_МОМЕНТ, StampContext("Т", "", "CY")).startswith("23.10.2026 00:30 · ")


class _Склад:
    def __init__(self) -> None:
        self.лежит: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.лежит[key] = data
        return f"s3://b/{key}"


def test_выгрузка_кладёт_кадр_со_штампом_а_без_штампа_без() -> None:
    склад = _Склад()
    исходный = _кадр()
    _put_photo(склад, "i-1", "p-1", исходный, stamp="22.10.2026 21:30 · П · А")
    _put_photo(склад, "i-1", "p-2", исходный, stamp=None)
    со, без = (_открыть(данные) for данные in склад.лежит.values())
    w, h = со.size
    assert _разница(со, без, (w // 2, h * 3 // 4, w, h)) > 0
    assert _разница(со, без, (0, 0, w // 2, h // 2)) == 0


class _Курсор:
    """Курсор с одной заготовленной строкой: `(пиццерия, проверяющий, страна, происхождение)`."""

    def __init__(self, строка: tuple[str, str, str | None, str] | None) -> None:
        self._строка = строка

    def execute(self, sql: str, params: tuple[str]) -> None:
        self.запрос = (sql, params)

    def fetchone(self) -> tuple[str, str, str | None, str] | None:
        return self._строка


def test_историческая_загрузка_штампа_не_получает() -> None:
    from src.db.photos import stamp_for

    legacy = _Курсор(("Тбилиси-1", "И. Иванов", "GE", "legacy"))
    assert stamp_for(legacy, "i-1", _МОМЕНТ) is None  # type: ignore[arg-type]
    загрузка = _Курсор(("Тбилиси-1", "И. Иванов", "GE", "import"))
    assert stamp_for(загрузка, "i-1", _МОМЕНТ) is None  # type: ignore[arg-type]


def test_живая_проверка_штамп_получает() -> None:
    from src.db.photos import stamp_for

    for происхождение in ("field",):
        курсор = _Курсор(("Тбилиси-1", "И. Иванов", "GE", происхождение))
        assert stamp_for(курсор, "i-1", _МОМЕНТ) == "23.10.2026 01:30 · Тбилиси-1 · И. Иванов"  # type: ignore[arg-type]
