"""PDF предписания по проверке: таблица визитов, таблица нарушений, приложение с фото (шаг 3).

Рендерер — WeasyPrint (D009), шрифт с кириллицей — тот же, что у отчёта
(`engine/assets/fonts`, читается по пути: движок не импортируется). Документ
английский всегда (D601). Разметка отчёта и этого документа общей не бывает
намеренно: у отчёта свой движок и своя вёрстка, а предписание — письмо с таблицами.

Сборка не пересчитывает ничего: нарушения, формулировки и сроки лежат в
`prescription_findings` как их согласовали; фото берутся из хранилища теми же
сжатыми копиями, что показывает админка (`db.previews`). Кадр, которого нет в
хранилище, не пропадает молча: на его месте в приложении стоит видимая отметка.
"""

from __future__ import annotations

import base64
import io
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image

from ..db import country_contracts, mail_templates, previews
from ..db.errors import DbError
from ..db.prescription_notice import Visit, visits
from ..db.prescriptions import NoticeFinding, Prescription
from ..db.reach import Reach
from ..domain.geo import COUNTRIES
from .errors import PdfNotBuilt, ReportError
from .notice_template import (
    BUILTIN_PRESCRIPTION_INSPECTION,
    MISSING_AGREEMENT,
    MISSING_FRANCHISEE,
    render_body,
)

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parents[2] / "engine" / "assets" / "fonts"
FONT_FAMILY = "Audit Sans"
#: Длинная сторона кадра в документе, px: приложение не должно весить как архив.
PHOTO_MAX_SIDE = 1100
PHOTO_QUALITY = 78
PHOTO_MISSING = "[photo not available]"
NO_PHOTO = "No photo"
PDF_MIN_BYTES = 1000

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip

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

    on: date
    due_on: date
    country: str
    template: str
    franchisee: country_contracts.Contract | None
    visits: tuple[Visit, ...]
    findings: tuple[NoticeFinding, ...]
    #: Идентификатор строки нарушения → кадры (байты сжатых копий).
    photos: Mapping[str, Sequence[bytes]]
    #: Идентификатор строки нарушения → сколько кадров показать нечем.
    photos_missing: Mapping[str, int]


def _long_date(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _visit_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _term_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _franchisee(contract: country_contracts.Contract | None) -> tuple[str, str]:
    """Блок «Франчайзи» и короткое имя — из карточки страны; нет сведений — заглушка."""
    if contract is None or not contract.legal_name:
        name = MISSING_FRANCHISEE
    else:
        name = contract.legal_name
    lines = [name]
    if contract is not None:
        if contract.registration_country:
            lines.append(f"Country of registration: {contract.registration_country}")
        if contract.company_number:
            lines.append(f"Company number: {contract.company_number}")
        if contract.address:
            lines.append(f"Address: {contract.address}")
    return "\n".join(lines), name


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


def _visits_table(doc: NoticeDocument) -> str:
    rows = "".join(
        f"<tr><td>{escape(v.object_name)}</td><td>{escape(v.address or '—')}</td>"
        f"<td>{_visit_date(v.visited_on)}</td><td>{escape(v.visitor or '—')}</td></tr>"
        for v in doc.visits
    )
    return (
        '<table class="t"><tr><th>Restaurant/premises</th><th>Address</th>'
        "<th>Date of the visit</th><th>Name of the visitor</th></tr>" + rows + "</table>"
    )


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


def render_html(doc: NoticeDocument) -> str:
    """HTML документа: шаблон с подставленными значениями и тремя блоками."""
    block, name = _franchisee(doc.franchisee)
    values = {
        "date": _long_date(doc.on),
        "country": COUNTRIES.get(doc.country, {}).get("en", doc.country),
        "franchisee_name": name,
        "franchisee_block": block,
        "agreement": (doc.franchisee.agreement if doc.franchisee else "") or MISSING_AGREEMENT,
        "due_on": _term_date(doc.due_on),
    }
    blocks = {
        "visits_table": _visits_table(doc),
        "findings_table": _findings_table(doc),
        "appendix": _appendix(doc),
    }
    body = render_body(doc.template, values=values, blocks=blocks)
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


def document_of(
    p: Prescription,
    *,
    reach: Reach,
    on: date,
    storage: previews.PreviewReader | None = None,
) -> NoticeDocument:
    """Собрать данные документа по предписанию: шаблон его версии, договор страны, визиты, кадры."""
    if not p.has_document:
        raise ReportError("Предписание вписано руками — документа по шаблону у него нет")
    version = mail_templates.get(p.template_version_id)
    template = version.body if version is not None else BUILTIN_PRESCRIPTION_INSPECTION
    contracts = country_contracts.read(p.country)
    franchisee = next((c for c in contracts if c.legal_name), contracts[0] if contracts else None)
    included = tuple(f for f in p.findings if f.included)
    bases = tuple(dict.fromkeys(f.inspection_id for f in included))
    shots, missing = _photos(included, reach=reach, storage=storage)
    return NoticeDocument(
        on=on,
        due_on=p.due_on,
        country=p.country,
        template=template,
        franchisee=franchisee,
        visits=visits(bases, reach=reach),
        findings=included,
        photos=shots,
        photos_missing=missing,
    )


def build_for(
    p: Prescription,
    *,
    reach: Reach,
    on: date,
    storage: previews.PreviewReader | None = None,
) -> bytes:
    """PDF предписания: прочитать всё нужное и собрать. Дата — согласования, до него сегодня."""
    return build_pdf(document_of(p, reach=reach, on=on, storage=storage))
