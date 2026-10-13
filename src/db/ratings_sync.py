"""Забор общей таблицы контроля: состояние по листам и заявки «Забрать сейчас» (D464).

Таблицы `ratings.sheet_sync` и `ratings.sheet_sync_requests` — миграция 0063.
Состояние — одна строка на лист: когда смотрели, чем кончилось. Заявку принимает
веб или Claude, выполняет бот (`src/bot/sheet_loader.py`) — как у агрегаторов
(`agg.requests`, D420). Журнал самих загрузок — `ratings.imports`
(`src/ratings/importer.py`), здесь его не пишем.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg

from .config import check_environment
from .errors import RatingsError
from .space import apply_space

OUTCOME_LOADED = "loaded"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_FAILED = "failed"
MAX_NOTE = 2000
MAX_ERROR = 500


def _fail(what: str, exc: psycopg.Error) -> RatingsError:
    return RatingsError(f"{what}: база отказала ({exc.__class__.__name__})")


@dataclass(frozen=True)
class SyncState:
    tab: str
    checked_at: datetime
    outcome: str
    sha256: str | None
    import_id: int | None
    note: str | None
    #: Счётчики загрузки, на которую указывает `import_id`: принято, обновлено, пропущено,
    #: не сопоставлено. `None` — загрузки нет (лист не лёг или ещё не брали).
    counts: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class SyncRequest:
    id: int
    requested_at: datetime
    requested_by: str


def states() -> tuple[SyncState, ...]:
    """Состояние по листам с итогами их загрузок, старые первыми."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            rows = conn.execute(
                "select s.tab, s.checked_at, s.outcome, s.sha256, s.import_id, s.note, "
                "i.accepted, i.updated, i.skipped, i.unmatched "
                "from ratings.sheet_sync s left join ratings.imports i on i.id = s.import_id "
                "order by s.checked_at, s.tab"
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Состояние забора таблицы не прочиталось", exc) from exc
    return tuple(
        SyncState(
            r[0], r[1], r[2], r[3], r[4], r[5], None if r[6] is None else (r[6], r[7], r[8], r[9])
        )
        for r in rows
    )


def last_state(tab: str) -> tuple[str | None, str] | None:
    """`(sha256, исход)` последнего захода по листу; `None` — листа ещё не брали."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            row = conn.execute(
                "select sha256, outcome from ratings.sheet_sync where tab = %s", (tab,)
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Состояние забора таблицы не прочиталось", exc) from exc
    return None if row is None else (row[0], str(row[1]))


def was_loaded(sha: str) -> bool:
    """Файл с таким sha256 уже лежал в журнале загрузок исходом `loaded`."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            row = conn.execute(
                "select 1 from ratings.imports where sha256 = %s and outcome = 'loaded'", (sha,)
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Журнал загрузок не прочитался", exc) from exc
    return row is not None


def record(
    tab: str, outcome: str, *, sha256: str | None, import_id: int | None, note: str | None
) -> None:
    """Итог по листу. `sha256=None` — лист не скачался: следующий заход применит его заново,
    даже если он тот же, что лёг до сбоя."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            conn.execute(
                "insert into ratings.sheet_sync "
                "(tab, checked_at, outcome, sha256, import_id, note) "
                "values (%s, now(), %s, %s, %s, %s) "
                "on conflict (tab) do update set checked_at = now(), outcome = excluded.outcome, "
                "  sha256 = excluded.sha256, "
                "  import_id = case when excluded.outcome = 'unchanged' "
                "    then coalesce(excluded.import_id, ratings.sheet_sync.import_id) "
                "    else excluded.import_id end, "
                "  note = excluded.note",
                (tab, outcome, sha256, import_id, None if note is None else note[:MAX_NOTE]),
            )
    except psycopg.Error as exc:
        raise _fail("Итог забора таблицы не записался", exc) from exc


def touch(tab: str) -> str:
    """Лист не менялся: отметить заход. Прежний сбой остаётся сбоем (его причина уже
    в журнале), всё прочее становится `unchanged`. Возвращает исход листа."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            row = conn.execute(
                "update ratings.sheet_sync set checked_at = now(), "
                "  outcome = case when outcome = 'failed' then 'failed' else 'unchanged' end, "
                "  note = case when outcome = 'failed' then note else null end "
                "where tab = %s returning outcome",
                (tab,),
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Итог забора таблицы не записался", exc) from exc
    return OUTCOME_UNCHANGED if row is None else str(row[0])


def open_request() -> SyncRequest | None:
    """Заявка, которую бот ещё не выполнил (`None` — очередь пуста)."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            row = conn.execute(
                "select id, requested_at, requested_by from ratings.sheet_sync_requests "
                "where done_at is null"
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Заявки на забор таблицы не прочитались", exc) from exc
    return None if row is None else SyncRequest(int(row[0]), row[1], str(row[2]))


def request_sync(*, by: str) -> tuple[SyncRequest, bool]:
    """Поставить заявку. Пока предыдущая не выполнена, второй не заводится: вернётся
    она сама и `False`; принята сейчас — `True`."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            row = conn.execute(
                "insert into ratings.sheet_sync_requests (requested_by) values (%s) "
                "on conflict do nothing returning id, requested_at, requested_by",
                (by,),
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Заявка на забор таблицы не легла", exc) from exc
    if row:
        return SyncRequest(int(row[0]), row[1], str(row[2])), True
    queued = open_request()
    if queued is None:  # выполнили между вставкой и чтением
        raise RatingsError("Заявка на забор таблицы не легла: очередь сменилась, повторите")
    return queued, False


def finish_request(request_id: int, *, ok: bool, error: str | None = None) -> None:
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            conn.execute(
                "update ratings.sheet_sync_requests set done_at = now(), outcome = %s, error = %s "
                "where id = %s and done_at is null",
                ("ok" if ok else "failed", (error or "")[:MAX_ERROR] or None, request_id),
            )
    except psycopg.Error as exc:
        raise _fail("Заявка на забор таблицы не закрылась", exc) from exc


def recent_requests(limit: int = 1) -> Sequence[tuple[datetime, str, str | None]]:
    """Последние закрытые заявки: `(когда, исход, текст ошибки)`."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            apply_space(conn)
            rows = conn.execute(
                "select done_at, outcome, error from ratings.sheet_sync_requests "
                "where done_at is not null order by done_at desc limit %s",
                (limit,),
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Заявки на забор таблицы не прочитались", exc) from exc
    return [(r[0], str(r[1]), r[2]) for r in rows]
