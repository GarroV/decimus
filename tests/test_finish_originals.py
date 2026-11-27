"""AUTO completion renders translations while preserving acknowledged evidence and recovery."""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from bot_harness import CHAT_ID, make_bot, text_message
from test_document_languages import cache  # noqa: F401
from test_engine_letter_feedback import _роли
from test_report_photos import текст_pdf
from test_technical_checks import technical_env  # noqa: F401
from test_web_app import карточка, шапка

from src import domain
from src.bot import finish_archive, finish_translate
from src.bot.routers import finish
from src.db.errors import DbError
from src.db.models import InfoRow
from src.domain import completion
from src.domain.engine import state_file
from src.domain.revision import revision
from src.domain.state import read_state, settings_for
from src.domain.technical import confirm, snapshot
from src.report import build_letter_notes, localized
from src.report.build import build_pdf


@pytest.mark.usefixtures("technical_env", "cache")
def test_auto_completion_preserves_original_evidence_and_recovery(request, monkeypatch):
    _роли(request.getfixturevalue("technical_env"), {"INF01": "strengths", "INF06": "growth"})
    domain.start_inspection(
        CHAT_ID, unit="Sample-1", kind="planned", report_lang="ru", speech_lang="ru"
    )
    domain.add_finding(
        CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар", comment="Очистить", photos=["photo-1"]
    )
    domain.set_info(CHAT_ID, "INF01", "Сильная команда")
    domain.set_info(CHAT_ID, "INF06", "Нужна уборка")
    inspection = domain.set_report_lang(CHAT_ID, "en")
    for code, status in (("TC001", "issue"), ("TC002", "ok")):
        confirm(
            CHAT_ID,
            run_id=inspection.run_id,
            check_id=code,
            zone="hot_kitchen",
            status=status,
            finding_numbers=[1] if status == "issue" else [],
        )
    inspection = domain.get_state(CHAT_ID)
    technical = snapshot(CHAT_ID)
    original = state_file(CHAT_ID, settings_for(CHAT_ID)).read_bytes()
    calls = []
    translations = {
        "Нагар": "Carbon deposits",
        "Очистить": "Clean the surface",
        "Сильная команда": "Strong team",
        "Нужна уборка": "Cleaning needed",
    }

    def translate(texts, *, lang):
        calls.extend(texts)
        return [translations[text] for text in texts]

    monkeypatch.setattr(localized, "translate_texts", translate)
    monkeypatch.setattr(finish_translate.translate_modes, "chosen_translate_mode", lambda _: "auto")
    # The API boundary is simulated; no Telegram or database messages leave this test.
    from PIL import Image

    frame = Path(request.getfixturevalue("technical_env")).parent / "photo.png"
    Image.new("RGB", (2, 2), "white").save(frame)
    photo_bytes = frame.read_bytes()

    async def photos(*args):
        return {"photo-1": str(frame)}

    monkeypatch.setattr(finish, "download_all", photos)
    jobs = []
    archived = []

    def push(chat_id, *, source_settings):
        completion.validate(chat_id, source_settings)
        jobs.append(source_settings)
        archived.append(read_state(chat_id, source_settings))
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(finish.db, "push_inspection", push)
    monkeypatch.setattr(finish.db, "upload_photos", lambda *a, **k: None)
    monkeypatch.setattr(
        finish.db,
        "upload_report",
        lambda *a, **k: SimpleNamespace(
            storage_path="test/report", size_bytes=len(k["data"]), already=False
        ),
    )
    save_translation = localized.document_cache.save
    cache_attempts = []

    def intermittent_cache(*args, **kwargs):
        cache_attempts.append(kwargs)
        if len(cache_attempts) == 1:
            raise DbError("temporary cache outage")
        save_translation(*args, **kwargs)

    monkeypatch.setattr(localized.document_cache, "save", intermittent_cache)
    bot, session = make_bot()
    asyncio.run(finish.deliver(text_message("finish").as_(bot), CHAT_ID, "ru", allow_missing=False))
    assert len(session.documents) == 1
    assert any("Strong team" in text and "Cleaning needed" in text for text in session.texts)
    assert any("Carbon deposits" in text for text in session.texts)
    done = domain.get_state(CHAT_ID)
    assert done.finished_at is not None
    assert (
        replace(
            done,
            finished_at=inspection.finished_at,
            technical_snapshot=inspection.technical_snapshot,
        )
        == inspection
    )
    assert done.findings == inspection.findings == archived[0].findings
    assert done.info == inspection.info == archived[0].info
    assert done.technical_checks == inspection.technical_checks
    assert done.technical_snapshot["checks"] == technical["checks"]
    assert done.technical_snapshot["required_pending"] == 0
    job = jobs[0]
    printed = текст_pdf(completion.report_path(CHAT_ID, job))
    assert "Carbon deposits" in printed and "Clean the surface" in printed
    assert "Strong team" in printed and "Cleaning needed" in printed
    source = state_file(CHAT_ID, job).read_bytes()
    assert source != original  # completion adds time and the frozen technical summary only
    assert state_file(CHAT_ID, settings_for(CHAT_ID)).read_bytes() == source
    completion.validate(CHAT_ID, job)
    before_revision = revision(read_state(CHAT_ID, job))
    assert finish_translate.translate_comments(CHAT_ID, done, source_settings=job) == 0
    build_pdf(CHAT_ID, fetch_photo=lambda _: str(frame), source_settings=job)
    assert "Strong team" in build_letter_notes(CHAT_ID, source_settings=job).text
    assert state_file(CHAT_ID, job).read_bytes() == source
    assert frame.read_bytes() == photo_bytes
    assert revision(read_state(CHAT_ID, job)) == before_revision
    assert len(calls) == 4

    # A process restart retries the exact source, PDF and photo; no new translation call.
    pending = completion.pending()
    assert len(pending) == 1
    assert Path(pending[0][2]["photo-1"]).read_bytes() == photo_bytes
    asyncio.run(finish_archive.retry_once())
    assert completion.pending() == []
    assert len(cache_attempts) == 2
    assert archived[-1].findings == inspection.findings
    assert len(calls) == 4

    # Acceptance/MCP/PDF can consume the archived seed with database row identifiers.
    detail = карточка(replace(шапка(), id=push(CHAT_ID, source_settings=job), speech_lang="ru"))
    detail = replace(
        detail,
        findings=(replace(detail.findings[0], lang="ru", text="Нагар", comment="Очистить"),),
        info=(InfoRow("INF01", "Сильная команда"), InfoRow("INF06", "Нужна уборка")),
    )
    rendered = localized.detail_in(detail, lang="en", reach=localized.Reach("HQ", ("HQ",), None))
    assert rendered.findings[0].text == "Carbon deposits"
    assert rendered.info[0].text == "Strong team"
    assert len(calls) == 4


@pytest.mark.usefixtures("technical_env")
def test_translation_outage_keeps_completion_and_technical_confirmations(monkeypatch):
    from src.recognize.errors import ModelUnavailable

    domain.start_inspection(
        CHAT_ID, unit="Sample-1", kind="planned", report_lang="ru", speech_lang="ru"
    )
    domain.set_info(CHAT_ID, "INF01", "Сильная команда")
    inspection = domain.set_report_lang(CHAT_ID, "en")
    for code in ("TC001", "TC002"):
        confirm(CHAT_ID, run_id=inspection.run_id, check_id=code, zone="hot_kitchen", status="ok")
    original = domain.get_state(CHAT_ID)
    monkeypatch.setattr(finish_translate.translate_modes, "chosen_translate_mode", lambda _: "auto")

    def unavailable(*a, **k):
        raise ModelUnavailable("unavailable")

    monkeypatch.setattr(localized, "translate_texts", unavailable)
    bot, session = make_bot()
    asyncio.run(finish.deliver(text_message("finish").as_(bot), CHAT_ID, "ru", allow_missing=False))
    assert len(session.documents) == 1
    assert any("перев" in text and "1" in text for text in session.texts)
    done = domain.get_state(CHAT_ID)
    assert done.finished_at is not None
    assert done.info == original.info
    assert done.technical_checks == original.technical_checks
    assert done.technical_snapshot["required_pending"] == 0
    assert len(completion.pending()) == 1  # standalone DB outage keeps durable archival pending
