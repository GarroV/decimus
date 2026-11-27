"""Работа по проверке: исходные файлы и общая лента комментариев в карточке."""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from collections.abc import Callable
from typing import Any

from flask import Flask, abort, redirect, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import inspection_followup as store
from src.db.config import load_action_plan_settings, load_storage_settings
from src.db.errors import DbError, StorageError
from src.db.storage import S3PhotoStorage, key_of_uri

from . import auth, guard, inspections, ui_lang
from .config import Settings
from .origin import refuse_foreign_origin
from .texts import t

log = logging.getLogger(__name__)


def card_context(inspection_id: str, *, finalized: bool, retracted: bool) -> dict[str, Any]:
    """Одинаковый блок для полной карточки и панели реестра."""
    if not finalized:
        return {"work_visible": False}
    try:
        page = store.list_entries(
            inspection_id,
            reach=auth.current_reach(),
            before=request.args.get("work_before"),
            as_admin=inspections.sees_retracted(auth.current_reach()),
        )
        known = True
    except (DbError, ValueError):
        page, known = store.Page(), False
    return {
        "work_visible": True,
        "work_page": page,
        "work_known": known,
        "work_may_add": known and not retracted and guard.may("inspection.followup"),
        "work_max_mb": load_action_plan_settings().max_bytes // (1024 * 1024),
    }


def install(
    app: Flask, conf: Settings, *, render_card: Callable[[str], str | tuple[str, int]]
) -> None:
    """Запись и скачивание в охвате самой проверки, независимо от паузы электронных планов."""

    @app.post("/inspections/<inspection_id>/work")
    @guard.action("inspection.followup")
    def inspection_work_add(inspection_id: str) -> Response | str | tuple[str, int]:
        refuse_foreign_origin()
        lang = ui_lang.request_lang(conf.ui_lang)
        # Отказ до чтения multipart и обращения к хранилищу.
        detail = inspections.load_card(inspection_id, reach=auth.current_reach())
        if detail is None:
            abort(404)
        if detail.inspection.on_review or detail.inspection.retracted:
            return t("work.error.inspection", lang), 409
        limit = load_action_plan_settings().max_bytes
        request.max_content_length = limit + 64 * 1024
        try:
            body = request.form.get("body", "")
            upload = request.files.get("file")
            data = upload.read(limit + 1) if upload and upload.filename else None
            account = auth.current_account()
            if account is None:
                abort(403)
            store.append(
                inspection_id,
                reach=auth.current_reach(),
                author=(
                    (account.display_name or "").strip()
                    or (account.email or "").strip()
                    or account.login
                )[:200],
                body=body,
                file_name=upload.filename or "" if upload else "",
                data=data,
                max_bytes=limit,
                finding_id=request.form.get("repair") or None,
            )
        except RequestEntityTooLarge:
            return t("work.error.file", lang, mb=limit // (1024 * 1024)), 413
        except store.FollowupRefused as exc:
            key = str(exc)
            return t(f"work.error.{key}", lang, mb=limit // (1024 * 1024)), 400
        except (DbError, StorageError):
            log.warning("Не сохранены материалы проверки %s", inspection_id)
            return t("work.error.save", lang), 503
        if request.headers.get("X-Panel") == "1":
            return render_card(inspection_id)
        return redirect(
            url_for(
                "card",
                inspection_id=inspection_id,
                lang=lang,
                repair=request.form.get("repair") or None,
            )
            + (
                "#repair-" + request.form["repair"]
                if request.form.get("repair")
                else "#inspection-work"
            ),
            code=303,
        )

    @app.get("/inspections/<inspection_id>/work/<entry_id>/file")
    def inspection_work_file(inspection_id: str, entry_id: str) -> Response | tuple[str, int]:
        lang = ui_lang.request_lang(conf.ui_lang)
        try:
            uuid.UUID(inspection_id)
            uuid.UUID(entry_id)
        except ValueError:
            abort(404)
        try:
            entry = store.get_file(
                inspection_id,
                entry_id,
                reach=auth.current_reach(),
                as_admin=inspections.sees_retracted(auth.current_reach()),
            )
            if entry is None or entry.storage_path is None:
                abort(404)
            data = S3PhotoStorage(load_storage_settings()).get(key_of_uri(entry.storage_path))
            if len(data) != entry.size_bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise StorageError("File integrity mismatch")
        except (DbError, StorageError):
            log.warning("Недоступен файл материалов проверки %s/%s", inspection_id, entry_id)
            return t("work.error.download", lang), 503
        response = send_file(
            io.BytesIO(data),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=entry.file_name,
            max_age=0,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/inspections/<inspection_id>/work/<entry_id>/preview")
    def inspection_work_preview(inspection_id: str, entry_id: str) -> Response | tuple[str, int]:
        lang = ui_lang.request_lang(conf.ui_lang)
        try:
            entry = store.get_file(
                inspection_id,
                entry_id,
                reach=auth.current_reach(),
                as_admin=inspections.sees_retracted(auth.current_reach()),
            )
            if entry is None or entry.preview_path is None:
                abort(404)
            data = S3PhotoStorage(load_storage_settings()).get(key_of_uri(entry.preview_path))
        except ValueError:
            abort(404)
        except (DbError, StorageError):
            return t("work.error.download", lang), 503
        response = send_file(io.BytesIO(data), mimetype="image/jpeg", max_age=0)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
