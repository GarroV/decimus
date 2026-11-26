"""Prepare RU/EN documents once, retaining the inspection and sent-letter history."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path

from src.db import document_cache, queries
from src.db.errors import DbError
from src.db.models import InspectionDetail
from src.db.reach import Reach

from . import current_pdf, letters, localized
from .errors import ReportError

logger = logging.getLogger(__name__)
PREPARED_LANGS = ("ru", "en")


def letter(
    detail: InspectionDetail,
    *,
    lang: str | None,
    papers: letters.Papers,
    reach: Reach,
    template: int | None = None,
    bodies: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, object]:
    """Return a prepared draft; a changed source or template creates another version."""
    language = letters._lang(detail, lang)
    letters.refuse_uploaded(detail)
    template = letters._template(template)
    edition, _ = letters._methodology(detail.inspection.checklist_version, papers)
    fallback = letters.current_edition(detail, papers)
    edition_hashes = {
        str(folder): {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.iterdir()
            if path.is_file()
        }
        for folder in (edition, fallback)
        if folder is not None
    }
    source = json.dumps(
        {
            "source": localized.fingerprint(detail),
            "template": template,
            "bodies": bodies or {},
            "engine": hashlib.sha256(letters.REPORT_SCRIPT.read_bytes()).hexdigest(),
            "adapter": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "letter_adapter": hashlib.sha256(Path(letters.__file__).read_bytes()).hexdigest(),
            "editions": edition_hashes,
        },
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    cached = document_cache.load(
        detail.inspection.id, lang=language, kind="letter", fingerprint=fingerprint, reach=reach
    )
    if cached is not None:
        return cached
    result = letters.build(
        localized.detail_in(detail, lang=language, reach=reach),
        lang=language,
        papers=papers,
        template=template,
        bodies=bodies,
    )
    document_cache.save(
        detail.inspection.id,
        lang=language,
        kind="letter",
        fingerprint=fingerprint,
        payload=result,
        reach=reach,
    )
    return result


def prepare(inspection_id: str, *, reach: Reach) -> dict[str, str]:
    """Prepare both versions after acceptance; failures stay visible and are retryable."""
    detail = queries.get_inspection(inspection_id, reach=reach, include_on_review=True)
    if detail is None:
        raise ReportError("Проверка недоступна для подготовки документов")
    if detail.inspection.is_legacy:
        return {}
    from src.db import mailing_templates
    from src.domain.tenants import HQ_TENANT

    try:
        bodies = mailing_templates.bodies() if detail.inspection.tenant_code == HQ_TENANT else {}
    except DbError:
        logger.warning("Шаблоны письма недоступны, используются встроенные")
        bodies = {}
    failures: dict[str, str] = {}
    for language in PREPARED_LANGS:
        try:
            current_pdf.ensure_report(detail, reach=reach, lang=language)
        except (DbError, ReportError, OSError) as exc:
            logger.warning(
                "Документы %s проверки %s не подготовлены: %s",
                language,
                inspection_id,
                type(exc).__name__,
            )
            failures[language] = str(exc)
        try:
            letter(detail, lang=language, papers=letters.sources(), reach=reach, bodies=bodies)
        except (DbError, ReportError, OSError) as exc:
            logger.warning(
                "Письмо %s проверки %s не подготовлено: %s",
                language,
                inspection_id,
                type(exc).__name__,
            )
            failures[language] = str(exc)
    return failures
