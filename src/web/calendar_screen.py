"""Раздел «Календарь» (D497): сетка месяца с проверками и поездками (D505, D506).

Сетка — проверки по дате обхода (охват как у «Проверок») и поездки своего
пространства полосой по их дням. Поездка открывается панелью справа (каркас
`_split_page.html`, как карточка проверки): кто едет, страна, даты, статус,
заметка и план по дням.

Пространство поездок — строго своё (D505): чтение и запись идут с пространством
вошедшего, а база (`0074_trips.sql`) сама не отдаёт и не принимает чужих строк.
Кто что правит, решает матрица: `trip.plan` — любые поездки пространства,
`trip.own` — только где человек сам исполнитель (D506).
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any

from flask import Flask, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db import trips as tr
from src.db.directory import Unit, list_units
from src.db.errors import DbError, TripError
from src.db.trips import Draft, StepDraft, Trip

from . import accounts, auth, calendar_view, guard, registry_period, registry_view, ui_lang
from . import inspections as data
from .config import Settings
from .geo_names import country_title
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

PLAN = "trip.plan"
OWN = "trip.own"


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def _url(endpoint: str, **params: Any) -> str:
    return url_for(endpoint, **{к: з for к, з in params.items() if з})


def _parse_date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except ValueError:
        return None


def _parse_time(raw: str | None) -> time | None:
    try:
        return time.fromisoformat((raw or "").strip()[:5]) if (raw or "").strip() else None
    except ValueError:
        return None


def _tenant() -> str:
    вошедший = auth.current_account()
    if вошедший is None:
        raise RuntimeError("поездки без вошедшего: маршрут прошёл мимо заслона")
    return вошедший.tenant


def may_edit(trip: Trip | None) -> bool:
    """Может ли вошедший править эту поездку (`None` — завести новую)."""
    вошедший = auth.current_account()
    if вошедший is None:
        return False
    if guard.may(PLAN):
        return trip is None or trip.tenant == вошедший.tenant
    if not guard.may(OWN):
        return False
    return trip is None or trip.executor_user_id == вошедший.id


def _permit(trip: Trip | None) -> tuple[str, int] | None:
    """Спросить матрицу на запись; своё правило «только свои» — поверх неё."""
    чьё = None if trip is None else trip.tenant
    if guard.may(PLAN, чьё):
        return guard.permit(PLAN, чьё)
    отказ = guard.permit(OWN, чьё)
    if отказ is not None:
        return отказ
    вошедший = auth.current_account()
    if trip is not None and (вошедший is None or trip.executor_user_id != вошедший.id):
        return guard.forbidden()
    return None


def _units() -> tuple[Unit, ...]:
    try:
        return tuple(list_units(reach=auth.current_reach()))
    except DbError as exc:
        logger.warning("справочник для поездок не прочитан: %s", exc)
        return ()


def _people() -> dict[str, str]:
    """Логин → id действующих учёток своего пространства (подсказка «Кто едет»)."""
    try:
        строки = accounts.everyone(tenant=_tenant())
    except DbError as exc:
        logger.warning("люди пространства для поездок не прочитаны: %s", exc)
        return {}
    return {r.login: r.id for r in строки if r.disabled_at is None}


def _executor(name: str) -> tuple[str, str | None]:
    """Кто едет: админ вписывает любого (учётка узнаётся по логину), сотрудник — себя."""
    вошедший = auth.current_account()
    if вошедший is None:
        raise TripError("trip.err.space")
    if not guard.may(PLAN):
        return вошедший.login, вошедший.id
    имя = " ".join(name.split())
    люди = {логин.casefold(): (логин, ид) for логин, ид in _people().items()}
    найдено = люди.get(имя.casefold())
    return найдено if найдено is not None else (имя, None)


def _draft_from_form(units: tuple[Unit, ...]) -> Draft:
    имя, учётка = _executor(request.form.get("executor") or "")
    страна = (request.form.get("country") or "").strip().upper() or None
    if страна is not None and страна not in {u.country for u in units}:
        raise TripError("trip.err.country")
    return Draft(
        executor_name=имя,
        executor_user_id=учётка,
        country=страна,
        date_from=_parse_date(request.form.get("from")),
        date_to=_parse_date(request.form.get("to")),
        status=(request.form.get("status") or "planned").strip(),
        note=request.form.get("note") or "",
    )


def _step_from_form(units: tuple[Unit, ...]) -> StepDraft:
    точка = (request.form.get("unit") or "").strip() or None
    if точка is not None and точка not in {u.id for u in units}:
        raise TripError("trip.err.unit")
    return StepDraft(
        day=_parse_date(request.form.get("day")),
        at=_parse_time(request.form.get("at")),
        kind=(request.form.get("kind") or "").strip(),
        unit_id=точка,
        body=request.form.get("body") or "",
    )


def _reason(exc: TripError, lang: str) -> str:
    return t("trip.failed", lang, reason=t(exc.code, lang, **exc.params))


def _done_by_unit(trip: Trip) -> dict[tuple[str, date], str]:
    """(пиццерия, день) → буква состоявшейся проверки — для отметки в плане."""
    try:
        строки = data.load_dated(
            reach=auth.current_reach(), date_from=trip.date_from, date_to=trip.date_to
        )
    except DbError as exc:
        logger.warning("проверки дней поездки не прочитаны: %s", exc)
        return {}
    return {(r.unit_name, r.inspection_date): r.grade for r in строки}


def _trips_by_day(trips: tuple[Trip, ...]) -> dict[date, tuple[Trip, ...]]:
    по_дням: dict[date, list[Trip]] = {}
    for поездка in trips:
        for день in поездка.days:
            по_дням.setdefault(день, []).append(поездка)
    return {д: tuple(п) for д, п in по_дням.items()}


def _render(
    conf: Settings,
    *,
    selected: str = "",
    failure: str | None = None,
    form: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[str, int]:
    язык = _lang(conf)
    сегодня = date.today()
    период = registry_period.read(request.args, today=сегодня)

    def отбор(**изменения: str) -> str:
        return _url("calendar", **{**период.params(), "lang": язык, **изменения})

    месяцы = calendar_view.months_between(период.start, период.end, сегодня)
    конец = calendar_view.month_end(месяцы[-1])
    строки = data.load_dated(reach=auth.current_reach(), date_from=месяцы[0], date_to=конец)
    try:
        поездки = tr.list_trips(tenant=_tenant(), date_from=месяцы[0], date_to=конец)
        поездки_ок = True
    except DbError as exc:
        # Поездки не прочитались — сетка с проверками всё равно открывается,
        # а над ней строка, что поездок не видно (а не «поездок нет»).
        logger.warning("поездки не прочитаны: %s", type(exc).__name__)
        поездки, поездки_ок = (), False

    открыта: Trip | None = None
    if selected and selected != "new" and поездки_ок:
        открыта = tr.get_trip(selected, tenant=_tenant())
    новая = selected == "new" and may_edit(None)
    точки = _units() if (новая or открыта is not None) else ()

    def к_поездке(ид: str) -> str:
        return отбор(trip=ид)

    return render_template(
        "calendar/index.html",
        months=tuple(
            calendar_view.month_grid(м, строки, сегодня, trips=_trips_by_day(поездки))
            for м in месяцы
        ),
        total=sum(1 for r in строки if месяцы[0] <= r.inspection_date <= конец),
        trips_total=len(поездки),
        trips_failed=not поездки_ок,
        card_href=lambda row: _url("registry", inspection=row.id, lang=язык),
        day_href=lambda d: _url("registry", lang=язык, **{"from": d, "to": d}),
        trip_href=к_поездке,
        can_add_trip=may_edit(None),
        new_trip_href=отбор(trip="new"),
        split_open=новая or bool(selected),
        split_back=отбор(),
        trip=открыта,
        trip_new=новая,
        trip_missing=bool(selected) and not новая and открыта is None,
        trip_editable=may_edit(открыта) if открыта is not None else новая,
        trip_self_only=not guard.may(PLAN),
        trip_failure=failure,
        trip_form=form or {},
        trip_people=tuple(sorted(_people())) if (новая or открыта) and guard.may(PLAN) else (),
        trip_countries=tuple(sorted({u.country for u in точки if u.country})),
        trip_units=tuple(
            u
            for u in точки
            if открыта is None or not открыта.country or u.country == открыта.country
        ),
        trip_done=_done_by_unit(открыта) if открыта is not None else {},
        trip_kinds=tr.KINDS,
        trip_statuses=tr.STATUSES,
        trip_action=lambda *части: (
            "/".join((section("calendar").path, "trips", *части))
            + f"?{_query(период.params(), язык)}"
        ),
        country_title=lambda c: country_title(c, язык) or c,
        period=период,
        period_title=registry_view.period_title(период, язык),
        period_prev=registry_view.period_link(период, -1, отбор),
        period_next=registry_view.period_link(период, 1, отбор),
        period_quick=registry_view.period_quick(период, сегодня, язык, отбор),
        period_hidden={"lang": язык},
    ), status


def _query(params: dict[str, str], lang: str) -> str:
    from urllib.parse import urlencode

    return urlencode({**{к: з for к, з in params.items() if з}, "lang": lang})


def _back(trip_id: str = "") -> Response:
    """Назад на «Календарь» с тем же периодом и языком; `trip_id` — открыть поездку."""
    параметры = {к: request.args.get(к, "") for к in ("from", "to", "period", "lang")}
    return redirect(_url("calendar", trip=trip_id, **параметры), code=303)


def install(app: Flask, conf: Settings) -> None:
    """Повесить «Календарь» и маршруты поездок."""
    путь = section("calendar").path

    @app.get(путь)
    def calendar() -> tuple[str, int]:
        return _render(conf, selected=(request.args.get("trip") or "").strip()[:40])

    @app.post(f"{путь}/trips", endpoint="trip_create")
    @guard.action(PLAN, OWN, object_in_route=True)
    def trip_create() -> Response | tuple[str, int]:
        refuse_foreign_origin()
        отказ = _permit(None)
        if отказ is not None:
            return отказ
        язык = _lang(conf)
        вошедший = auth.current_account()
        try:
            ид = tr.create_trip(
                _draft_from_form(_units()),
                tenant=_tenant(),
                actor_id=вошедший.id if вошедший else "",
            )
        except TripError as exc:
            return _render(
                conf,
                selected="new",
                failure=_reason(exc, язык),
                form=dict(request.form),
                status=400,
            )
        return _back(ид)

    def _own_trip(trip_id: str) -> Trip | None:
        return tr.get_trip(trip_id, tenant=_tenant())

    @app.post(f"{путь}/trips/<trip_id>", endpoint="trip_update")
    @guard.action(PLAN, OWN, object_in_route=True)
    def trip_update(trip_id: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        поездка = _own_trip(trip_id)
        if поездка is None:
            return _render(conf, selected=trip_id, status=404)
        отказ = _permit(поездка)
        if отказ is not None:
            return отказ
        язык = _lang(conf)
        try:
            tr.update_trip(поездка.id, _keep_executor(поездка, _units()), tenant=_tenant())
        except TripError as exc:
            return _render(
                conf,
                selected=поездка.id,
                failure=_reason(exc, язык),
                form=dict(request.form),
                status=400,
            )
        return _back(поездка.id)

    @app.post(f"{путь}/trips/<trip_id>/delete", endpoint="trip_delete")
    @guard.action(PLAN, OWN, object_in_route=True)
    def trip_delete(trip_id: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        поездка = _own_trip(trip_id)
        if поездка is None:
            return _render(conf, selected=trip_id, status=404)
        отказ = _permit(поездка)
        if отказ is not None:
            return отказ
        tr.delete_trip(поездка.id, tenant=_tenant())
        return _back()

    @app.post(f"{путь}/trips/<trip_id>/steps", endpoint="trip_step_add")
    @guard.action(PLAN, OWN, object_in_route=True)
    def trip_step_add(trip_id: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        поездка = _own_trip(trip_id)
        if поездка is None:
            return _render(conf, selected=trip_id, status=404)
        отказ = _permit(поездка)
        if отказ is not None:
            return отказ
        try:
            tr.add_step(поездка, _step_from_form(_units()))
        except TripError as exc:
            return _render(
                conf,
                selected=поездка.id,
                failure=_reason(exc, _lang(conf)),
                form=dict(request.form),
                status=400,
            )
        return _back(поездка.id)

    @app.post(f"{путь}/trips/<trip_id>/steps/<step_id>/delete", endpoint="trip_step_delete")
    @guard.action(PLAN, OWN, object_in_route=True)
    def trip_step_delete(trip_id: str, step_id: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        поездка = _own_trip(trip_id)
        if поездка is None:
            return _render(conf, selected=trip_id, status=404)
        отказ = _permit(поездка)
        if отказ is not None:
            return отказ
        tr.delete_step(поездка, step_id)
        return _back(поездка.id)


def _keep_executor(trip: Trip, units: tuple[Unit, ...]) -> Draft:
    """Правка поездки: сотрудник без `trip.plan` исполнителя не меняет — остаётся он."""
    черновик = _draft_from_form(units)
    if guard.may(PLAN):
        return черновик
    return Draft(
        executor_name=trip.executor_name,
        executor_user_id=trip.executor_user_id,
        country=черновик.country,
        date_from=черновик.date_from,
        date_to=черновик.date_to,
        status=черновик.status,
        note=черновик.note,
    )
