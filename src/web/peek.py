"""Переключатель пространств главного админа: дверь и заслон «только просмотр» (D726).

Главный админ УК одним нажатием смотрит на сервис глазами партнёра. Правила — в
`src/domain/peek.py`; здесь три вещи:

* **Дверь** `POST /space/peek` (поле `target`: код пространства из перечня или `HQ`).
  Отказ тому, кто не главный админ УК после второй ступени, — 403, независимо от того,
  показана ли кнопка. Состояние пишется на сессию в базе (`web_session_peeks`, `0123`).
  Вернуться — `target=HQ`, возврат всегда на главную, а не на произвольный адрес.
* **Заслон записи.** Пока переключатель включён, любой изменяющий запрос отвечает 403
  со страницей «Только просмотр» — одним `before_request`, а не в каждом маршруте.
  Исключения: само переключение и выход. Сюда же — GET, который пишет (`WRITING_GETS`).
* **Контекст шаблонов**: показывать ли переключатель, куда он ведёт, включён ли.

Журнал: переключение пишется общей точкой журнала действий (`web/journal.py`) как
действие НАСТОЯЩЕЙ учётки — главного админа УК.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, g, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.errors import DbError
from src.db.web_access import set_acting_tenant
from src.domain import peek

from . import auth, guard
from .journal import WRITE_METHODS

ENDPOINT = "space_peek"
PATH = "/space/peek"

#: Что открыто и при включённом переключателе: само переключение и выход.
_ALWAYS_ALLOWED = frozenset({ENDPOINT, "logout"})


def _second_step_ok(account: Any) -> bool:
    """Вторая ступень настоящей учётки пройдена — или способов входа у неё нет вовсе."""
    return bool(account.passed_second_step or not account.has_second_factor)


def may_switch(account: Any) -> bool:
    """Показывать ли переключатель и пускать ли к двери: по НАСТОЯЩЕЙ учётке."""
    if account is None:
        return False
    real = account.actual
    return peek.may_peek(role=real.role, tenant=real.tenant, second_step_ok=_second_step_ok(real))


def _readonly_page() -> tuple[str, int]:
    return render_template("peek/readonly.html"), 403


def install(app: Flask) -> None:
    """Повесить заслон записи, дверь и контекст. Ставится ПОСЛЕ заслона входа."""

    @app.before_request
    def _only_view() -> tuple[str, int] | None:
        account = auth.current_account()
        if account is None or not account.is_peeking:
            return None
        if request.endpoint in _ALWAYS_ALLOWED:
            return None
        writes = request.method in WRITE_METHODS or request.endpoint in guard.WRITING_GETS
        return _readonly_page() if writes else None

    @app.context_processor
    def _peek_context() -> dict[str, Any]:
        account = auth.current_account()
        active = account is not None and account.is_peeking
        return {
            "peek_can": may_switch(account),
            "peek_spaces": peek.PEEK_SPACES,
            "peek_home": peek.HOME,
            "peek_active": account.tenant if active and account is not None else None,
            "peek_name": (account.acting_name or account.tenant) if active and account else "",
            "peek_path": PATH,
        }

    @app.post(PATH, endpoint=ENDPOINT)
    def space_peek() -> Response | tuple[str, int]:
        """Переключить пространство просмотра у своей сессии. Только главный админ УК."""
        account = auth.current_account()
        if not may_switch(account):
            return guard.forbidden()
        try:
            target = peek.target_of(request.form.get("target"))
        except ValueError:
            return "", 400
        token = g.get(auth.SESSION_TOKEN)
        if not token:
            return guard.forbidden()
        try:
            done = set_acting_tenant(str(token), target)
        except DbError:
            return "", 503
        if not done:
            return guard.forbidden()
        return redirect(url_for("home"))
