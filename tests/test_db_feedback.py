"""D761 п.6: отзывы из кнопки «Обратная связь» на настоящей базе.

Что нельзя обойти, позвав запись напрямую: предел частоты на учётку, видимость по
пространству (УК читает всё, партнёр — только своё), правка только отметок, чат Telegram
не задан, пока его не задали.
"""

from __future__ import annotations

import psycopg
import pytest
from conftest import requires_db

from src.db import feedback as store
from src.db.errors import DbError
from src.db.space import acting_space

pytestmark = requires_db

JPEG = b"\xff\xd8\xff\xe0jpeg-bytes"


@pytest.fixture
def spaces(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        for code in ("HQ", "RS", "GE"):
            conn.execute("insert into tenants (code) values (%s) on conflict do nothing", (code,))


def _save(space: str, login: str = "anna", **over: object) -> str:
    fields: dict[str, object] = {
        "tenant": space,
        "login": login,
        "role": "auditor",
        "page": "/inspections?x=1",
        "lang": "ru",
        "body": "Не работает кнопка",
    }
    fields.update(over)
    with acting_space(space):
        return store.save(**fields)  # type: ignore[arg-type]


def test_roundtrip_with_photos_and_page_context(spaces: None) -> None:
    new_id = _save("RS", photos=[JPEG, JPEG + b"2"])
    with acting_space("HQ"):
        [entry] = store.entries()
        shot = store.photo(entry.photo_ids[1])
    assert entry.id == new_id
    assert (entry.tenant, entry.login, entry.role, entry.lang) == ("RS", "anna", "auditor", "ru")
    assert entry.page == "/inspections?x=1" and entry.body == "Не работает кнопка"
    assert entry.reviewed_at is None and entry.telegram_sent_at is None
    assert len(entry.photo_ids) == 2
    assert shot == ("image/jpeg", JPEG + b"2")


def test_hq_reads_everything_partner_only_own_space(spaces: None) -> None:
    rs = _save("RS", photos=[JPEG])
    ge = _save("GE", login="boris")
    with acting_space("HQ"):
        assert {e.id for e in store.entries()} == {rs, ge}
    with acting_space("RS"):
        assert [e.id for e in store.entries()] == [rs]
    with acting_space("GE"):
        mine = store.entries()
        assert [e.id for e in mine] == [ge]
    with acting_space("HQ"):
        [rs_entry] = [e for e in store.entries() if e.id == rs]
        photo_id = rs_entry.photo_ids[0]
    with acting_space("GE"):
        assert store.photo(photo_id) is None  # чужой кадр по угаданному номеру не отдаётся
    with acting_space("RS"):
        assert store.photo(photo_id) is not None


def test_partner_cannot_write_into_another_space(spaces: None) -> None:
    with acting_space("RS"), pytest.raises(psycopg.Error):
        store.save(
            tenant="GE", login="x", role="auditor", page="/", lang="ru", body="чужое пространство"
        )


def test_rate_limit_per_login_within_the_hour(spaces: None) -> None:
    for _ in range(store.MAX_PER_HOUR):
        _save("RS")
    with pytest.raises(store.FeedbackRateLimited):
        _save("RS")
    _save("RS", login="other")  # другая учётка — своё окно


def test_old_entries_do_not_count(spaces: None, pg_dsn: str) -> None:
    for _ in range(store.MAX_PER_HOUR):
        _save("RS")
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("update feedback set created_at = now() - interval '2 hours'")
    _save("RS")


def test_rejected_entry_leaves_nothing_behind(spaces: None) -> None:
    for _ in range(store.MAX_PER_HOUR):
        _save("RS")
    with pytest.raises(store.FeedbackRateLimited):
        _save("RS", photos=[JPEG])
    with acting_space("HQ"):
        assert len(store.entries()) == store.MAX_PER_HOUR
        assert all(not e.photo_ids for e in store.entries())


@pytest.mark.parametrize(
    "bad",
    [{"body": "   "}, {"body": "я" * 4001}, {"lang": "RUS"}, {"page": "/" * 501}, {"login": " "}],
)
def test_base_refuses_unfit_rows(spaces: None, bad: dict[str, object]) -> None:
    with pytest.raises(psycopg.Error):
        _save("RS", **bad)


def test_too_many_photos_are_refused_by_the_base(spaces: None) -> None:
    with pytest.raises(psycopg.Error):
        _save("RS", photos=[JPEG] * 6)


def test_text_is_not_editable_only_marks_are(spaces: None, db_env: str) -> None:
    new_id = _save("RS")
    with acting_space("HQ"):
        with psycopg.connect(db_env) as conn:
            conn.execute("select set_config('decimus.space', 'HQ', false)")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("update feedback set body = 'подмена' where id = %s", (new_id,))
        assert store.mark_reviewed(new_id, reviewed=True, by="director") is True
        [entry] = store.entries()
        assert entry.reviewed_by == "director" and entry.reviewed_at is not None
        assert store.mark_reviewed(new_id, reviewed=False, by="director") is True
        [entry] = store.entries()
        assert entry.reviewed_at is None and entry.reviewed_by is None
        store.record_delivery(new_id, sent=False, error="http_403")
        assert store.entries()[0].telegram_error == "http_403"
        store.record_delivery(new_id, sent=True)
        [entry] = store.entries()
        assert entry.telegram_sent_at is not None and entry.telegram_error is None


def test_other_partner_cannot_mark_foreign_entry(spaces: None) -> None:
    new_id = _save("RS")
    with acting_space("GE"):
        assert store.mark_reviewed(new_id, reviewed=True, by="boris") is False
    with acting_space("HQ"):
        assert store.entries()[0].reviewed_at is None


def test_nothing_is_deleted_by_the_app_role(spaces: None, db_env: str) -> None:
    new_id = _save("RS")
    with psycopg.connect(db_env) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from feedback where id = %s", (new_id,))


def test_no_chat_until_one_is_set(spaces: None) -> None:
    with acting_space("HQ"):
        assert store.chat_id() is None  # миграция чат не задаёт
        store.set_chat_id("-1001234567890", by="director")
        assert store.chat_id() == "-1001234567890"
        store.set_chat_id("-1009999999999", by="director")
        assert store.chat_id() == "-1009999999999"  # текущий — последний
        store.set_chat_id(None, by="director")
        assert store.chat_id() is None
    with acting_space("RS"):  # читать чат для отправки нужно любому пространству
        assert store.chat_id() is None


@pytest.mark.parametrize("bad", ["abc", "12", "1001234; drop table feedback", "--100123456"])
def test_base_refuses_a_malformed_chat(spaces: None, bad: str) -> None:
    with acting_space("HQ"), pytest.raises(psycopg.Error):
        store.set_chat_id(bad, by="director")


def test_bad_id_is_a_refusal_not_a_crash(spaces: None) -> None:
    with acting_space("HQ"):
        with pytest.raises(DbError):
            store.photo("not-a-uuid")
        with pytest.raises(DbError):
            store.mark_reviewed("nope", reviewed=True, by="director")
