"""Synthetic audit reproductions; external model, Bot API and database never called."""

import pytest
from bot_harness import CHAT_ID, make_bot, text_message
from conftest import requires_db

from src import domain
from src.bot import finish_translate, merged, sidecar
from src.bot.pending import PendingStore, Proposal
from src.bot.routers import finish
from src.domain.revision import revision


def start(unit="Audit A"):
    domain.start_inspection(CHAT_ID, unit, "planned", "ru", auditor="Synthetic")
    domain.add_finding(
        CHAT_ID,
        code="CLN05",
        level="D1",
        zone="hot_kitchen",
        text="Old words",
        comment="Old comment",
    )
    return domain.get_state(CHAT_ID)


def replace_run():
    domain.drop_inspection(CHAT_ID)
    sidecar.reset(CHAT_ID)
    return start("Audit B")


@pytest.mark.asyncio
async def test_translation_preserves_confirmed_finish(domain_env, monkeypatch):
    start()
    domain.set_report_lang(CHAT_ID, "en")
    before = revision(domain.get_state(CHAT_ID))
    monkeypatch.setattr(finish_translate, "mode_of", lambda _: "auto")
    monkeypatch.setattr(finish_translate, "translate_text", lambda *a, **k: "Translated comment")
    bot, session = make_bot()
    await finish.deliver(
        text_message("/finish").as_(bot),
        CHAT_ID,
        "ru",
        allow_missing=True,
        expected_revision=before,
    )
    assert domain.get_state(CHAT_ID).findings[0].comment == "Translated comment"
    assert len(session.documents) == 1
    assert domain.get_state(CHAT_ID).finished_at is not None


@pytest.mark.parametrize("new_run", [False, True])
def test_late_translation_preserves_changed_target(domain_env, monkeypatch, new_run):
    old = start()

    def model(*args, **kwargs):
        if new_run:
            replace_run()
        domain.edit_finding(CHAT_ID, 1, comment="Fresh human words")
        return "Old translated words"

    monkeypatch.setattr(finish_translate, "translate_text", model)
    assert finish_translate._translate_findings(CHAT_ID, old, "en") > 0
    current = domain.get_state(CHAT_ID)
    assert current.findings[0].comment == "Fresh human words"
    assert (current.run_id != old.run_id) == new_run


@pytest.mark.asyncio
async def test_replacement_cannot_change_report_run(domain_env, monkeypatch, tmp_path):
    start()
    built = []

    async def download(*a, **k):
        assert domain.handed_over(CHAT_ID)
        replace_run()
        return {}

    def build(chat_id, **kwargs):
        from src.domain.state import read_state

        built.append(read_state(chat_id, kwargs["source_settings"]).unit)
        p = tmp_path / "synthetic.pdf"
        p.write_bytes(b"%PDF synthetic test")
        return p

    monkeypatch.setattr(finish, "download_all", download)
    monkeypatch.setattr(finish, "build_pdf", build)
    bot, session = make_bot()
    await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    assert built == ["Audit A"]
    assert domain.get_state(CHAT_ID).unit == "Audit B"
    assert domain.get_state(CHAT_ID).finished_at is None
    assert not domain.handed_over(CHAT_ID)
    assert len(session.documents) == 1


@pytest.mark.asyncio
async def test_post_pdf_message_failure_cannot_skip_archive(domain_env, monkeypatch, tmp_path):
    start()
    called = []
    p = tmp_path / "synthetic.pdf"
    p.write_bytes(b"%PDF synthetic test")
    monkeypatch.setattr(finish, "build_pdf", lambda *a, **k: p)

    async def warn(*a, **k):
        raise RuntimeError("Synthetic Bot API failure")

    async def archive(*a, **k):
        called.append(True)

    monkeypatch.setattr(finish, "warn_untranslated", warn)
    monkeypatch.setattr(finish, "archive", archive)
    bot, session = make_bot()
    with pytest.raises(RuntimeError, match="Synthetic Bot API"):
        await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    assert len(session.documents) == 1
    assert domain.get_state(CHAT_ID).finished_at is not None
    assert domain.handed_over(CHAT_ID)
    assert called == [True]
    await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    assert len(session.documents) == 1
    assert called == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("new_run", [False, True])
async def test_late_merge_preserves_changed_target(domain_env, monkeypatch, new_run):
    old = start()

    def model(*args, **kwargs):
        if new_run:
            replace_run()
        domain.edit_finding(CHAT_ID, 1, text="Fresh human words")
        return "Stale merged words"

    monkeypatch.setattr(merged, "merge_wording", model)
    await merged._rewrite(CHAT_ID, old.findings[0], "More words", "ru")
    current = domain.get_state(CHAT_ID)
    assert current.findings[0].text == "Fresh human words"
    assert (current.run_id != old.run_id) == new_run


@pytest.mark.asyncio
async def test_late_proposal_cannot_enter_new_run(domain_env):
    from src.bot.routers.record import _save

    old = start()
    pending = PendingStore(run_of=lambda chat: domain.get_state(chat).run_id)
    assert pending.proposal(CHAT_ID) is None
    late = Proposal(
        file_ids=("synthetic-old-photo",), source="comment", note="Old run words", run_id=old.run_id
    )
    current = replace_run()
    assert old.run_id != current.run_id
    pending.propose(CHAT_ID, late, at=99)
    assert pending.proposal(CHAT_ID, at=99) is None
    bot, _session = make_bot()
    await _save(
        text_message("Synthetic pick").as_(bot),
        CHAT_ID,
        code="CLN06",
        level="D1",
        zone="hot_kitchen",
        text="Old run observation",
        file_ids=late.file_ids,
        source=late.source,
        lang="ru",
        words=late.note,
        expected_run_id=late.run_id,
        zone_spoken=True,
    )
    after = domain.get_state(CHAT_ID)
    assert after.run_id == current.run_id
    assert len(after.findings) == 1
    assert after.findings[0].words != late.note


@pytest.mark.asyncio
@pytest.mark.parametrize("new_run", [False, True])
async def test_late_correction_preserves_changed_target(domain_env, monkeypatch, new_run):
    from src.bot.routers import correct
    from src.recognize.revise import Revision

    before = start()

    async def model(*args, **kwargs):
        if new_run:
            replace_run()
        domain.edit_finding(CHAT_ID, 1, text="Fresh human words")
        return Revision("wording", "Stale model words")

    monkeypatch.setattr(correct, "_revision", model)
    bot, _ = make_bot()
    assert await correct._revise(
        text_message("Please revise").as_(bot),
        CHAT_ID,
        before.findings[0],
        "Old request",
        lang="ru",
        report_lang="ru",
    )
    assert domain.get_state(CHAT_ID).findings[0].text == "Fresh human words"


@pytest.mark.asyncio
async def test_archive_retry_survives_new_run_and_preserves_media(
    domain_env, monkeypatch, tmp_path
):
    from src import db
    from src.bot import finish_archive
    from src.domain import completion
    from src.domain.state import read_state

    source = start()
    domain.attach_photo(CHAT_ID, 1, "old-photo")
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"%PDF original report")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"synthetic evidence")
    monkeypatch.setattr(finish, "build_pdf", lambda *a, **k: pdf)

    async def download(*args, **kwargs):
        return {"old-photo": str(frame)}

    async def warn(*args, **kwargs):
        raise RuntimeError("Synthetic warning failure")

    monkeypatch.setattr(finish, "download_all", download)
    monkeypatch.setattr(finish, "warn_untranslated", warn)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append("unavailable")
        raise db.PushError("Synthetic database outage")

    monkeypatch.setattr(db, "push_inspection", unavailable)
    bot, session = make_bot()
    with pytest.raises(RuntimeError, match="Synthetic warning"):
        await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    assert len(session.documents) == 1
    assert len(completion.pending()) == 1
    replace_run()
    frame.unlink()
    pdf.unlink()

    def push(chat_id, *, source_settings):
        inspection = read_state(chat_id, source_settings)
        assert inspection.run_id == source.run_id
        assert inspection.unit == "Audit A"
        assert inspection.finished_at is not None
        completion.validate(chat_id, source_settings)
        calls.append("archived")
        return "stable-inspection-id"

    def photos(inspection_id, *, fetch, allow_missing):
        assert inspection_id == "stable-inspection-id"
        assert fetch("old-photo") == b"synthetic evidence"
        return 1

    def report(inspection_id, *, data):
        assert inspection_id == "stable-inspection-id"
        assert data == b"%PDF original report"

    monkeypatch.setattr(db, "push_inspection", push)
    monkeypatch.setattr(db, "upload_photos", photos)
    monkeypatch.setattr(db, "upload_report", report)
    await finish_archive.retry_once()
    await finish_archive.retry_once()
    assert calls == ["unavailable", "archived"]
    assert not completion.pending()
    assert len(session.documents) == 1
    assert domain.get_state(CHAT_ID).unit == "Audit B"
    assert domain.get_state(CHAT_ID).finished_at is None


@pytest.mark.parametrize("damage", ["run", "methodology", "missing_methodology"])
def test_archive_snapshot_rejects_changed_source(domain_env, tmp_path, damage):
    from dataclasses import replace

    from src.domain import completion
    from src.domain.config import DATA_FILES
    from src.domain.engine import state_file
    from src.domain.errors import DomainError
    from src.domain.state import _read_raw, _write_atomic
    from src.domain.timing import utc_now

    source = start()
    env = completion.snapshot(CHAT_ID, source.run_id, revision(source))
    completion.finish_snapshot(CHAT_ID, env, utc_now())
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF original")
    completion.prepare(CHAT_ID, env, pdf, {})
    completion.mark(CHAT_ID, env, "delivered")
    completion.validate(CHAT_ID, env)
    if damage == "run":
        path = state_file(CHAT_ID, env)
        raw = _read_raw(path)
        raw["domain"]["run_id"] = "different-run"
        _write_atomic(path, raw)
    elif damage == "methodology":
        env = replace(env, data_dir=tmp_path)
        (tmp_path / DATA_FILES[0]).write_text("different methodology")
    else:
        env = replace(env, data_dir=tmp_path / "missing")
    with pytest.raises((DomainError, OSError)):
        completion.validate(CHAT_ID, env)


@pytest.mark.asyncio
async def test_old_build_failure_cannot_unseal_new_visit(domain_env, monkeypatch):
    from src.report import ReportError

    start()

    async def download(*args, **kwargs):
        replace_run()
        sidecar.mark_handed_over(CHAT_ID, 1)
        return {}

    def broken(*args, **kwargs):
        raise ReportError("Synthetic render failure")

    monkeypatch.setattr(finish, "download_all", download)
    monkeypatch.setattr(finish, "build_pdf", broken)
    bot, session = make_bot()
    await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    assert not session.documents
    assert domain.get_state(CHAT_ID).unit == "Audit B"
    assert domain.handed_over(CHAT_ID)


@pytest.mark.asyncio
@requires_db
async def test_snapshot_archive_is_idempotent_in_postgres(
    domain_env, db_env, monkeypatch, tmp_path
):
    import psycopg

    from src import db
    from src.domain import completion

    start("Белград 2")
    real_push = db.push_inspection
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF synthetic report")
    monkeypatch.setattr(finish, "build_pdf", lambda *a, **k: pdf)

    def unavailable(*args, **kwargs):
        raise db.PushError("Synthetic archive outage")

    monkeypatch.setattr(db, "push_inspection", unavailable)
    bot, session = make_bot()
    await finish.deliver(text_message("/finish").as_(bot), CHAT_ID, "ru", allow_missing=True)
    [(chat_id, env, _photos)] = completion.pending()
    replace_run()
    first_id = real_push(chat_id, source_settings=env)
    second_id = real_push(chat_id, source_settings=env)
    assert first_id == second_id
    with psycopg.connect(db_env) as conn:
        assert conn.execute("select count(*) from inspections").fetchone()[0] == 1
    assert len(session.documents) == 1
    assert domain.get_state(CHAT_ID).unit == "Audit B"


def test_archive_cleanup_keeps_pending_and_recent_deliveries(domain_env, tmp_path, monkeypatch):
    from src.domain import completion
    from src.domain.engine import state_file
    from src.domain.timing import utc_now

    source = start()
    env = completion.snapshot(CHAT_ID, source.run_id, revision(source))
    completion.finish_snapshot(CHAT_ID, env, utc_now())
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF original")
    completion.prepare(CHAT_ID, env, pdf, {})
    completion.mark(CHAT_ID, env, "delivered")
    now = completion.time.time()
    monkeypatch.setattr(completion.time, "time", lambda: now + completion.ARCHIVED_KEEP_SEC + 1)
    completion.prune_archived()
    assert state_file(CHAT_ID, env).is_file()
    completion.mark(CHAT_ID, env, "archived")
    completion.prune_archived()
    assert state_file(CHAT_ID, env).is_file()
    monkeypatch.setattr(completion.time, "time", lambda: now + 2 * completion.ARCHIVED_KEEP_SEC + 2)
    completion.prune_archived()
    assert not state_file(CHAT_ID, env).exists()
    assert domain.get_state(CHAT_ID).run_id == source.run_id


@pytest.mark.asyncio
async def test_photo_archive_error_keeps_durable_evidence(domain_env, monkeypatch):
    from src import db

    monkeypatch.setattr(db, "push_inspection", lambda *args, **kwargs: "inspection-id")

    def broken(*args, **kwargs):
        raise db.PushError("Synthetic photo metadata failure")

    monkeypatch.setattr(db, "upload_photos", broken)
    bot, _session = make_bot()
    assert (
        await finish.archive(
            text_message("/finish").as_(bot),
            CHAT_ID,
            {},
            "ru",
            allow_missing=True,
        )
        is False
    )
