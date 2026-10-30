"""Повторная выдача связанного визита не откатывается к локальному снимку."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.bot.routers import resend
from src.db.errors import DbError
from src.db.reach import Reach


@pytest.fixture
def linked(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("DATABASE_URL", "configured")
    head = SimpleNamespace(id="exact-visit")
    detail = SimpleNamespace(inspection=head)
    reach = Reach(tenant="actor", tenants=None, countries=("Serbia",))
    lookup = Mock(return_value=SimpleNamespace(id="exact-visit"))
    get = Mock(return_value=detail)
    ensure = Mock(return_value="current-ref")
    fetch = Mock(return_value=b"%PDF-current")
    scope = Mock(return_value=reach)
    monkeypatch.setattr(resend.db, "find_pushed", lookup)
    monkeypatch.setattr(resend.queries, "get_inspection", get)
    monkeypatch.setattr(resend.current_pdf, "ensure_report", ensure)
    monkeypatch.setattr(resend.current_pdf, "report_name", lambda head: "current.pdf")
    monkeypatch.setattr(resend.reports, "fetch_report", fetch)
    monkeypatch.setattr(resend, "reach_of", scope)
    return SimpleNamespace(**locals())


def test_saved_visit_uses_exact_binding_and_actor_scope(linked: SimpleNamespace) -> None:
    assert resend._linked_report(123, space="actor") == (b"%PDF-current", "current.pdf")
    linked.lookup.assert_called_once_with(123)
    linked.scope.assert_called_once_with("actor")
    linked.get.assert_called_once_with("exact-visit", reach=linked.reach, include_on_review=True)
    linked.ensure.assert_called_once_with(linked.detail, reach=linked.reach)
    linked.fetch.assert_called_once_with("current-ref")


def test_no_database_keeps_standalone_path(
    linked: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    assert resend._linked_report(123, space=None) is None
    linked.lookup.assert_not_called()


def test_no_exact_binding_keeps_local_path(linked: SimpleNamespace) -> None:
    linked.lookup.configure_mock(return_value=None)
    assert resend._linked_report(123, space="actor") is None
    linked.get.assert_not_called()


@pytest.mark.parametrize("failure", ["database", "scope", "inaccessible", "build", "fetch"])
def test_configured_failure_never_returns_local_fallback(
    linked: SimpleNamespace, failure: str
) -> None:
    if failure == "database":
        linked.lookup.configure_mock(side_effect=DbError("unavailable"))
    elif failure == "inaccessible":
        linked.get.configure_mock(return_value=None)
    elif failure == "build":
        linked.ensure.configure_mock(side_effect=DbError("busy"))
    elif failure == "fetch":
        linked.fetch.configure_mock(side_effect=DbError("missing"))
    with pytest.raises(DbError):
        resend._linked_report(123, space=None if failure == "scope" else "actor")
    if failure != "fetch":
        linked.fetch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_handler_sends_current_bytes_or_failure_without_local_build(
    domain_env: object, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    from bot_harness import CHAT_ID, feed, make_bot, text_message

    from src.bot.app import build_dispatcher
    from src.bot.config import BotSettings
    from src.bot.texts import t
    from src.domain import start_inspection

    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    local = Mock(side_effect=AssertionError("stale local build"))
    current = Mock(
        side_effect=DbError("unavailable") if failed else None,
        return_value=(b"%PDF-current", "current.pdf"),
    )
    monkeypatch.setattr(resend, "_linked_report", current)
    monkeypatch.setattr(resend, "build_pdf", local)
    bot, session = make_bot()
    await feed(
        build_dispatcher(BotSettings(token="unused-in-tests", mode="polling")),
        bot,
        text_message("/resend"),
    )
    local.assert_not_called()
    documents = [call for call in session.calls if type(call).__name__ == "SendDocument"]
    if failed:
        assert not documents
        assert session.texts[-1] == t("resend.failed", "ru")
    else:
        assert len(documents) == 1
        assert documents[0].document.data == b"%PDF-current"
        assert documents[0].document.filename == "current.pdf"
