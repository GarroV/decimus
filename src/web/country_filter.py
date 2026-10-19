"""Постоянный отбор стран экрана «Страны» (D536): «мне нужен только Кавказ».

Человек выбирает свои страны, или кластер целиком (D383, D502), и остальные с
экрана уходят. Отбор живёт в профиле учётки (`web_users.country_filter`, `0077`),
как язык сайта, поэтому действует на всех устройствах и в следующих сессиях.
В кластере хранятся его СТРАНЫ на момент выбора: состав кластера читается из
справочника рейтингов и в профиль не копируется как понятие.

Отбор только СУЖАЕТ охват. Партнёру двери и так отдают только его страны; отбор
пересекается с охватом, а не расширяет его, и код страны вне охвата в профиле
ничего не открывает. Если после пересечения не осталось ни одной страны (охват
сузился), отбор не применяется: пустой экран хуже полного.

В открытом демо (D524) учётки ролей общие: отбор, сохранённый в профиль, одному
посетителю менял бы экран всем остальным. Там он живёт в куке браузера.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from flask import Flask, current_app, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import ratings_read, web_own_profile
from src.db.errors import DbError
from src.ratings.report import CLUSTERS

from . import auth
from .origin import over_https, refuse_foreign_origin
from .sections import section
from .ui_lang import _DEMO_FLAG, _safe_back

log = logging.getLogger(__name__)

#: Кука отбора в открытом демо (D524) — вместо профиля, как у языка.
DEMO_COOKIE = "decimus_demo_countries"
_DEMO_MAX_AGE_S = 7 * 24 * 3600
#: Больше стран, чем в сети, в отборе быть не может; предел защищает базу от мусора формы.
MAX_COUNTRIES = 300


@dataclass(frozen=True)
class Cluster:
    """Кластер стран охвата вошедшего: ключ (`CAUCASUS`) и его коды."""

    key: str
    codes: tuple[str, ...]


def clusters_of(visible: Iterable[str]) -> tuple[Cluster, ...]:
    """Кластеры справочника рейтингов, суженные до видимых стран; пустые не показываются."""
    shown = set(visible)
    try:
        rows = ratings_read.countries()
    except DbError:
        log.warning("Кластеры стран для отбора не прочитались", exc_info=True)
        return ()
    found = []
    for key in CLUSTERS:
        members = tuple(sorted(r.code for r in rows if r.cluster == key and r.code in shown))
        if members:
            found.append(Cluster(key, members))
    return tuple(found)


def _clean(codes: Iterable[str]) -> tuple[str, ...]:
    """Коды стран из формы или профиля: две заглавные буквы, без повторов, не больше предела."""
    out: dict[str, None] = {}
    for raw in codes:
        code = (raw or "").strip().upper()
        if len(code) == 2 and code.isascii() and code.isalpha():
            out[code] = None
    return tuple(out)[:MAX_COUNTRIES]


def saved() -> tuple[str, ...]:
    """Отбор вошедшего: из профиля, а в демо — из куки. Пусто — отбора нет."""
    if current_app.config.get(_DEMO_FLAG):
        return _clean((request.cookies.get(DEMO_COOKIE) or "").split(","))
    return _clean(getattr(auth.current_account(), "country_filter", None) or ())


def narrow(codes: tuple[str, ...], chosen: tuple[str, ...]) -> tuple[str, ...]:
    """Страны экрана: видимые `codes`, оставшиеся после отбора; порядок `codes` сохраняется."""
    if not chosen:
        return codes
    kept = tuple(c for c in codes if c in set(chosen))
    return kept or codes


def is_active(codes: tuple[str, ...], chosen: tuple[str, ...]) -> bool:
    """Сужает ли отбор что-то на самом деле: хоть одна видимая страна отброшена."""
    return bool(chosen) and narrow(codes, chosen) != codes


def _store(countries: tuple[str, ...], response: Response) -> bool:
    """Записать отбор: профиль или кука демо. `False` — сохранить не вышло."""
    if current_app.config.get(_DEMO_FLAG):
        if countries:
            response.set_cookie(
                DEMO_COOKIE,
                ",".join(countries),
                max_age=_DEMO_MAX_AGE_S,
                httponly=True,
                samesite="Lax",
                secure=over_https(),
                path="/",
            )
        else:
            response.delete_cookie(DEMO_COOKIE, path="/")
        return True
    try:
        return web_own_profile.set_country_filter(auth.current_session_token(), countries)
    except DbError:
        log.exception("отбор стран: сохранить в профиль не удалось")
        return False


def install(app: Flask) -> None:
    """Маршрут сохранения отбора: `POST /country/filter` (дело самого человека)."""
    path = section("country").path + "/filter"

    @app.post(path, endpoint="country_filter")
    def country_filter() -> Response:
        """Сохранить отбор стран и вернуть на экран, откуда его меняли.

        Поля формы: `countries` (флажки), `cluster` (кнопка кластера — отбор
        становится его странами), `reset` (кнопка «Все страны»), `next` (путь
        экрана). Страны вне охвата в отбор не попадают.
        """
        refuse_foreign_origin()
        reach = auth.current_reach().countries
        form = request.form
        if form.get("reset"):
            chosen: tuple[str, ...] = ()
        elif form.get("cluster"):
            chosen = next(
                (c.codes for c in clusters_of(_visible(reach)) if c.key == form["cluster"]), ()
            )
        else:
            chosen = _clean(form.getlist("countries"))
            if reach is not None:
                chosen = tuple(c for c in chosen if c in reach)
        back = _safe_back(form.get("next")) or url_for("country_index")[len(request.script_root) :]
        response = redirect(f"{request.script_root}{back}")
        _store(chosen, response)
        return response


def _visible(reach: tuple[str, ...] | None) -> tuple[str, ...]:
    """Страны справочника в охвате (`None` — вся сеть)."""
    try:
        rows = ratings_read.countries()
    except DbError:
        return tuple(reach or ())
    return tuple(r.code for r in rows if reach is None or r.code in reach)
