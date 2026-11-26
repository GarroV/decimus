"""Language-specific document text; the recorded inspection is never overwritten."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

from src.db import document_cache
from src.db.models import InspectionDetail
from src.db.reach import Reach
from src.recognize.errors import RecognizeError
from src.recognize.translate import translate_texts

from .errors import ReportError


def fingerprint(detail: InspectionDetail) -> str:
    payload = json.dumps(asdict(detail), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def detail_in(detail: InspectionDetail, *, lang: str, reach: Reach) -> InspectionDetail:
    """Translate only display text; codes, measurements, scores and source words stay intact."""
    head = detail.inspection
    if head.is_legacy:
        return detail
    # Native-language output needs no model call or translation cache.
    if (
        all(f.lang == lang for f in detail.findings)
        and (head.speech_lang or head.report_lang) == lang
    ):
        return detail
    key = fingerprint(detail)
    cached = document_cache.load(
        head.id, lang=lang, kind="translation", fingerprint=key, reach=reach
    )
    if cached is None:
        sources = [
            value for f in detail.findings if f.lang != lang for value in (f.text, f.comment)
        ]
        if (head.speech_lang or head.report_lang) != lang:
            sources.extend(row.text for row in detail.info)
        unique = list(
            dict.fromkeys(
                value for value in sources if value and any(char.isalpha() for char in value)
            )
        )
        memo: dict[str, str] = {}
        try:
            for start in range(0, len(unique), 20):
                batch = unique[start : start + 20]
                memo.update(zip(batch, translate_texts(batch, lang=lang), strict=True))
        except RecognizeError as exc:
            raise ReportError("Перевод документа не подготовлен; повторите запрос") from exc

        def translate(text: str | None) -> str | None:
            if not text or not any(char.isalpha() for char in text):
                return text
            return memo[text]

        cached = {
            "findings": {
                f.id: {"text": translate(f.text), "comment": translate(f.comment)}
                for f in detail.findings
                if f.lang != lang
            },
            "info": {row.code: translate(row.text) for row in detail.info}
            if (head.speech_lang or head.report_lang) != lang
            else {},
        }
        document_cache.save(
            head.id, lang=lang, kind="translation", fingerprint=key, payload=cached, reach=reach
        )
    findings = tuple(
        replace(f, lang=lang, **cached["findings"][f.id]) if f.id in cached["findings"] else f
        for f in detail.findings
    )
    info = tuple(replace(row, text=cached["info"].get(row.code, row.text)) for row in detail.info)
    return replace(detail, inspection=replace(head, speech_lang=lang), findings=findings, info=info)
