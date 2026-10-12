"""Привязка пиццерии к Migros Yemek по ссылке на страницу магазина (#717).

Migros собирается по справочнику известных точек: координат карточка не отдаёт,
а у поиска нет фильтра по бренду, поэтому новую пиццерию Турции сам сбор не
найдёт. На экране «Пиццерии на площадках» человек вставляет ссылку
`https://www.migros.com.tr/yemek/<slug>`; сервер берёт из неё только `slug`,
читает карточку тем же путём, что сбор (через ретранслятор, D434), проверяет,
что это Dodo Pizza, и заводит точку справочника с первой оценкой.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection
from datetime import date
from urllib.parse import urlsplit

from src.db.agg_store import PointRow, RatingRow

from . import migros
from .base import AggregatorError, Http
from .glovo_link import (
    BAD_URL,
    COUNTRY_MISMATCH,
    NO_STORE,
    OK,
    TAKEN,
    UNKNOWN_UNIT,
    LinkResult,
    Locatable,
)

logger = logging.getLogger(__name__)

COUNTRY = "TR"
HOSTS = frozenset({"www.migros.com.tr", "migros.com.tr"})
#: Тот же шаблон, что пропускает ретранслятор (`migros_relay._PATH`).
_PATH = re.compile(r"^/yemek/(?P<slug>[a-z0-9][a-z0-9-]{0,159})/?$")

MIGROS_FAILED = "migros_failed"


def parse_store_url(url: str) -> str | None:
    """Адрес страницы магазина Migros Yemek → `slug` или `None`. Только https,
    хост `www.migros.com.tr` или `migros.com.tr`, без порта и логина, путь
    `/yemek/<slug>`; запрос и якорь отбрасываются."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    match = _PATH.match(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname not in HOSTS
        or port is not None
        or parts.username
        or parts.password
        or not match
    ):
        return None
    return match["slug"]


def link_by_url(
    unit: Locatable | None,
    url: str,
    taken: Collection[str],
    today: date,
    *,
    http: Http | None = None,
) -> tuple[LinkResult, PointRow | None, RatingRow | None]:
    """Привязать пиццерию к Migros Yemek по ссылке. Вернуть итог
    (`LinkResult.code` — ключ текста), точку и оценку для записи."""
    if unit is None:
        return LinkResult(UNKNOWN_UNIT), None, None
    slug = parse_store_url(url)
    if slug is None:
        return LinkResult(BAD_URL), None, None
    if unit.country != COUNTRY:
        return LinkResult(COUNTRY_MISMATCH), None, None
    if slug in taken:
        return LinkResult(TAKEN), None, None
    probe = PointRow(migros.KEY, slug, COUNTRY, None, None, None, None, None, None, None, {})
    try:
        payload = (http or Http(migros.GAP_SEC)).get(migros.store_url(slug))
    except AggregatorError as exc:
        logger.warning("migros: %s по ссылке не прочитался (%s)", unit.name, migros.reason(exc))
        return LinkResult(MIGROS_FAILED), None, None
    try:
        found = migros.parse(payload, probe)
    except AggregatorError:
        return LinkResult(NO_STORE), None, None
    point = PointRow(
        migros.KEY,
        slug,
        COUNTRY,
        found.name,
        found.url,
        None,
        None,
        unit.dodo_id,
        unit.name,
        None,
        dict(found.extra),
    )
    rating = None
    if found.score is not None and 0 <= found.score <= found.scale:
        rating = RatingRow(
            migros.KEY,
            slug,
            today,
            found.score,
            found.scale,
            found.votes,
            found.votes_exact,
            found.is_open,
        )
    return LinkResult(OK, slug), point, rating
