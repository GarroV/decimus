"""Гость УК (D440): вся сеть только на чтение — один заслон на всё приложение.

Заслон `before_request`, а не проверка в каждом маршруте: любая запись гостя —
403 с момента появления маршрута, и закрывать новый не придётся помнить. Кнопки
у гостя прячет разметка (`read_only` в шаблонах), но скрытие — не защита: адрес
известен, и POST набирается руками. Защита — этот заслон.

Читает гость разделы `GUEST_SECTIONS` (`sections.py`): обзор, проверки и отчёты,
страну, рейтинги и свою карточку. Остальное (методика, действия УК) — 404, как
закрытый раздел партнёру. Дела самого человека — выход, свой пароль, подключение
Claude и отзыв подключения — он делает: это не запись в сеть, а его же учётка;
что Claude вправе читать от его имени, решает матрица MCP (`src/mcp/policy.py`).
"""

from __future__ import annotations

from flask import Flask, abort, request

from src.domain.tenants import is_hq_guest

from . import auth, oauth
from .sections import GUEST_SECTIONS, current_section, section

#: Безопасные методы: чужой раздел на чтение — 404, на запись — 403.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def own_paths() -> frozenset[str]:
    """Дела самого человека, которые гость делает и без права писать в сеть."""
    users_path = section("users").path
    return frozenset(
        {
            auth.LOGOUT_PATH,
            f"{users_path}/password",
            f"{users_path}/claude-revoke",
            oauth.AUTHORIZE_PATH,
        }
    )


def install(app: Flask) -> None:
    """Повесить заслон. Ставится после опознания: без вошедшего он ничего не решает."""
    разрешено = own_paths()

    @app.before_request
    def _гость_только_читает() -> None:
        if request.endpoint in auth.OPEN_ENDPOINTS or request.routing_exception is not None:
            return
        вошедший = auth.current_account()
        if вошедший is None or not is_hq_guest(вошедший.role, вошедший.tenant):
            return
        путь = request.path
        if request.method not in _READ_METHODS:
            if путь not in разрешено:
                abort(403)
            return
        if путь in ("/", oauth.AUTHORIZE_PATH):
            return
        # Форма заведения пиццерии — запись, а не чтение: гостю её не показывают.
        if current_section(путь) not in GUEST_SECTIONS or путь.endswith("/units/new"):
            abort(404)
