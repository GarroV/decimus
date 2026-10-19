"""Новая пиццерия из веб-админки: экран страны → «Добавить пиццерию» (#437, D240).

Раньше точку заводили бот («Новая пиццерия?», D233) и `tools/units.py add` по
ssh. Правила те же, что у бота, и живут они не здесь:

- кто вправе — матрица (`unit.create`, `src/domain/permissions.py`): только УК (D234),
  партнёр справочник не пополняет (D284), и для него адреса нет вовсе (404, как
  у разделов УК, D264);
- какое имя — `domain.unit_new.plan_new_unit`: «Город-N» по-английски
  (D232, D233), город другой страны — отказ, незнакомый город — подтверждение;
- дубль — `db.directory.create_unit`: имя или синоним уже называют точку —
  отказ с этой точкой, а не молчаливое обновление.

Пиццерия заводится в стране экрана. Охват читающего (`reach.py`) сверяется
тоже: УК видит все страны, но правило «пишешь только туда, что видишь»
держится и тогда, когда охват станет уже.

Сведения справочника (D536): кроме названия форма принимает адрес, партнёра, код
Dodo (необязательный), стадию и дату открытия — то, что держит справочник
`unit_profiles` (`docs/16-unit-profiles.md`). Название совпало со строкой
справочника — форма подставляет её сведения, а пустые поля при заведении
добираются из неё. Сведения пишутся рядом со сводом (`unit_profiles.upsert`),
остальной справочник не трогая; код Dodo ложится ещё и в `units.code` — по нему
экран «Страны» связывает точку со строкой справочника.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db import directory, unit_profiles
from src.db.errors import DbError, UnitExistsError
from src.db.reach import Reach
from src.domain.geo import COUNTRIES
from src.domain.log_ids import log_id
from src.domain.tenants import HQ_TENANT, may_add_units
from src.domain.unit_match import Ref
from src.domain.unit_new import OTHER_COUNTRY, NewUnit, NewUnitRefused, plan_new_unit
from src.ratings.svod import normalize as reference_key

from . import auth, guard, ui_lang
from . import country as country_data
from .config import Settings
from .geo_names import country_title
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Код Dodo пиццерии — 32 шестнадцатеричных знака (`unit_profiles.dodo_id`, `0046`).
_DODO_ID = re.compile(r"[0-9a-f]{32}")
#: Стадии, в которых пиццерию заводят вручную; закрытая — не новая.
STAGES = ("open", "pipeline", "paused")
#: Сколько названий справочника предлагать в подсказке формы.
_SUGGEST_LIMIT = 300
#: Пределы текстовых полей формы.
_ADDRESS_MAX = 200
_PARTNER_MAX = 120


class ExtrasRefused(ValueError):
    """Сведения формы не годятся. `args[0]` — код отказа (`unitnew.refused.<код>`)."""


@dataclass(frozen=True)
class Extras:
    """Сведения справочника, названные в форме. Пустое поле — «не названо»."""

    address: str = ""
    partner: str = ""
    dodo_id: str = ""
    stage: str = ""
    opened: date | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.address or self.partner or self.dodo_id or self.stage or self.opened)


def parse_extras(form: Any) -> Extras:
    """Сведения из формы — или `ExtrasRefused`. Ввод снаружи: форма проверяется здесь."""
    dodo_id = (form.get("dodo_id") or "").strip().lower()
    if dodo_id and not _DODO_ID.fullmatch(dodo_id):
        raise ExtrasRefused("dodo_id")
    stage = (form.get("stage") or "").strip()
    if stage and stage not in STAGES:
        raise ExtrasRefused("stage")
    raw_date = (form.get("opened") or "").strip()
    try:
        opened = date.fromisoformat(raw_date) if raw_date else None
    except ValueError as exc:
        raise ExtrasRefused("opened") from exc
    return Extras(
        address=" ".join((form.get("address") or "").split())[:_ADDRESS_MAX],
        partner=" ".join((form.get("partner") or "").split())[:_PARTNER_MAX],
        dodo_id=dodo_id,
        stage=stage,
        opened=opened,
    )


def reference_rows(country: str) -> tuple[unit_profiles.Profile, ...]:
    """Строки справочника страны; не прочиталось — пусто: форма живёт и без подсказок."""
    try:
        return unit_profiles.by_country(country)
    except DbError:
        logger.warning("Справочник пиццерий страны для формы не прочитался", exc_info=True)
        return ()


def _refs(country: str) -> tuple[Ref, ...]:
    """Справочник страны в виде, понятном правилу имени (D538)."""
    return tuple(
        Ref(p.country_code, p.name, p.dodo_id, p.city, p.address) for p in reference_rows(country)
    )


def match_reference(
    rows: tuple[unit_profiles.Profile, ...], *names: str
) -> unit_profiles.Profile | None:
    """Строка справочника, чьё название совпало с одним из `names` (без регистра и пробелов)."""
    keys = {reference_key(n) for n in names if n}
    return next((p for p in rows if reference_key(p.name) in keys), None)


def merged_profile(
    country: str, name: str, extras: Extras, base: unit_profiles.Profile | None
) -> unit_profiles.Profile:
    """Что лягло бы в справочник: найденная строка, дополненная названным в форме."""
    stage = extras.stage or (base.stage if base else "open")
    return unit_profiles.Profile(
        country_code=country,
        name=base.name if base else name,
        name_normalized=base.name_normalized if base else reference_key(name),
        stage=stage,
        status=(base.status if base and not extras.stage else ""),
        city=base.city if base else None,
        address=extras.address or (base.address if base else None),
        partner=extras.partner or (base.partner if base else None),
        partner_email=base.partner_email if base else None,
        restaurant_on=extras.opened or (base.restaurant_on if base else None),
        delivery_on=base.delivery_on if base else None,
        revenue_on=base.revenue_on if base else None,
        closed_on=base.closed_on if base else None,
        total_area=base.total_area if base else None,
        seats=base.seats if base else None,
        extra=dict(base.extra) if base else {},
        dodo_id=extras.dodo_id or (base.dodo_id if base else None),
    )


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
    # Роль — по матрице (`unit.create`): гость и контроль формы не видят.
    return (
        bool(code)
        and guard.may("unit.create")
        and may_add_in(auth.current_tenant(), auth.current_reach(), code)
    )


def _gate(raw_code: str) -> str:
    """Код страны, в которую вошедшему можно добавлять, — или 404."""
    code = country_data.normalize_code(raw_code)
    if not can_add_here(code):
        abort(404)
    return code


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def _refusal_text(exc: NewUnitRefused, lang: str) -> str:
    params: dict[str, Any] = dict(exc.params)
    if exc.code == OTHER_COUNTRY:
        params["country"] = country_title(str(params["country"]), lang) or params["country"]
    return t(f"unitnew.refused.{exc.code}", lang, **params)


def _suggestions(code: str) -> tuple[str, ...]:
    """Названия справочника страны, которых ещё нет среди точек, — подсказка формы."""
    rows = reference_rows(code)
    if not rows:
        return ()
    try:
        known = {
            reference_key(u.name)
            for u in directory.list_units(reach=auth.current_reach(), country=code)
        }
    except DbError:
        known = set()
    names = [p.name for p in rows if reference_key(p.name) not in known and p.stage != "closed"]
    return tuple(names[:_SUGGEST_LIMIT])


def _render(
    code: str,
    lang: str,
    *,
    typed: str = "",
    values: dict[str, str] | None = None,
    **context: Any,
) -> str:
    return render_template(
        "units/new.html",
        country=code,
        lang=lang,
        back=url_for("country", code=code, lang=lang),
        action=url_for("unit_new", code=code, lang=lang),
        typed=typed,
        values=values or {},
        stages=STAGES,
        suggestions=_suggestions(code),
        partners=tuple(sorted({p.partner for p in reference_rows(code) if p.partner})),
        **context,
    )


def _prefill(code: str, typed: str) -> dict[str, str]:
    """Сведения строки справочника, чьё название совпало с набранным, — для полей формы."""
    base = match_reference(reference_rows(code), typed, _planned_name(typed, code))
    if base is None:
        return {}
    return {
        "name": base.name,
        "address": base.address or "",
        "partner": base.partner or "",
        "dodo_id": base.dodo_id or "",
        "stage": base.stage if base.stage in STAGES else "",
        "opened": str(base.restaurant_on or base.delivery_on or ""),
    }


def _planned_name(typed: str, code: str) -> str:
    """Каноническое имя набранного или пусто, если оно не годится."""
    try:
        return plan_new_unit(typed, country=code, refs=_refs(code)).name
    except NewUnitRefused:
        return ""


def _confirm_context(plan: NewUnit, lang: str) -> dict[str, Any]:
    return {
        "confirm": plan.name,
        "confirm_city": plan.name.rsplit("-", 1)[0],
        "confirm_country": country_title(plan.country, lang) or plan.country,
    }


def _card_url_in_reach(exc: UnitExistsError, lang: str) -> str | None:
    """Ссылка на найденную точку — только если вошедший её видит; иначе просто «уже есть».

    Ссылка вне охвата вела бы в 404 и вдобавок называла бы идентификатор точки,
    которую вошедшему знать не положено.
    """
    охват = auth.current_reach()
    if охват.countries is not None and exc.country not in охват.countries:
        return None
    return url_for("unit", unit_id=exc.unit_id, lang=lang)


def install(app: Flask, conf: Settings) -> None:
    """Маршруты заведения пиццерии: форма и её отправка."""
    путь = section("country").path + "/<code>/units/new"

    # Объявлено действием, а не только чтением раздела: «Страна» открыта и
    # партнёру (D508), а форма заведения — только УК, и заслон УК-границы
    # закрывает её по матрице, а не лишь по `_gate`.
    @app.get(путь, endpoint="unit_new")
    @guard.action("unit.create")
    def unit_new(code: str) -> str:
        страна = _gate(code)
        # «Подставить из справочника» (D536): название набрано — поля берутся из строки справочника.
        набрано = (request.args.get("name") or "")[:200]
        поля = _prefill(страна, набрано) if набрано and request.args.get("prefill") else {}
        return _render(страна, _lang(conf), typed=поля.get("name", набрано), values=поля)

    @app.post(путь, endpoint="unit_create")
    @guard.action("unit.create")
    def unit_create(code: str) -> Response | str | tuple[str, int]:
        страна = _gate(code)
        refuse_foreign_origin()
        lang = _lang(conf)
        написано = (request.form.get("name") or "")[:200]
        поля = {
            k: (request.form.get(k) or "")
            for k in ("address", "partner", "dodo_id", "stage", "opened")
        }
        try:
            plan = plan_new_unit(написано, country=страна, refs=_refs(страна))
            extras = parse_extras(request.form)
        except NewUnitRefused as exc:
            return _render(
                страна, lang, typed=написано, values=поля, failure=_refusal_text(exc, lang)
            ), 400
        except ExtrasRefused as exc:
            return _render(
                страна,
                lang,
                typed=написано,
                values=поля,
                failure=t(f"unitnew.refused.{exc.args[0]}", lang),
            ), 400
        if not plan.known_city and request.form.get("confirm") != plan.name:
            # Незнакомый город (D240) заводится, но не молча: район или адрес
            # с цифрой («Zemun 2») иначе стал бы «городом» сети (#440).
            return _render(
                страна, lang, typed=написано, values=поля, **_confirm_context(plan, lang)
            )
        try:
            заведена = directory.create_unit(
                plan.name,
                country=plan.country,
                city=plan.city,
                aliases=plan.aliases,
                code=plan.code,
                tenant=HQ_TENANT,
            )
        except UnitExistsError as exc:
            return _render(
                страна,
                lang,
                typed=написано,
                values=поля,
                exists_name=exc.name,
                exists_url=_card_url_in_reach(exc, lang),
            ), 409
        except DbError:
            logger.exception("пиццерия %s не заведена в справочник", plan.name)
            return _render(
                страна, lang, typed=написано, values=поля, failure=t("unitnew.failed", lang)
            ), 503
        профиль_записан = _save_profile(страна, plan.name, написано, extras, заведена.id)
        вошедший = auth.current_account()
        logger.info(
            "пиццерия %s (%s) заведена из веба: %s",
            plan.name,
            plan.country,
            log_id(вошедший.login if вошедший else "?"),
        )
        # Дальше — экран «Страны» с новой пиццерией справа (D536); сказать о неудаче
        # записи сведений или занятом написании словами, а не молчанием.
        return redirect(
            url_for(
                "country",
                code=страна,
                unit=заведена.id,
                lang=lang,
                added=1,
                alias_taken=1 if заведена.taken_aliases else None,
                profile_failed=None if профиль_записан else 1,
            )
        )


def _save_profile(страна: str, name: str, typed: str, extras: Extras, unit_id: str) -> bool:
    """Записать сведения справочника новой точки и связать её кодом Dodo. `False` — не вышло.

    Точка уже заведена и верна; неудача здесь не откатывает её, а сообщается экраном.
    Нечего писать (ни полей, ни совпавшей строки справочника) — это успех: делать нечего.
    """
    base = match_reference(reference_rows(страна), name, typed)
    if extras.is_empty and base is None:
        return True
    profile = merged_profile(страна, name, extras, base)
    try:
        unit_profiles.upsert(profile)
        if profile.dodo_id:
            unit_profiles.set_unit_codes([(unit_id, profile.dodo_id)])
    except DbError:
        logger.warning("сведения новой пиццерии %s не легли в справочник", name, exc_info=True)
        return False
    return True
