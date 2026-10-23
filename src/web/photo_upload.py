"""Загрузка кадров к черновику загрузки проверки по подписанному адресу (мимо Claude).

Модель не передаёт байты картинки аргументом инструмента, поэтому MCP
(`import_upload_photos`) выдаёт песочнице команду, а кадры идут сюда: из песочницы
Claude командой `curl -F n=… -F file=@…` (POST). Человеку адрес не показывается и
страницы ручной загрузки нет: действия с отчётом идут только через MCP.

**Доступ — только токен** (`domain.photo_upload_link`: подпись, пара «черновик,
пространство», без срока — до приёмки, D573). Куки админки здесь не читаются и
ничего не дают:
адреса открыты заслону входа (`auth.OPEN_ENDPOINTS`) и заслону происхождения
(`app._install_origin_gate`) ровно потому, что у такого запроса нет сессии, которую
чужая страница могла бы использовать, — CSRF-у нечего подделывать. Токен неверный
или чужой — 403; черновик уже принят, снят или не загруженный — 410;
подробностей в обоих ответах нет. Принятый черновик ловит и сама запись кадра:
замок строки в `db.imports.add_photo` пускает только `status = 'draft'`.

**Замена (`replace=1`, D627).** Прежние кадры записи снимаются только если ВСЕ новые
кадры запроса легли: сначала прикладываются новые, потом снимаются старые тем же путём,
что снятие кадра на вычитке (`revision.detach_photo`). Любой отказ — уже лёгшие новые
снимаются обратно, старые не тронуты, ответ несёт `replaced: false`. Не вышло снять
старый — оба на месте и это сказано: доказательство важнее аккуратности.

Кадр проверяется по сигнатуре байт (`db.photo_intake`), HEIC читается как JPEG,
в хранилище ложится сжатая копия — тот же путь, что у `import_add_photo`.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from flask import Flask, Response, jsonify, make_response, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.db import imports as db_imports
from src.db import previews as db_previews
from src.db.config import load_storage_settings
from src.db.errors import ConfigError as DbConfigError
from src.db.errors import DbError, HistoryImportError, ReviseError
from src.db.models import UPLOADED_ORIGINS
from src.db.photo_intake import sniff_image
from src.db.space import acting_space
from src.db.storage import PhotoStorage, S3PhotoStorage
from src.domain import photo_upload_link

from . import revision
from .config import Settings

logger = logging.getLogger(__name__)

PATH = "/photo-upload/<token>"
POST_ENDPOINT = "photo_upload_post"
ENDPOINTS = frozenset({POST_ENDPOINT})

#: Предел тела запроса: несколько кадров с телефона за раз.
MAX_REQUEST_BYTES = 25 * 1024 * 1024
#: Предел одного кадра: фото с телефона бывает до 10 МБ.
MAX_FILE_BYTES = 12 * 1024 * 1024
#: Поля формы и границы частей поверх самих файлов.
FORM_OVERHEAD_BYTES = 64 * 1024
#: Номер находки в черновике: те же пределы, что у инструментов MCP.
MAX_N = 999
#: Запросов в минуту с одного токена: песочница шлёт пачку кадров.
PER_MINUTE = 30
#: Значения поля `replace`, включающие замену кадров записи (D627).
REPLACE_VALUES = frozenset({"1", "true"})
WINDOW_SEC = 60.0
SWEEP_AFTER = 256


class _TokenRate:
    """Скользящее окно по отпечатку токена, в памяти процесса. Потокобезопасно.

    Ключ — отпечаток, а не сам токен: счётчик живёт в памяти, и дамп её не
    должен приносить готовые ссылки. Свой, а не `mcp.ratelimit`: блоки `web` и
    `mcp` друг друга не импортируют.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: dict[str, deque[float]] = {}

    def allow(self, token: str) -> bool:
        key = hashlib.sha256(token.encode()).hexdigest()[:16]
        now = self._clock()
        with self._lock:
            stamps = self._seen.setdefault(key, deque())
            while stamps and now - stamps[0] >= WINDOW_SEC:
                stamps.popleft()
            if len(stamps) >= PER_MINUTE:
                return False
            stamps.append(now)
            if len(self._seen) > SWEEP_AFTER:
                for k in [k for k, v in self._seen.items() if not v or now - v[-1] >= WINDOW_SEC]:
                    del self._seen[k]
            return True


RATE = _TokenRate()


@dataclass
class _Outcome:
    attached: list[dict[str, object]] = field(default_factory=list)
    refused: list[dict[str, object]] = field(default_factory=list)
    #: Только при `replace=1`: прежние кадры записи сняты (`True`) или остались (`False`).
    replaced: bool | None = None


def _storage() -> PhotoStorage:
    return S3PhotoStorage(load_storage_settings(), fail_fast=True)


def _plain(status: int) -> Response:
    """Отказ без подробностей: ни причины, ни имени черновика."""
    ответ = make_response("", status)
    ответ.headers["Cache-Control"] = "no-store"
    return ответ


def _guarded(response: Response) -> Response:
    """Ответ с адресом токена не должен утекать ни в кэш, ни в Referer."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _is_open_draft(grant: photo_upload_link.UploadGrant) -> bool:
    """Черновик загрузки своего пространства, ещё не принятый и не снятый."""
    head = db_imports.import_head(grant.inspection_id, tenant=grant.tenant)
    return (
        head is not None
        and head.origin in UPLOADED_ORIGINS
        and head.status == "draft"
        and not head.retracted
    )


def _frames_of(grant: photo_upload_link.UploadGrant, n: int) -> list[str]:
    """Кадры записи `n` с копией — то, что `replace` заменяет. Нет записи — пусто."""
    return list(db_previews.finding_frames(grant.inspection_id, n, tenant=grant.tenant))


def _swap(
    grant: photo_upload_link.UploadGrant,
    итог: _Outcome,
    n: int,
    *,
    old: list[str],
    new: list[str],
    storage: PhotoStorage,
) -> None:
    """Довести замену: все новые легли — снять старые; иначе откатить новые (D627)."""
    if итог.refused or not итог.attached:
        # «Всё или ничего»: лёгшие новые не остаются, старые на месте.
        for кадр, запись in zip(new, итог.attached, strict=True):
            try:
                revision.detach_photo(
                    grant.inspection_id, кадр, tenant=grant.tenant, storage=storage
                )
                причина = "not kept: another photo of this upload was refused, old photos stay"
            except (ReviseError, DbError):
                logger.warning("замена кадров: новый кадр не откатился, лежит рядом со старыми")
                причина = "kept next to the old photos (rollback failed)"
            итог.refused.append({**запись, "reason": причина})
        итог.attached = []
        итог.replaced = False
        return
    for кадр in old:
        try:
            revision.detach_photo(grant.inspection_id, кадр, tenant=grant.tenant, storage=storage)
        except (ReviseError, DbError) as exc:
            logger.warning("замена кадров: старый кадр не снят: %r", exc)
            итог.replaced = False
            итог.refused.append(
                {
                    "file": None,
                    "n": n,
                    "reason": "an old photo could not be removed; old and new photos are both kept",
                }
            )
            return
    итог.replaced = True


def _attach(grant: photo_upload_link.UploadGrant, n: int, *, replace: bool = False) -> _Outcome:
    """Приложить все файлы запроса к находке `n`; каждый — своим итогом.

    `replace` — после приложения прежние кадры записи заменяются новыми (`_swap`).
    """
    итог = _Outcome()
    файлы = [f for f in request.files.getlist("file") if f.filename or f.content_length]
    if not файлы:
        итог.refused.append({"file": None, "n": n, "reason": "no file in the request"})
        итог.replaced = False if replace else None
        return итог
    try:
        хранилище = _storage()
    except DbConfigError:
        for файл in файлы:
            итог.refused.append(
                {"file": файл.filename, "n": n, "reason": "photo storage is not configured"}
            )
        итог.replaced = False if replace else None
        return итог
    прежние = _frames_of(grant, n) if replace else []
    новые: list[str] = []
    for файл in файлы:
        имя = файл.filename or ""
        данные = файл.stream.read(MAX_FILE_BYTES + 1)
        причина = _refusal(данные)
        if причина is None:
            try:
                новые.append(
                    db_imports.add_photo(
                        grant.inspection_id, n, tenant=grant.tenant, data=данные, storage=хранилище
                    )
                )
            except HistoryImportError as exc:
                причина = str(exc)
        if причина is None:
            итог.attached.append({"file": имя, "n": n})
        else:
            итог.refused.append({"file": имя, "n": n, "reason": причина})
    if replace:
        _swap(grant, итог, n, old=прежние, new=новые, storage=хранилище)
    return итог


def _refusal(data: bytes) -> str | None:
    """Почему кадр не берётся (по байтам, не по имени), или `None`."""
    if not data:
        return "empty file"
    if len(data) > MAX_FILE_BYTES:
        return f"file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
    if sniff_image(data) is None:
        return "not an image (expected JPEG, PNG, WebP or HEIC)"
    return None


def install(app: Flask, conf: Settings) -> None:
    """Повесить адреса загрузки. Ключ подписи — тот же `WEB_SECRET_KEY`, что у MCP."""

    def _grant(token: str) -> photo_upload_link.UploadGrant | None:
        if conf.secret_key_is_ephemeral:
            # Ключ этого запуска MCP не знает: подписанная им ссылка здесь не проверится.
            return None
        return photo_upload_link.verify(conf.secret_key, token)

    @app.post(PATH, endpoint=POST_ENDPOINT)
    def photo_upload_post(token: str) -> Response:
        grant = _grant(token)
        if grant is None:
            return _plain(403)
        if not RATE.allow(token):
            return _plain(429)
        request.max_content_length = MAX_REQUEST_BYTES + FORM_OVERHEAD_BYTES
        try:
            n_raw = request.form.get("n", "")
            if not (n_raw.isascii() and n_raw.isdigit() and 1 <= int(n_raw) <= MAX_N):
                return _json({"error": "n must be the finding number (1..999)"}, 400)
            n = int(n_raw)
            with acting_space(grant.tenant):
                if not _is_open_draft(grant):
                    return _plain(410)
                replace = request.form.get("replace", "") in REPLACE_VALUES
                итог = _attach(grant, n, replace=replace)
        except RequestEntityTooLarge:
            return _json({"error": "request is larger than the limit"}, 413)
        except DbError:
            logger.warning("загрузка кадров по ссылке: база недоступна")
            return _plain(503)
        тело: dict[str, object] = {"attached": итог.attached, "refused": итог.refused}
        if итог.replaced is not None:
            тело["replaced"] = итог.replaced
        return _json(тело, 200 if итог.attached else 422)


def _json(body: dict[str, object], status: int) -> Response:
    ответ = jsonify(body)
    ответ.status_code = status
    return _guarded(ответ)
