"""Забор общей таблицы контроля «база рейтингов» самим decimus (D464).

Таблица открыта по ссылке; каждый лист скачивается как CSV без ключа:
`…/spreadsheets/d/<id>/export?format=csv&gid=<gid>`. Адрес таблицы — настройка
сервера `RATINGS_SHEET_ID`, в репозиторий его не кладём (репозиторий публичный,
таблица открыта любому с адресом). Номера листов (`gid`) без адреса таблицы
ничего не открывают и живут здесь.

Каждый лист идёт той же дверью, что ручная загрузка (`importer.import_file`,
журнал `ratings.imports`, автор `sheet-sync`, канал `sync`). Лист, чьё содержимое
не менялось с прошлого захода (тот же sha256), пропускается без строки журнала;
итог захода по каждому листу — в `ratings.sheet_sync` и на экране «Загрузки».
Сбой — закрытая таблица, ответ не 200, заголовок листа изменился, база отказала —
это строка `failed` в журнале и строка состояния с причиной, а не тишина.

Справочник ссылок («Справочник», «Реестр_ссылок») не журналируется: он нужен, чтобы
найти id пиццерии, чьё имя не сопоставилось с известными. Не скачался — листы
идут без него, пиццерия без id попадает в «не сопоставлено».
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.db import ratings as store
from src.db import ratings_sync as state
from src.db.errors import RatingsError

from .base import parse_directory
from .importer import CHANNEL_SYNC, OUTCOME_DUPLICATE, ImportReport, import_file
from .model import (
    FORMAT_BASE_COLLECTION,
    FORMAT_BASE_RKO_VIOLATIONS,
    FORMAT_BASE_RS_VIOLATIONS,
    FORMAT_BASE_SCORES,
    RatingsFormatError,
)

logger = logging.getLogger(__name__)

SHEET_ID_VAR = "RATINGS_SHEET_ID"
SYNC_ACTOR = "sheet-sync"
#: Как часто бот забирает таблицу сам.
SYNC_EVERY_SEC = 3 * 60 * 60
FETCH_TIMEOUT_SEC = 60
MAX_SHEET_BYTES = 30 * 1024 * 1024
_EXPORT = "https://docs.google.com/spreadsheets/d/{sheet}/export?format=csv&gid={gid}"
_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
USER_AGENT = "decimus-ratings-sync"

#: Листы, которые идут в журнал: формат (он же ключ состояния) и номер листа.
TABS: tuple[tuple[str, int], ...] = (
    (FORMAT_BASE_SCORES, 0),
    (FORMAT_BASE_COLLECTION, 1669206617),
    (FORMAT_BASE_RKO_VIOLATIONS, 1721034650),
    (FORMAT_BASE_RS_VIOLATIONS, 1924069821),
)
#: Справочники ссылок «Пиццерия, Ссылка для РКО, Ссылка для РС».
DIRECTORY_GIDS = (818224501, 339059090)

ERR_NOT_CONFIGURED = "not_configured"
ERR_BAD_ID = "bad_id"
ERR_HTTP = "http"
ERR_CLOSED = "closed"
ERR_NETWORK = "network"
ERR_TOO_BIG = "too_big"
ERR_HEADER = "header"
ERR_DB = "db"

#: Исходы листа в `ratings.sheet_sync`.
LOADED = state.OUTCOME_LOADED
UNCHANGED = state.OUTCOME_UNCHANGED
FAILED = state.OUTCOME_FAILED


class SyncError(Exception):
    """Лист не взят: `code` — машинный признак для экрана, текст — для журнала."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


Fetcher = Callable[[str, int], bytes]


@dataclass(frozen=True)
class TabResult:
    tab: str
    outcome: str
    note: str | None = None
    report: ImportReport | None = None


def sheet_id(env: Mapping[str, str] | None = None) -> str | None:
    """Адрес таблицы из настройки сервера; не задан — `None`. Негодный вид — `SyncError`."""
    value = (env if env is not None else os.environ).get(SHEET_ID_VAR, "").strip()
    if not value:
        return None
    if not _SHEET_ID.match(value):
        raise SyncError(ERR_BAD_ID, f"{SHEET_ID_VAR} не похоже на идентификатор таблицы Google")
    return value


def configured(env: Mapping[str, str] | None = None) -> bool:
    return bool((env if env is not None else os.environ).get(SHEET_ID_VAR, "").strip())


def fetch_sheet(sheet: str, gid: int) -> bytes:
    """CSV одного листа. Закрытая таблица Google отдаёт страницу входа с кодом 200,
    поэтому ответ проверяется по виду, а не только по коду."""
    request = urllib.request.Request(  # noqa: S310 — хост постоянный, идентификатор проверен
        _EXPORT.format(sheet=sheet, gid=gid), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SEC) as response:  # noqa: S310
            kind = response.headers.get_content_type()
            body: bytes = response.read(MAX_SHEET_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SyncError(ERR_HTTP, f"таблица ответила кодом {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(ERR_NETWORK, f"таблица не отвечает ({type(exc).__name__})") from exc
    if len(body) > MAX_SHEET_BYTES:
        raise SyncError(ERR_TOO_BIG, "лист больше допустимого размера")
    if kind != "text/csv" or body.lstrip()[:1] == b"<":
        raise SyncError(ERR_CLOSED, "вместо листа пришла страница входа: таблица закрыта по ссылке")
    return body


def _note(code: str, text: str) -> str:
    """Причина в виде `код: текст` — экран по коду берёт свой перевод."""
    return f"{code}: {text}"[: state.MAX_NOTE]


def _directory(sheet: str, fetch: Fetcher) -> dict[str, str]:
    """Имя → id по справочникам; любой сбой — пусто и строка в логе, листы идут без него."""
    merged: dict[str, set[str]] = {}
    for gid in DIRECTORY_GIDS:
        try:
            part = parse_directory(fetch(sheet, gid))
        except (SyncError, RatingsFormatError) as exc:
            logger.warning("рейтинги: справочник ссылок (лист %s) не взят: %s", gid, exc)
            continue
        for key, dodo_id in part.items():
            merged.setdefault(key, set()).add(dodo_id)
    return {key: next(iter(ids)) for key, ids in merged.items() if len(ids) == 1}


def _failed(tab: str, note: str, *, sha: str | None) -> TabResult:
    """След неудачи: строка журнала (если её ещё не оставил разбор) и состояние листа."""
    journal_sha = hashlib.sha256(f"{tab}|{note}".encode()).hexdigest()
    import_id = store.record_failure(
        channel=CHANNEL_SYNC, actor=SYNC_ACTOR, file_name=f"sheet:{tab}", sha=journal_sha, note=note
    )
    state.record(tab, FAILED, sha256=sha, import_id=import_id, note=note)
    return TabResult(tab, FAILED, note)


def _pull(
    tab: str, gid: int, *, sheet: str, fetch: Fetcher, today: date, directory: Mapping[str, str]
) -> TabResult:
    try:
        data = fetch(sheet, gid)
    except SyncError as exc:
        return _failed(tab, _note(exc.code, str(exc)), sha=None)
    sha = hashlib.sha256(data).hexdigest()
    last = state.last_state(tab)
    if last is not None and last[0] == sha:
        # Тот же лист, что в прошлый раз: ложился — ничего нового; не ложился — причина
        # уже в журнале, второй раз её не пишем.
        return TabResult(tab, state.touch(tab))
    salt = datetime.now(UTC).isoformat() if state.was_loaded(sha) else None
    try:
        report = import_file(
            data,
            kind=tab,
            channel=CHANNEL_SYNC,
            actor=SYNC_ACTOR,
            file_name=f"sheet:{tab}",
            today=today,
            directory=directory,
            sha_salt=salt,
        )
    except RatingsFormatError as exc:
        # Разбор уже оставил строку `failed`; состоянию нужна причина с кодом.
        note = _note(ERR_HEADER, str(exc))
        state.record(tab, FAILED, sha256=sha, import_id=None, note=note)
        return TabResult(tab, FAILED, note)
    except RatingsError as exc:
        note = _note(ERR_DB, str(exc))
        state.record(tab, FAILED, sha256=sha, import_id=None, note=note)
        return TabResult(tab, FAILED, note)
    outcome = UNCHANGED if report.outcome == OUTCOME_DUPLICATE else LOADED
    state.record(tab, outcome, sha256=sha, import_id=report.import_id, note=None)
    return TabResult(tab, outcome, report=report)


def run(
    *, today: date | None = None, fetch: Fetcher = fetch_sheet, env: Mapping[str, str] | None = None
) -> tuple[TabResult, ...]:
    """Забрать все листы. Таблица не настроена или адрес негоден — `SyncError`."""
    sheet = sheet_id(env)
    if sheet is None:
        raise SyncError(ERR_NOT_CONFIGURED, f"{SHEET_ID_VAR} не задан в настройках сервера")
    day = today or date.today()
    directory = _directory(sheet, fetch)
    return tuple(
        _pull(tab, gid, sheet=sheet, fetch=fetch, today=day, directory=directory)
        for tab, gid in TABS
    )
