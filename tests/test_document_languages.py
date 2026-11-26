"""Language variants must preserve source text, reuse translations and never cross languages."""

from dataclasses import asdict, replace

import pytest
from test_web_app import карточка, шапка

from src.db.models import InfoRow
from src.db.reach import Reach
from src.recognize.errors import ModelUnavailable
from src.report import documents, localized
from src.report.errors import ReportError

REACH = Reach("HQ", None, None)


@pytest.fixture
def cache(monkeypatch):
    rows = {}

    def load(ident, *, lang, kind, fingerprint, reach):
        return rows.get((ident, lang, kind, fingerprint))

    def save(ident, *, lang, kind, fingerprint, payload, reach):
        rows[ident, lang, kind, fingerprint] = payload

    monkeypatch.setattr(localized.document_cache, "load", load)
    monkeypatch.setattr(localized.document_cache, "save", save)
    return rows


def test_translation_preserves_source_and_reuses_only_matching_snapshot(monkeypatch, cache):
    detail = карточка(replace(шапка(), report_lang="ru", speech_lang="ru"))
    detail = replace(
        detail,
        findings=(
            replace(detail.findings[0], lang="ru", text="Грязный стол", comment="Грязный стол"),
        ),
        info=(InfoRow("INF01", "2026-11-26"),),
    )
    source = asdict(detail)
    calls = []

    def translate(texts, *, lang):
        calls.append((texts, lang))
        return ["Dirty table" for text in texts]

    monkeypatch.setattr(localized, "translate_texts", translate)
    result = localized.detail_in(detail, lang="en", reach=REACH)
    assert result.findings[0].text == "Dirty table"
    assert result.findings[0].code == detail.findings[0].code
    assert result.inspection.pct == detail.inspection.pct
    assert result.info == detail.info
    assert asdict(detail) == source
    assert localized.detail_in(detail, lang="en", reach=REACH) == result
    assert calls == [(["Грязный стол"], "en")]
    changed = replace(detail, findings=(replace(detail.findings[0], comment="Другой факт"),))
    localized.detail_in(changed, lang="en", reach=REACH)
    assert len(calls) == 2


def test_translation_failure_never_caches_or_returns_original_as_english(monkeypatch, cache):
    detail = карточка(replace(шапка(), speech_lang="ru"))
    detail = replace(
        detail, findings=(replace(detail.findings[0], lang="ru", text="Грязный стол"),)
    )

    def fail(*args, **kwargs):
        raise ModelUnavailable("unavailable")

    monkeypatch.setattr(localized, "translate_texts", fail)
    with pytest.raises(ReportError):
        localized.detail_in(detail, lang="en", reach=REACH)
    assert cache == {}


def test_preparation_builds_both_languages_and_preserves_partial_failure(monkeypatch):
    detail = карточка(шапка())
    monkeypatch.setattr(documents.queries, "get_inspection", lambda *a, **k: detail)
    from src.db import mailing_templates

    monkeypatch.setattr(mailing_templates, "bodies", lambda: {})
    pdfs, letters = [], []

    def pdf(detail, *, lang, reach):
        pdfs.append(lang)
        if lang == "en":
            raise ReportError("storage down")

    monkeypatch.setattr(documents.current_pdf, "ensure_report", pdf)
    monkeypatch.setattr(documents, "letter", lambda *a, **k: letters.append(k["lang"]))
    monkeypatch.setattr(documents.letters, "sources", lambda: object())
    assert documents.prepare(detail.inspection.id, reach=REACH) == {"en": "storage down"}
    assert pdfs == letters == ["ru", "en"]
    monkeypatch.setattr(
        documents.queries,
        "get_inspection",
        lambda *a, **k: replace(detail, inspection=replace(detail.inspection, origin="legacy")),
    )
    assert documents.prepare(detail.inspection.id, reach=REACH) == {}
    assert len(pdfs) == 2
