"""Возврат после подтверждения второго шага: куда вести и что принимать (D670).

Отказ действия над ключом («подтвердите второй шаг») ведёт на «Вход и защита» с адресом той
вкладки, откуда пришли; верный код или ключ возвращает туда же. Принимается только свой путь —
проверка одна, `reauth.safe_back`: новой проверки адресов здесь нет намеренно.
"""

from __future__ import annotations

from flask import request

from .sections import section

#: Ключ текста отказа «второй шаг не подтверждён в этой сессии» и «второй шаг не включён».
PROVE_KEY = "keys.err.prove_step"
NO_FACTOR_KEY = "keys.err.no_factor"

#: Параметр адреса и поле формы, где едет путь возврата.
NEXT_PARAM = "next"


def checked(raw: str | None) -> str:
    """Путь возврата как есть, если он свой и допустимый; иначе пусто (прежнее поведение)."""
    from . import reauth

    путь = (raw or "").strip()
    return путь if путь and reauth.safe_back(путь) == путь else ""


def _tab_path(tab: str) -> str:
    """Путь вкладки «Администрирования» без префикса площадки, со страной, если она выбрана."""
    from . import administration
    from .dodois_screen import _country_from_form

    страна = _country_from_form() if tab == "dodois" else None
    полный = administration.url(tab, country=страна or "")
    return полный[len(request.script_root) :]


def refusal_href(key: str) -> str:
    """Куда ведёт действие у отказа `key`; пусто — у этого отказа действия нет."""
    base = f"{request.script_root}{section('settings').path}/security"
    if key == NO_FACTOR_KEY:
        return base
    if key != PROVE_KEY:
        return ""
    from .connections_screen import return_tab
    from .dodois_screen import ISSUE_ACTION

    tab = "dodois" if request.endpoint == ISSUE_ACTION else return_tab()
    вернуться = checked(_tab_path(tab))
    return f"{base}?{NEXT_PARAM}={_quote(вернуться)}" if вернуться else base


def _quote(path: str) -> str:
    from urllib.parse import quote

    return quote(path, safe="")
