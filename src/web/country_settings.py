"""«Настройки страны» на экране «Страны» (D536): девелопер и партнёр страны — только администратору.

Панель справа на том же экране (D527). Своей логики здесь нет, только дверь веба
в то, что уже есть:

- девелопер — справочник рейтингов (`ratings.countries.developer`), тот же
  `ratings_read.set_developer`, что у экрана «Рейтинги → Загрузки» (`ratings.py`);
- партнёр — пространство, за которым закреплена страна (`space_countries`), тот же
  `partner_spaces.add_countries`, что у «Пользователи → Пространства». Страна — один
  партнёр: занятую другим пространством страну отсюда не перенести, как и там;
  привязка добавляется, снять её можно только руками (`docs/18-access-map.md`).

Кто вправе — по матрице: оба маршрута объявлены действием `space.manage` (главный
админ и админ УК, D364). Кнопка на экране показывается по тому же коду, остальным
адреса отвечают отказом заслона.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from flask import Flask, abort, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import ratings_read
from src.db.errors import DbError
from src.domain.tenants import HQ_TENANT

from . import auth, guard, partner_spaces
from . import country as country_data
from .origin import refuse_foreign_origin
from .sections import section

log = logging.getLogger(__name__)

#: Исходы сохранения — коды в адресе возврата (`?saved=`); текст подбирает экран.
SAVED = "ok"
FAILED = "failed"
_OUTCOMES = frozenset({SAVED, FAILED})

#: Длина имени девелопера — как у поля справочника (`country_page.DEVELOPER_MAX`).
DEVELOPER_MAX = 120


@dataclass(frozen=True)
class SpaceOption:
    """Пространство партнёра для выбора: код и название."""

    code: str
    name: str


@dataclass(frozen=True)
class Panel:
    """Что показывает панель: девелопер, чья страна, кому её можно отдать, исход."""

    code: str
    developer: str
    #: Пространство, за которым закреплена страна; пусто — ни за кем.
    owner: str = ""
    owner_name: str = ""
    #: Пространства партнёров, которым страну можно закрепить (пока она ничья).
    spaces: tuple[SpaceOption, ...] = ()
    #: Пространства не прочитались — форма партнёра не рисуется.
    failed: bool = False
    #: Исход прошлого сохранения (`ok` / `failed`) или пусто.
    saved: str = ""


def load(code: str, developer: str, saved: str) -> Panel:
    """Панель страны `code`: текущий девелопер и партнёр-пространство."""
    try:
        spaces = partner_spaces.overview()
    except DbError:
        log.warning("Пространства партнёров для настроек страны не прочитались", exc_info=True)
        return Panel(code, developer, failed=True, saved=saved if saved in _OUTCOMES else "")
    owner = next((s for s in spaces if code in s.countries), None)
    free = tuple(SpaceOption(s.code, s.name or s.code) for s in spaces if s.code != HQ_TENANT)
    return Panel(
        code=code,
        developer=developer,
        owner=owner.code if owner else "",
        owner_name=(owner.name or owner.code) if owner else "",
        spaces=() if owner else free,
        saved=saved if saved in _OUTCOMES else "",
    )


def _back(code: str, outcome: str, lang_in_url: str) -> Response:
    params: dict[str, Any] = {"code": code, "settings": 1, "saved": outcome}
    if lang_in_url:
        params["lang"] = lang_in_url
    return redirect(url_for("country", **params))


def install(app: Flask) -> None:
    """Маршруты настроек страны: девелопер и партнёр. Оба — действие `space.manage`."""
    base = section("country").path + "/<code>/settings"

    def _checked(raw: str) -> str:
        """Код страны из адреса в охвате вошедшего — иначе 404, как у несуществующей."""
        code = country_data.normalize_code(raw)
        reach = auth.current_reach().countries
        if not code or (reach is not None and code not in reach):
            abort(404)
        return code

    @app.post(base + "/developer", endpoint="country_set_developer")
    @guard.action("space.manage")
    def set_developer(code: str) -> Response:
        страна = _checked(code)
        refuse_foreign_origin()
        вошедший = auth.current_account()
        имя = (request.form.get("developer") or "").strip()[:DEVELOPER_MAX]
        try:
            changed = ratings_read.set_developer(
                страна, имя, actor=вошедший.login if вошедший else ""
            )
        except (DbError, ratings_read.RatingsEditError):
            log.warning("Девелопер страны %s не сохранён", страна, exc_info=True)
            changed = False
        return _back(страна, SAVED if changed else FAILED, request.args.get("lang", ""))

    @app.post(base + "/space", endpoint="country_set_space")
    @guard.action("space.manage")
    def set_space(code: str) -> Response:
        страна = _checked(code)
        refuse_foreign_origin()
        пространство = (request.form.get("space") or "").strip()
        try:
            partner_spaces.add_countries(пространство, (страна,))
            outcome = SAVED
        except DbError:
            log.warning("Страна %s не закреплена за %s", страна, пространство, exc_info=True)
            outcome = FAILED
        return _back(страна, outcome, request.args.get("lang", ""))
