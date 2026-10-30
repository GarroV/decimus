"""Актуальный сохранённый PDF проверки для веба, почты и повторной выдачи ботом.

Перед выдачей проверяет полный снимок базы, кадров и реальных генераторов.
Старые PDF остаются историей; legacy выдаётся исходным и не пересчитывается.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from src.db import busy_lock, previews, queries, reports
from src.db.config import load_storage_settings
from src.db.errors import StorageError
from src.db.models import InspectionDetail, InspectionRow
from src.db.reach import Reach
from src.db.storage import S3PhotoStorage, key_of_uri

from . import detail_pdf
from .letters import AUDIT_SCRIPT, REPORT_SCRIPT, state_json
from .letters import sources as letter_sources


def report_name(head: InspectionRow) -> str:
    """Единое безопасное имя PDF для скачивания, вложения и повторной выдачи."""
    unit = "".join(char for char in head.unit_name if char.isprintable() and char not in '"\\/')
    return f"{unit.strip() or 'inspection'} {head.inspection_date}.pdf"


def ensure_report(detail: InspectionDetail, *, reach: Reach) -> reports.ReportRef:
    """Актуальный PDF для скачивания и почты, с сохранением прежних версий.

    Снимок перечитывается в охвате вызывающего, а перед публикацией проверяется
    повторно. Отпечаток данных и неизменяемых ссылок кадров хранится в ключе
    объекта; второй процесс использует тот же PDF. Legacy не пересчитывается.
    Отказ кадра, сборки или замка не подменяется устаревшим отчётом.
    """
    head = detail.inspection
    current = queries.get_inspection(head.id, reach=reach, include_on_review=True)
    if current is None:
        raise StorageError("Проверка не найдена или недоступна для актуального PDF")
    ref = reports.latest_report(head.id, reach=reach)
    if current.inspection.is_legacy:
        if ref is None:
            raise StorageError("Сохранённого отчёта исторической проверки нет")
        return ref
    shots = previews.report_photos(head.id, reach=reach)
    fingerprint = _report_fingerprint(current, shots)
    if ref is not None and f"/reports/{fingerprint}/" in ref.storage_path:
        return ref
    hold = busy_lock.try_hold(busy_lock.REPORT_REFRESH, head.id)
    if not hold.acquired or not hold.shared:
        hold.release()
        raise StorageError("Актуальный PDF уже собирается или замок недоступен — повторите запрос")
    try:
        # Пока брали замок, другой процесс мог уже закончить тот же снимок.
        ref = reports.latest_report(head.id, reach=reach)
        if ref is not None and f"/reports/{fingerprint}/" in ref.storage_path:
            return ref
        return _rebuild_report(current, shots, fingerprint=fingerprint, reach=reach)
    finally:
        hold.release()


def _rebuild_report(
    detail: InspectionDetail,
    shots: tuple[previews.ReportPhoto, ...],
    *,
    fingerprint: str,
    reach: Reach,
) -> reports.ReportRef:
    store = S3PhotoStorage(load_storage_settings(), fail_fast=True)
    photos: dict[int, list[bytes]] = {}
    info_photos: dict[str, list[bytes]] = {}
    for shot in shots:
        path = shot.storage_path or shot.preview_path
        if path is None:
            raise StorageError("Не все фотографии проверки загружены для актуального PDF")
        data = store.get(key_of_uri(path))
        if not data:
            raise StorageError("Фотография проверки не прочитана для актуального PDF")
        if shot.finding_n is not None:
            photos.setdefault(shot.finding_n, []).append(data)
        elif shot.info_code:
            info_photos.setdefault(shot.info_code, []).append(data)
        else:
            raise StorageError("Не определено место фотографии в актуальном PDF")
    data = detail_pdf.build_bytes(
        detail, lang=None, papers=letter_sources(), photos=photos, info_photos=info_photos
    )
    head = detail.inspection
    _assert_report_source(head.id, fingerprint=fingerprint, reach=reach)
    reports.upload_report(head.id, data=data, storage=store, source_fingerprint=fingerprint)
    # Смена источника во время загрузки оставляет снимок в истории, но запрещает
    # выдать его вызывающему. Следующий ensure проверит и заменит latest.
    _assert_report_source(head.id, fingerprint=fingerprint, reach=reach)
    updated = reports.latest_report(head.id, reach=reach)
    if updated is None or f"/reports/{fingerprint}/" not in updated.storage_path:
        raise StorageError("Актуальный PDF не сохранён — повторите запрос")
    return updated


def _assert_report_source(inspection_id: str, *, fingerprint: str, reach: Reach) -> None:
    current = queries.get_inspection(inspection_id, reach=reach, include_on_review=True)
    if (
        current is None
        or _report_fingerprint(current, previews.report_photos(inspection_id, reach=reach))
        != fingerprint
    ):
        raise StorageError("Проверка изменилась во время сборки PDF — повторите запрос")


def _report_fingerprint(detail: InspectionDetail, shots: tuple[previews.ReportPhoto, ...]) -> str:
    payload = {
        "detail": asdict(detail),
        # Фото и копии после загрузки неизменяемы (0004); замена создаёт новый
        # id/путь. Удалённый кадр исчезает из перечня, незагруженный меняет путь.
        "photos": [asdict(value) for value in shots],
        "generator": hashlib.sha256(REPORT_SCRIPT.read_bytes()).hexdigest(),
        "engine": hashlib.sha256(AUDIT_SCRIPT.read_bytes()).hexdigest(),
        "adapter": hashlib.sha256(Path(detail_pdf.__file__).read_bytes()).hexdigest(),
        "photo_adapter": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "state": hashlib.sha256(Path(state_json.__code__.co_filename).read_bytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
