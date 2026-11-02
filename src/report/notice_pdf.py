"""PDF предписания по проверке: текст шаблона, таблица нарушений, приложение с фото (шаг 3).

Рендерер — WeasyPrint (D009), шрифт с кириллицей — тот же, что у отчёта
(`engine/assets/fonts`, читается по пути: движок не импортируется). Документ
английский всегда (D601). Текст шапки и тела приходит готовым: его собирает веб из
шаблона вида `document` (`mailing_templates`), второго хранилища шаблонов здесь нет.
Разметка отчёта и этого документа общей не бывает намеренно: у отчёта свой движок и
своя вёрстка, а предписание — письмо с таблицей.

Сборка не пересчитывает ничего: нарушения, формулировки и сроки лежат в
`prescription_findings` как их согласовали; фото берутся из хранилища теми же
сжатыми копиями, что показывает админка (`db.previews`). Кадр, которого нет в
хранилище, не пропадает молча: на его месте в приложении стоит видимая отметка.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image

from ..db import previews
from ..db.errors import DbError
from ..db.prescriptions import NoticeFinding
from ..db.reach import Reach
from .errors import PdfNotBuilt, ReportError

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parents[2] / "engine" / "assets" / "fonts"
FONT_FAMILY = "Audit Sans"
#: Длинная сторона кадра в документе, px: приложение не должно весить как архив.
PHOTO_MAX_SIDE = 1100
PHOTO_QUALITY = 78
PHOTO_MISSING = "[photo not available]"
NO_PHOTO = "No photo"
PDF_MIN_BYTES = 1000

_CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 7pt; color: #6F6880; } }
body { font-family: "Audit Sans", "DejaVu Sans", Arial, sans-serif; font-size: 10pt;
       line-height: 1.35; color: #23202B; }
h1 { font-size: 15pt; margin: 4mm 0 2mm 0; color: #23202B; }
h2 { font-size: 11.5pt; margin: 5mm 0 1.5mm 0; }
p { margin: 0 0 3mm 0; }
table.t { width: 100%; border-collapse: collapse; margin: 1mm 0 4mm 0; font-size: 9pt; }
table.t th { background: #F2F0F7; text-align: left; padding: 1.4mm 2mm;
  border: .6pt solid #BDB6CC; }
table.t td { padding: 1.4mm 2mm; border: .6pt solid #BDB6CC; vertical-align: top; }
table.t tr { page-break-inside: avoid; }
.pagebreak { page-break-after: always; }
.item { margin: 0 0 4mm 0; page-break-inside: avoid; }
.item .cap { font-size: 9pt; margin-bottom: 1mm; }
.item img { max-width: 80mm; max-height: 70mm; margin: 0 2mm 2mm 0; border: .6pt solid #BDB6CC; }
.miss { display: inline-block; padding: 6mm 4mm; margin: 0 2mm 2mm 0; color: #A81E1E;
        border: .8pt dashed #D08A8A; font-size: 9pt; }
.nophoto { color: #6F6880; font-size: 9pt; }
"""


@dataclass(frozen=True)
class NoticeDocument:
    """Всё, что нужно документу: уже прочитанное, без обращений к базе."""

    #: Шапка и тело — шаблон документа с подставленными фактами (простой текст).
    heading: str
    body: str
    findings: tuple[NoticeFinding, ...]
    #: Идентификатор строки нарушения → кадры (байты сжатых копий).
    photos: Mapping[str, Sequence[bytes]]
    #: Идентификатор строки нарушения → сколько кадров показать нечем.
    photos_missing: Mapping[str, int]


def _term_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _photo_uri(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
            image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=PHOTO_QUALITY, optimize=True)
    except OSError as exc:
        raise PdfNotBuilt(
            f"Кадр предписания не читается как изображение ({type(exc).__name__})"
        ) from exc
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def _findings_table(doc: NoticeDocument) -> str:
    rows = "".join(
        f"<tr><td>{escape(f.object_name)}</td><td>{escape(f.clause)}</td>"
        f"<td>{escape(f.description or '—')}</td><td>{_term_date(f.due_on)}</td></tr>"
        for f in doc.findings
    )
    return (
        '<table class="t"><tr><th>Restaurant/premises</th><th>The identified failure</th>'
        "<th>Description of the failure</th><th>The remedy term</th></tr>" + rows + "</table>"
    )


def _appendix(doc: NoticeDocument) -> str:
    """Фото по каждому нарушению с подписью-описанием, сгруппированы по объекту."""
    parts: list[str] = []
    objects = list(dict.fromkeys(f.object_name for f in doc.findings))
    number = 0
    for name in objects:
        parts.append(f"<h2>{escape(name)}</h2>")
        for f in (x for x in doc.findings if x.object_name == name):
            number += 1
            caption = f.description or f.clause
            shots = "".join(
                f'<img src="{_photo_uri(data)}">' for data in doc.photos.get(f.id, ())
            ) + "".join(
                f'<span class="miss">{PHOTO_MISSING}</span>'
                for _ in range(doc.photos_missing.get(f.id, 0))
            )
            if not shots:
                shots = f'<span class="nophoto">{NO_PHOTO}</span>'
            parts.append(
                f'<div class="item"><div class="cap">{number}. {escape(f.clause)} — '
                f"{escape(caption)}</div>{shots}</div>"
            )
    return "\n".join(parts)


def _font_css() -> str:
    faces = []
    for file, weight in (("DejaVuSans.ttf", "normal"), ("DejaVuSans-Bold.ttf", "bold")):
        path = FONT_DIR / file
        if path.exists():
            faces.append(
                f'@font-face {{ font-family: "{FONT_FAMILY}"; font-weight: {weight}; '
                f'src: url("file://{quote(str(path))}"); }}'
            )
    return "\n".join(faces)


def _paragraphs(text: str) -> str:
    """Простой текст шаблона: абзацы через пустую строку, переводы строк — `<br>`."""
    return "\n".join(
        f"<p>{escape(block.strip()).replace(chr(10), '<br>')}</p>"
        for block in re.split(r"\n\s*\n", text.strip())
        if block.strip()
    )


def render_html(doc: NoticeDocument) -> str:
    """HTML документа: шапка и текст шаблона, таблица нарушений, приложение с фото."""
    body = "\n".join(
        (
            f"<h1>{escape(doc.heading)}</h1>",
            _paragraphs(doc.body),
            _findings_table(doc),
            '<div class="pagebreak"></div>',
            "<h1>Appendix 1</h1>",
            _appendix(doc),
        )
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Notice</title>'
        f"<style>{_font_css()}\n{_CSS}</style></head><body>{body}</body></html>"
    )


def build_pdf(doc: NoticeDocument) -> bytes:
    """PDF документа. Не собрался или не PDF — `PdfNotBuilt`, а не пустые байты."""
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except Exception as exc:  # системные библиотеки Pango могут отсутствовать
        raise PdfNotBuilt(f"Рендерер PDF недоступен: {type(exc).__name__}") from exc
    try:
        data: Any = HTML(string=render_html(doc)).write_pdf()
    except ReportError:
        raise
    except Exception as exc:
        raise PdfNotBuilt(f"Не удалось собрать PDF предписания: {type(exc).__name__}") from exc
    if not isinstance(data, bytes) or len(data) < PDF_MIN_BYTES or not data.startswith(b"%PDF-"):
        raise PdfNotBuilt("Рендерер отчитался об успехе, но предписания как PDF нет")
    return data


def _photos(
    findings: Sequence[NoticeFinding], *, reach: Reach, storage: previews.PreviewReader | None
) -> tuple[dict[str, list[bytes]], dict[str, int]]:
    """Кадры включённых нарушений: байты копий и число кадров, которые показать нечем."""
    shots: dict[str, list[bytes]] = {}
    missing: dict[str, int] = {}
    by_inspection: dict[str, dict[str, previews.FindingShots]] = {}
    for f in findings:
        if f.inspection_id not in by_inspection:
            by_inspection[f.inspection_id] = previews.finding_previews(f.inspection_id, reach=reach)
        known = by_inspection[f.inspection_id].get(f.finding_id)
        if known is None:
            continue
        missing[f.id] = known.missing
        for photo_id in known.shown:
            try:
                data = previews.preview_bytes(
                    f.inspection_id, photo_id, reach=reach, storage=storage
                )
            except (DbError, OSError) as exc:
                logger.warning("кадр %s предписания не прочитан: %s", photo_id, exc)
                data = None
            if data:
                shots.setdefault(f.id, []).append(data)
            else:
                missing[f.id] = missing.get(f.id, 0) + 1
    return shots, missing


def photos_of(
    findings: Sequence[NoticeFinding],
    *,
    reach: Reach,
    storage: previews.PreviewReader | None = None,
) -> tuple[dict[str, list[bytes]], dict[str, int]]:
    """Кадры включённых нарушений: байты копий и число кадров, которые показать нечем."""
    return _photos(tuple(f for f in findings if f.included), reach=reach, storage=storage)
