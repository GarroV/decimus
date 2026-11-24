"""Удаление людей: только главный админ, срок и повторная проверка прав — в БД."""

from flask import Flask, request
from flask import Response as FlaskResponse

from src.db import user_deletion
from src.db.errors import DbError

from . import access_policy, auth, guard
from .origin import refuse_foreign_origin
from .users_page import Flash, Show, people_scope, render
from .users_screen import _target, forbidden


def install(app: Flask, users_path: str) -> None:
    def change(*, cancel: bool) -> FlaskResponse | tuple[str, int]:
        refuse_foreign_origin()
        scope, actor = people_scope(), auth.current_account()
        if scope is None or scope.kind != access_policy.SUPER or actor is None:
            return forbidden()
        try:
            target = _target(scope, request.form.get("login", ""), request.form.get("tenant", ""))
            if target is None or target.id == actor.id:
                return forbidden()
            operation = user_deletion.cancel if cancel else user_deletion.schedule
            changed = operation(actor.id, target.id)
        except DbError:
            return render(Show(show_off=True, flash=Flash("users.delete.failed", False)), 409)
        key = "users.delete.cancelled" if cancel else "users.delete.scheduled"
        if not changed:
            key = "users.delete.unchanged"
        return render(Show(person=target.id, show_off=True, flash=Flash(key, changed)))

    @app.post(f"{users_path}/delete")
    @guard.action("people.manage")
    def delete_user() -> FlaskResponse | tuple[str, int]:
        return change(cancel=False)

    @app.post(f"{users_path}/cancel-deletion")
    @guard.action("people.manage")
    def cancel_user_deletion() -> FlaskResponse | tuple[str, int]:
        return change(cancel=True)
