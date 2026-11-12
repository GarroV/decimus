"""«Начало работы» и тур по интерфейсу: карточка, пометки человека, данные для оболочки (D756).

Что здесь, а что нет:

* решение «какие шаги и что сделано» — `onboarding.py` (ядро, покрыто тестом);
* чтение фактов — `onboarding_facts.py`;
* шаги тура и их тексты — `onboarding_tour.py`;
* здесь — карточка для «Главной», данные тура для каждой страницы и один маршрут
  `POST /settings/onboarding` (пометки своей учётки: тур пройден, карточка скрыта).

**Открытое демо (D524).** Учётки ролей общие: пометка в профиле одному посетителю меняла бы
экран всем остальным, а действия настройки (бот, Claude, второй шаг, новые люди) там
закрыты. Поэтому карточки в демо нет, а тур есть — для партнёрской роли демо он открывается
сам, и отметка «пройден» лежит в куке браузера (как отбор стран, `country_filter.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import Flask, current_app, make_response, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import web_own_profile
from src.db.errors import DbError

from . import auth, onboarding, onboarding_facts, onboarding_tour
from .origin import over_https, refuse_foreign_origin
from .sections import section, visible_sections
from .texts import t
from .ui_lang import _DEMO_FLAG, _safe_back

log = logging.getLogger(__name__)

#: Кука открытого демо: тур уже показан в этом браузере.
DEMO_TOUR_COOKIE = "decimus_demo_tour"
_DEMO_TOUR_MAX_AGE_S = 365 * 24 * 3600
ENDPOINT = "settings_onboarding"
#: Запрос фоном из браузера (тур): ответ без тела, а не переадресация.
_FETCH_HEADER = "X-Requested-With"


@dataclass(frozen=True)
class Row:
    """Строка карточки: шаг решения и готовые тексты на языке страницы."""

    key: str
    state: str
    required: bool
    title: str
    text: str
    cta: str
    href: str


@dataclass(frozen=True)
class Card:
    """Карточка «Начало работы»: строки, счёт, скрыта ли у человека."""

    rows: tuple[Row, ...]
    done: int
    total: int
    hidden: bool
    finished: bool
    action: str


def is_demo() -> bool:
    """Стенд открытого демо: пометки в куке, карточки нет."""
    return bool(current_app.config.get(_DEMO_FLAG))


def _page(path: str, lang: str, **query: str) -> str:
    params = "&".join([f"lang={lang}", *(f"{k}={v}" for k, v in query.items())])
    return f"{request.script_root}{path}?{params}"


def _href(key: str, lang: str) -> str:
    """Куда ведёт кнопка шага: туда, где его делают. Пусто — делать нечего самому."""
    where = {
        onboarding.BOT: lambda: _page(section("settings").path, lang, tile="bot") + "#connections",
        onboarding.PEOPLE: lambda: _page(section("administration").path, lang, tab="people"),
        onboarding.UNITS: lambda: _page(section("country").path, lang),
        onboarding.CHECKLIST: lambda: _page(section("admin").path, lang),
        onboarding.CLAUDE: lambda: (
            _page(section("settings").path, lang, tile="claude") + "#connections"
        ),
    }.get(key)
    return where() if where else ""


def _row(step: onboarding.Step, lang: str) -> Row:
    base = f"onboarding.step.{step.key}"
    href = _href(step.key, lang)
    # Кнопка у шага, который ждёт управляющую компанию, — «Открыть», а не «Сделайте»:
    # у «Страны» и «Методики» есть куда посмотреть, у остального — нет.
    return Row(
        key=step.key,
        state=step.state,
        required=step.required,
        title=t(f"{base}.title", lang),
        text=t(f"{base}.text", lang),
        cta=t(f"{base}.cta", lang) if href else "",
        href=href,
    )


def card(lang: str) -> Card | None:
    """Карточка для «Главной» вошедшего — или `None`, если показывать нечего.

    Не показывается: управляющей компании, в демо, при просмотре чужими глазами, скрытая
    человеком и уже завершённая. `?start=1` (пункт меню учётки) показывает её всегда, с
    тем, что сделано.
    """
    account = auth.current_account()
    tenant = auth.current_tenant()
    if account is None or is_demo() or account.is_peeking or not onboarding_tour.is_partner(tenant):
        return None
    forced = request.args.get("start") == "1"
    hidden = account.start_hidden_at is not None
    if hidden and not forced:
        return None
    facts = onboarding_facts.person_facts(account, tenant=tenant)
    steps = onboarding.steps_for(
        account.role, tenant, facts, bot_available=onboarding_facts.bot_available()
    )
    if not steps:
        return None
    finished = not onboarding.needs_attention(steps)
    if finished and not forced:
        return None
    required = [s for s in steps if s.required]
    return Card(
        rows=tuple(_row(step, lang) for step in steps),
        done=sum(1 for s in required if s.state == onboarding.DONE),
        total=len(required),
        hidden=hidden,
        finished=finished,
        action=f"{request.script_root}{section('settings').path}/onboarding",
    )


def shell_context(account: object | None, lang: str) -> dict[str, object]:
    """Данные тура для каждой страницы: шаги, подписи, адреса и признак автозапуска."""
    if account is None:
        return {"tour": None}
    tenant = auth.current_tenant()
    demo_seen = bool(request.cookies.get(DEMO_TOUR_COOKIE)) if is_demo() else None
    autostart = request.endpoint == "overview" and onboarding_tour.should_autostart(
        tenant=tenant,
        seen=getattr(account, "tour_seen_at", None) is not None,
        peeking=bool(getattr(account, "is_peeking", False)),
        demo_seen=demo_seen,
    )
    base = request.script_root
    return {
        "tour": onboarding_tour.config(
            visible_sections(account),
            lang,
            tenant=tenant,
            autostart=autostart,
            settings_href=_page(section("settings").path, lang, tile="claude") + "#connections",
            done_url=f"{base}{section('settings').path}/onboarding",
            lib_js=url_for("static", filename="vendor/driver/driver.js"),
            lib_css=url_for("static", filename="vendor/driver/driver.css"),
            tour_css=url_for("static", filename="decimus-tour.css"),
        ),
        "start_link": (
            f"{base}{section('overview').path}?lang={lang}&start=1"
            if onboarding_tour.is_partner(tenant) and not is_demo()
            else None
        ),
    }


def install(app: Flask) -> None:
    """Маршрут пометок: `POST /settings/onboarding` (дело самого человека над своей учёткой)."""
    path = f"{section('settings').path}/onboarding"

    @app.post(path, endpoint=ENDPOINT)
    def settings_onboarding() -> Response:
        """Отметить тур пройденным (`tour=1`) и скрыть/вернуть карточку (`start=hide|show`)."""
        refuse_foreign_origin()
        tour = request.form.get("tour") == "1"
        start = (request.form.get("start") or "").strip() or None
        if start is not None and start not in web_own_profile.START_ACTIONS:
            return make_response("", 400)
        fetched = request.headers.get(_FETCH_HEADER) == "fetch"
        back = _safe_back(request.form.get("next")) or section("overview").path
        response: Response = (
            make_response("", 204) if fetched else redirect(f"{request.script_root}{back}")
        )
        if is_demo():
            if tour:
                response.set_cookie(
                    DEMO_TOUR_COOKIE,
                    "1",
                    max_age=_DEMO_TOUR_MAX_AGE_S,
                    expires=datetime.now(UTC) + timedelta(seconds=_DEMO_TOUR_MAX_AGE_S),
                    httponly=True,
                    samesite="Lax",
                    secure=over_https(),
                    path="/",
                )
            return response
        try:
            saved = web_own_profile.set_onboarding(
                auth.current_session_token(), tour_seen=tour, start=start
            )
        except DbError:
            log.exception("онбординг: пометку сохранить не удалось")
            return make_response("", 503) if fetched else response
        return response if saved else make_response("", 401 if fetched else 403)
