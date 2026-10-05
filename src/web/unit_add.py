"""Новая пиццерия из веб-админки: экран страны → «Добавить пиццерию» (#437, D240).

Раньше точку заводили бот («Новая пиццерия?», D233) и `tools/units.py add` по
ssh. Правила те же, что у бота, и живут они не здесь:

- кто вправе — `domain.tenants.may_add_units`: только пространство УК (D234),
  партнёр справочник не пополняет (D284), и для него адреса нет вовсе (404, как
  у разделов УК, D264);
- какое имя — `domain.unit_new.plan_new_unit`: «Город-N» по-английски
  (D232, D233), город другой страны — отказ, незнакомый город — подтверждение;
- дубль — `db.directory.create_unit`: имя или синоним уже называют точку —
  отказ с этой точкой, а не молчаливое обновление.

Пиццерия заводится в стране экрана. Охват читающего (`reach.py`) сверяется
тоже: УК видит все страны, но правило «пишешь только туда, что видишь»
держится и тогда, когда охват станет уже.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db import directory
from src.db.errors import DbError, UnitExistsError
from src.db.reach import Reach
from src.domain.geo import COUNTRIES
from src.domain.tenants import HQ_TENANT, may_add_units
from src.domain.unit_new import OTHER_COUNTRY, NewUnit, NewUnitRefused, plan_new_unit

from . import auth
from . import country as country_data
from .config import Settings
from .geo_names import country_title
from .origin import refuse_foreign_origin
from .sections import section
from .texts import lang_or_default, t

logger = logging.getLogger(__name__)


def may_add_in(tenant: str, reach: Reach, code: str) -> bool:
    """Может ли вошедший завести пиццерию в стране `code`.

    Три условия, и все обязательны: пространство УК, страна из словаря сети и
    страна в охвате вошедшего.
    """
    if not may_add_units(tenant) or code not in COUNTRIES:
        return False
    return reach.countries is None or code in reach.countries


def can_add_here(code: str) -> bool:
    """Показывать ли вход «Добавить пиццерию» на экране страны `code`."""
    return bool(code) and may_add_in(auth.current_tenant(), auth.current_reach(), code)


def _gate(raw_code: str) -> str:
    """Код страны, в которую вошедшему можно добавлять, — или 404."""
    code = country_data.normalize_code(raw_code)
    if not can_add_here(code):
        abort(404)
    return code


def _lang(conf: Settings) -> str:
    return lang_or_default(request.args.get("lang"), fallback=conf.ui_lang)


def _refusal_text(exc: NewUnitRefused, lang: str) -> str:
    params: dict[str, Any] = dict(exc.params)
    if exc.code == OTHER_COUNTRY:
        params["country"] = country_title(str(params["country"]), lang) or params["country"]
    return t(f"unitnew.refused.{exc.code}", lang, **params)


def _render(code: str, lang: str, *, typed: str = "", **context: Any) -> str:
    return render_template(
        "units/new.html",
        country=code,
        lang=lang,
        back=url_for("country", code=code, lang=lang),
        action=url_for("unit_new", code=code, lang=lang),
        typed=typed,
        **context,
    )


def _confirm_context(plan: NewUnit, lang: str) -> dict[str, Any]:
    return {
        "confirm": plan.name,
        "confirm_city": plan.name.rsplit("-", 1)[0],
        "confirm_country": country_title(plan.country, lang) or plan.country,
    }


def install(app: Flask, conf: Settings) -> None:
    """Маршруты заведения пиццерии: форма и её отправка."""
    путь = section("country").path + "/<code>/units/new"

    @app.get(путь, endpoint="unit_new")
    def unit_new(code: str) -> str:
        return _render(_gate(code), _lang(conf))

    @app.post(путь, endpoint="unit_create")
    def unit_create(code: str) -> Response | str | tuple[str, int]:
        страна = _gate(code)
        refuse_foreign_origin()
        lang = _lang(conf)
        написано = (request.form.get("name") or "")[:200]
        try:
            plan = plan_new_unit(написано, country=страна)
        except NewUnitRefused as exc:
            return _render(страна, lang, typed=написано, failure=_refusal_text(exc, lang)), 400
        if not plan.known_city and request.form.get("confirm") != plan.name:
            # Незнакомый город (D240) заводится, но не молча: район или адрес
            # с цифрой («Zemun 2») иначе стал бы «городом» сети (#440).
            return _render(страна, lang, typed=написано, **_confirm_context(plan, lang))
        try:
            unit_id = directory.create_unit(
                plan.name,
                country=plan.country,
                city=plan.city,
                aliases=plan.aliases,
                tenant=HQ_TENANT,
            )
        except UnitExistsError as exc:
            return _render(
                страна,
                lang,
                typed=написано,
                exists_name=exc.name,
                exists_url=url_for("unit", unit_id=exc.unit_id, lang=lang),
            ), 409
        except DbError:
            logger.exception("пиццерия %s не заведена в справочник", plan.name)
            return _render(страна, lang, typed=написано, failure=t("unitnew.failed", lang)), 503
        вошедший = auth.current_account()
        logger.info(
            "пиццерия %s (%s) заведена из веба: %s",
            plan.name,
            plan.country,
            вошедший.login if вошедший else "?",
        )
        return redirect(url_for("unit", unit_id=unit_id, lang=lang, added=1))
