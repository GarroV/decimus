"""Ссылки Dodo IS в выгрузках рейтинга: id пиццерии, проверки и периода.

Ключ пиццерии — id Dodo IS (32 hex). Он стоит в ссылке на рейтинг во всех
трёх выгрузках: `https://dodopizza.info/rating#/<пиццерия>/<тип>?…&checkupId=…
&ratingPeriodId=…`. Тип в пути: `1` — РКО, `2` — РС (сверено по живым выгрузкам).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .model import RKO, RS

HEX32 = re.compile(r"^[0-9a-f]{32}$")
RATING_HOST = "dodopizza.info"
BACKOFFICE_DOMAIN = "dodois.io"
_TYPE_BY_SEGMENT = {"1": RKO, "2": RS}
_SEGMENT_BY_TYPE = {code: segment for segment, code in _TYPE_BY_SEGMENT.items()}


def hex_id(value: object) -> str | None:
    """id Dodo IS в одной форме: 32 hex строчными, без дефисов. Не id — `None`."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().replace("-", "").lower()
    return candidate if HEX32.match(candidate) else None


@dataclass(frozen=True)
class RatingLink:
    unit_id: str
    rating_type: str | None
    checkup_id: str | None
    period_id: str | None


def parse_rating_link(url: str) -> RatingLink | None:
    """Ссылка на рейтинг → id. Чужой адрес или нет id пиццерии — `None`."""
    parts = urlsplit(url.strip())
    if parts.hostname != RATING_HOST or not parts.fragment:
        return None
    path, _, query = parts.fragment.partition("?")
    segments = [segment for segment in path.split("/") if segment]
    unit = hex_id(segments[0]) if segments else None
    if unit is None:
        return None
    params = parse_qs(query)
    return RatingLink(
        unit_id=unit,
        rating_type=_TYPE_BY_SEGMENT.get(segments[1]) if len(segments) > 1 else None,
        checkup_id=hex_id((params.get("checkupId") or [""])[0]),
        period_id=hex_id((params.get("ratingPeriodId") or [""])[0]),
    )


def backoffice_checkup_id(url: str) -> str | None:
    """id проверки из ссылки бэк-офиса `…dodois.io/backoffice/checkups/<id>`."""
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    if host != BACKOFFICE_DOMAIN and not host.endswith("." + BACKOFFICE_DOMAIN):
        return None
    return hex_id(parts.path.rstrip("/").rsplit("/", 1)[-1])


def checkup_backoffice_url(checkup_id: str) -> str:
    """Ссылка на проверку в бэк-офисе, собранная из проверенного id (не из файла)."""
    return f"https://control.{BACKOFFICE_DOMAIN}/backoffice/checkups/{checkup_id}"


def checkup_rating_url(
    unit_id: str, rating_type: str, checkup_id: str, period_id: str | None
) -> str:
    """Ссылка на проверку в рейтинге, собранная из проверенных id (не из файла)."""
    base = unit_rating_url(unit_id, rating_type)
    url = f"{base}?selectedRemarkType=0&openRemarkDetails=1&checkupId={checkup_id}"
    return f"{url}&ratingPeriodId={period_id}" if period_id else url


def unit_rating_url(dodo_id: str, rating_type: str) -> str:
    """Страница пиццерии в рейтинге Dodo IS — куда ведёт имя в сводке."""
    return f"https://{RATING_HOST}/rating#/{dodo_id}/{_SEGMENT_BY_TYPE[rating_type]}"
