"""Раздел «Действия»: экшн-планы и предписания — один экран у УК и партнёра (D526, D527).

Одно устройство для обеих сторон: вкладки «Экшн-планы» и «Предписания»,
слева список с отбором, справа панель выбранной строки (`?tab=…&id=…`, тот же
каркас, что у «Проверок» и «Пиццерий»: `_split_page.html`, `split.js`). Сторона
меняет объём сведений и кнопки внутри панели, а не меню и раскладку (D526).

Заслонов этот модуль не держит и не ослабляет: каждая вкладка читает данные
только через свои двери с охватом вошедшего (`action_plans.screen`,
`prescriptions.screen`), а записи ведут прежние маршруты со своими заслонами.
Здесь — раскладка, выбор вкладки и строки и переадресации со старых адресов.

Вкладки не импортируются отсюда: каждая регистрирует себя на сборке
(`register`), поэтому `action_plans` и `prescriptions` вызывают `respond` без
круговой зависимости.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Flask, current_app, render_template, request, url_for
from flask import redirect as flask_redirect
from werkzeug.wrappers import Response

from . import ui_lang
from .config import Settings
from .sections import section
from .texts import t

#: Заголовок, которым `split.js` отличает действие из панели от обычной формы —
#: тот же, что `app.PANEL_HEADER`.
PANEL_HEADER = "X-Panel"

TAB_PLANS = "plans"
TAB_RX = "prescriptions"
TABS = (TAB_PLANS, TAB_RX)

#: Длина кода строки из адреса — с запасом на uuid; длиннее — не код.
ID_MAX = 64

#: Параметры отбора, которые переживают переадресацию со старых адресов.
KEPT_ARGS = ("lang", "country", "queue", "accepted", "closed")

_TABS_KEY = "decimus.actions_tabs"


@dataclass(frozen=True)
class Tab:
    """Вкладка раздела: список с отбором и панель выбранной строки.

    `screen(lang)` — всё для списка и полосы отбора; `panel(item_id, notice=,
    failure=, gmail=)` — всё для панели; в ответе всегда `item` (строка или
    `None`) и `failed` (база не ответила — панель говорит об этом, список
    остаётся).
    """

    screen: Callable[[str], dict[str, Any]]
    panel: Callable[..., dict[str, Any]]
    #: Ответ на действие над строкой, которой нет в охвате (404 страницей вкладки).
    missing: Callable[[], tuple[str, int]]


def register(app: Flask, key: str, tab: Tab) -> None:
    """Подключить вкладку: вызывается на сборке из `install` вкладки."""
    app.extensions.setdefault(_TABS_KEY, {})[key] = tab


def _tab(key: str) -> Tab:
    return current_app.extensions[_TABS_KEY][key]


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def tab_of(raw: str | None) -> str:
    """Вкладка из адреса; незнакомое значение — первая вкладка, а не отказ."""
    return raw if raw in TABS else TAB_PLANS


def panel_link(tab: str, item_id: str, *, lang: str, **extra: str) -> str:
    """Адрес экрана с открытой панелью строки — куда возвращаются после действия."""
    kept = {k: v for k, v in extra.items() if v}
    return url_for("actions", tab=tab, id=item_id, lang=lang, **kept)


def redirect_to_screen(tab: str, item_id: str = "") -> Response:
    """Переадресация со старого адреса: тот же отбор, нужная вкладка, при `id` — панель."""
    params = {k: request.args[k] for k in KEPT_ARGS if request.args.get(k)}
    if item_id:
        params["id"] = item_id
    return flask_redirect(url_for("actions", tab=tab, **params), code=303)


def _tab_links(lang: str, country: str) -> dict[str, str]:
    """Адреса вкладок: отбор страны переносится, остальное у вкладок своё."""
    kept = {k: v for k, v in {"lang": lang, "country": country}.items() if v}
    return {key: url_for("actions", tab=key, **kept) for key in TABS}


def _page(conf: Settings, tab: str, picked: str, panel: dict[str, Any]) -> dict[str, Any]:
    lang = _lang(conf)
    screen = _tab(tab).screen(lang)
    return {
        **screen,
        **panel,
        "tab": tab,
        "picked": picked,
        "split_open": bool(picked),
        "split_back": screen["select_url"](id=""),
        "tab_links": _tab_links(lang, screen.get("country", "")),
        "panel_retry": screen["select_url"](id=picked),
        "actions_path": section("actions").path,
        "registry_path": section("registry").path,
    }


def respond(
    conf: Settings,
    tab: str,
    *,
    item_id: str,
    notice: str | None = None,
    failure: str | None = None,
    gmail: str = "",
    status: int = 200,
) -> str | tuple[str, int]:
    """Ответ экрана «Действия» — на чтение и на действие в панели.

    Действие из панели (`split.js`, заголовок `X-Panel`) ждёт обратно только
    панель с итогом — со статусом 200 и для отказа, иначе скрипт примет отказ за
    обрыв связи. Без скрипта форма получает страницу целиком и честный статус.
    Строки нет в охвате — тот же 404, что у несуществующей: чужое от пустого не
    отличить.
    """
    panel = _tab(tab).panel(item_id, notice=notice, failure=failure, gmail=gmail)
    posted = request.method == "POST"
    if posted and panel["item"] is None and not panel["failed"]:
        return _tab(tab).missing()
    if posted and request.headers.get(PANEL_HEADER) == "1":
        return render_template("actions/_panel_fragment.html", tab=tab, **panel)
    page = render_template("actions/index.html", **_page(conf, tab, item_id, panel))
    return (page, status) if status != 200 else page


def install(app: Flask, conf: Settings) -> None:
    """Повесить экран раздела. Вкладки регистрируют себя сами (`register`)."""

    @app.get(section("actions").path, endpoint="actions")
    def actions() -> str:
        tab = tab_of(request.args.get("tab"))
        picked = (request.args.get("id") or "").strip()[:ID_MAX]
        gmail = request.args.get("gmail") or ""
        saved = request.args.get("saved") == "1"
        notice = None
        if saved and tab == TAB_RX:
            notice = t("rx.saved", _lang(conf))
        panel = (
            _tab(tab).panel(picked, notice=notice, failure=None, gmail=gmail)
            if picked
            else _empty_panel()
        )
        return render_template("actions/index.html", **_page(conf, tab, picked, panel))


def _empty_panel() -> dict[str, Any]:
    return {"item": None, "failed": False, "notice": None, "failure": None, "gmail": ""}

