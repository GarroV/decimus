"""Ручные решения по охвату агрегаторов (D700): «нет на площадке» и закреплённая привязка.

Четыре действия на экране «Администрирование → Агрегаторы», все за тем же правом
`ratings.manage`, что и привязка Glovo по ссылке (`ratings._link_point`):

- «Нет на площадке» / «Снять отметку» — у площадок без поиска у координат (Glovo,
  Chowdeck, Migros), где отсутствие нельзя вывести из поиска;
- «Привязать» — закрепить непривязанную точку рядом за пиццерией (площадка
  геокодирует адрес плохо, точка дальше `MAX_LINK_M`); ночной сбор закрепление не
  отменяет;
- «Отвязать» — снять закрепление.

Исход — возврат на страну; не вышло — с пометкой `result=failed`, успех молчит
(строка просто переезжает в нужный список). Никому ничего не отправляется.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from flask import Flask, redirect, render_template, request
from werkzeug.wrappers import Response

from src.db import agg_store
from src.db.errors import RatingsError
from src.ratings import maps_link
from src.ratings.aggregators import collect

from . import administration, auth, guard
from .config import Settings
from .origin import refuse_foreign_origin
from .ratings import may_manage
from .sections import section

logger = logging.getLogger(__name__)

_DODO_ID = re.compile(r"[0-9a-f]{32}")
#: Результат, который показывает экран после возврата.
FAILED = "failed"

Reply = Response | tuple[str, int]


def _known(aggregator: str) -> bool:
    return aggregator in {m.KEY for m in collect.SEARCHERS + collect.KNOWN + collect.PAUSED}


def _searched(aggregator: str) -> bool:
    return aggregator in {m.KEY for m in collect.SEARCHERS}


def _field(name: str) -> str:
    return (request.form.get(name) or "").strip()


def _back(country: str, result: str = "") -> Response:
    return redirect(
        administration.url("aggregators", country=country.upper(), result=result), code=303
    )


def _actor() -> str:
    account = auth.current_account()
    return account.login if account else ""


def _unit(unit_id: str) -> agg_store.UnitRow | None:
    if not _DODO_ID.fullmatch(unit_id):
        return None
    return next((u for u in agg_store.units() if u.dodo_id == unit_id), None)


def _absent(mark: bool) -> Reply:
    aggregator = _field("aggregator")
    unit = _unit(_field("dodo_id").lower())
    # Поисковой площадке «нет» говорит поиск, а не человек: отметка там спрятала бы
    # появившуюся точку.
    if unit is None or not _known(aggregator) or _searched(aggregator):
        return _back(_field("country"), FAILED)
    if mark:
        agg_store.mark_absent(aggregator, unit.dodo_id, by=_actor())
    else:
        agg_store.unmark_absent(aggregator, unit.dodo_id)
    return _back(unit.country)


def _pin() -> Reply:
    aggregator, key = _field("aggregator"), _field("point_key")
    unit = _unit(_field("dodo_id").lower())
    if unit is None or not _known(aggregator):
        return _back(_field("country"), FAILED)
    point = next(
        (
            p
            for p in agg_store.open_points()
            if (p.aggregator, p.point_key) == (aggregator, key) and p.country_code == unit.country
        ),
        None,
    )
    if point is None:
        return _back(unit.country, FAILED)
    metres = round(maps_link.distance_m(unit.lat, unit.lng, point.lat, point.lng))
    saved = agg_store.pin_link(aggregator, key, unit.dodo_id, unit.name, metres, by=_actor())
    return _back(unit.country, "" if saved else FAILED)


def _unpin() -> Reply:
    aggregator, key = _field("aggregator"), _field("point_key")
    if not _known(aggregator) or not key:
        return _back(_field("country"), FAILED)
    agg_store.unpin_link(aggregator, key)
    return _back(_field("country"))


def install(app: Flask, conf: Settings) -> None:
    base = f"{section('ratings').path}/aggregators"

    def run(action: Callable[[], Reply]) -> Reply:
        if not may_manage():
            return render_template("users/forbidden.html"), 403
        refuse_foreign_origin()
        try:
            return action()
        except RatingsError:
            logger.warning("агрегаторы: ручное решение не легло", exc_info=True)
            return _back(_field("country"), FAILED)

    @app.post(f"{base}/absent")
    @guard.action("ratings.manage")
    def aggregators_absent() -> Reply:
        return run(lambda: _absent(True))

    @app.post(f"{base}/present")
    @guard.action("ratings.manage")
    def aggregators_present() -> Reply:
        return run(lambda: _absent(False))

    @app.post(f"{base}/pin")
    @guard.action("ratings.manage")
    def aggregators_pin() -> Reply:
        return run(_pin)

    @app.post(f"{base}/unpin")
    @guard.action("ratings.manage")
    def aggregators_unpin() -> Reply:
        return run(_unpin)
