"""Видимый штамп на кадре проверки: когда, где, кто снял (D619, D621).

Штамп вшивается в сохранённый файл на сервере, при сжатии кадра
(`previews.make_preview`), и оригинала без него не остаётся (D250, D253).
Текст принят владельцем: `ДД.ММ.ГГГГ ЧЧ:ММ · пиццерия · кто снял`, правый
нижний угол, мелко, на полупрозрачной тёмной подложке.

Время местное для страны пиццерии. Часовой пояс нигде в справочнике не
хранится, поэтому берётся из базы часовых поясов системы (`zone.tab`): у страны
один пояс — он; поясов несколько, но в этот момент они показывают одно время
(Кипр, Узбекистан), — первый; иначе пояс неоднозначен, и штамп честно идёт по
UTC с пометкой «UTC» в конце — молча подставленное чужое время хуже названного.

Кадры исторической загрузки (`origin = 'legacy'`, D332) штампа не получают:
сегодняшняя дата на кадре старого отчёта была бы ложью. Решает вызывающий —
он просто не просит штамп.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Высота шрифта штампа — доля ширины кадра (принято на макете, D621).
FONT_SHARE = 0.018

#: Меньше этого штамп не читается даже на маленьком кадре.
MIN_FONT_PX = 11

#: Поля подложки вокруг текста и отступ штампа от края — доли высоты шрифта.
_PAD_SHARE = 0.4
_MARGIN_SHARE = 0.8

#: Подложка: тёмная, прозрачность около 60% (RGBA).
_BACK_RGBA = (0, 0, 0, 150)
_TEXT_RGBA = (255, 255, 255, 255)

_SEPARATOR = " · "
_UTC_MARK = " UTC"

_FONT_PATH = Path(__file__).resolve().parents[2] / "engine" / "assets" / "fonts" / "DejaVuSans.ttf"
_ZONE_TAB = "zone.tab"


@dataclass(frozen=True)
class StampContext:
    """Что на штампе, кроме времени: пиццерия, проверяющий, страна (для пояса)."""

    unit_name: str
    auditor: str
    country: str | None


@lru_cache(maxsize=64)
def _zone_names(country: str) -> tuple[str, ...]:
    """Пояса страны из `zone.tab` базы часовых поясов; пусто, если файла нет."""
    for корень in zoneinfo.TZPATH:
        путь = Path(корень) / _ZONE_TAB
        if not путь.is_file():
            continue
        names: list[str] = []
        for строка in путь.read_text(encoding="utf-8").splitlines():
            поля = строка.split("\t")
            if len(поля) >= 3 and not строка.startswith("#") and поля[0] == country:
                names.append(поля[2])
        return tuple(names)
    return ()


def local_zone(country: str | None, moment: datetime) -> tzinfo | None:
    """Местный пояс страны на момент штампа; `None` — однозначного нет (штамп по UTC)."""
    if not country:
        return None
    names = _zone_names(country)
    try:
        zones = [zoneinfo.ZoneInfo(n) for n in names]
    except zoneinfo.ZoneInfoNotFoundError:
        return None
    if not zones:
        return None
    offsets = {moment.astimezone(z).utcoffset() for z in zones}
    return zones[0] if len(offsets) == 1 else None


def stamp_text(moment: datetime, context: StampContext) -> str:
    """Текст штампа. `moment` — осведомлённое время; пустое поле из штампа выпадает."""
    zone = local_zone(context.country, moment)
    local = moment.astimezone(zone if zone is not None else UTC)
    parts: list[str] = [local.strftime("%d.%m.%Y %H:%M") + ("" if zone is not None else _UTC_MARK)]
    parts.extend(x for x in (context.unit_name.strip(), context.auditor.strip()) if x)
    return _SEPARATOR.join(parts)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size)


def stamp_image(image: Image.Image, text: str) -> Image.Image:
    """Кадр с текстом в правом нижнем углу; исходный объект не меняется.

    Размер шрифта — доля ширины кадра. Слишком длинный текст ужимается, чтобы
    не выходить за кадр: штамп важнее ровного размера.
    """
    width, height = image.size
    size = max(MIN_FONT_PX, round(width * FONT_SHARE))
    font = _font(size)
    pad = max(2, round(size * _PAD_SHARE))
    margin = round(size * _MARGIN_SHARE)
    while size > MIN_FONT_PX and font.getlength(text) + 2 * pad + margin > width:
        size -= 1
        font = _font(size)
        pad = max(2, round(size * _PAD_SHARE))
        margin = round(size * _MARGIN_SHARE)
    left, top, right, bottom = font.getbbox(text)
    text_w, text_h = right - left, bottom - top
    box_w, box_h = text_w + 2 * pad, text_h + 2 * pad
    x1 = max(0, width - margin - box_w)
    y1 = max(0, height - margin - box_h)
    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle((x1, y1, x1 + box_w, y1 + box_h), fill=_BACK_RGBA)
    draw.text((x1 + pad - left, y1 + pad - top), text, font=font, fill=_TEXT_RGBA)
    return Image.alpha_composite(base, layer).convert("RGB")
