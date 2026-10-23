"""Чей это адрес у сервера MCP: клиент за общим прокси (D462, журнал действий).

То же правило, что у веба (`src/web/remote.py`, `src/web/proxy.py`), для сервера,
которого `waitress` не обслуживает: заголовку `X-Forwarded-For` верим только от
СВОЕГО звена и считаем с конца цепочки. Левый край пишет клиент — взять его значило
бы записать в журнал то, что отправитель захотел там увидеть.

Чистый Python: ни сети, ни базы.
"""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Iterable


def parse_peers(raw: str) -> tuple[str, ...]:
    """Адреса и подсети своих звеньев через запятую. Кривая запись — `ValueError`."""
    части = tuple(часть.strip() for часть in raw.split(",") if часть.strip())
    for часть in части:
        ipaddress.ip_network(часть, strict=False)
    return части


def peer_trusted(peer: str, addrs: Iterable[str]) -> bool:
    """Соединение пришло от своего звена: адрес совпал с названным или лежит в его подсети."""
    try:
        адрес = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(адрес in ipaddress.ip_network(сеть, strict=False) for сеть in addrs)


def front_key_matches(expected: str, given: str | None) -> bool:
    """Ключ фронта совпал: сравнение за постоянное время, пустой присланный — нет."""
    return bool(given) and hmac.compare_digest(expected.encode(), (given or "").encode())


def forwarded_client(
    peer: str,
    forwarded_for: str | None,
    *,
    trusted_proxies: int,
    trusted_addrs: tuple[str, ...],
    front_key: str = "",
    given_key: str | None = None,
) -> str:
    """Адрес клиента: по цепочке своих звеньев, а при любом сомнении — адрес соединения.

    Заголовок учитывается, только если звеньев обещано больше нуля, соединение пришло
    от названного звена и цепочка не короче обещанного. Иначе — `peer`: осторожный
    конец развилки (общий адрес на всех, а не выбранный отправителем).

    Задан ключ фронта (`front_key`, F-107 аудита) — звено, пришедшее без верного
    `given_key`, тоже чужое: подсеть звена делят и другие контейнеры. Не задан —
    доверие по подсети, как раньше.
    """
    if trusted_proxies <= 0 or not peer_trusted(peer, trusted_addrs):
        return peer
    if front_key and not front_key_matches(front_key, given_key):
        return peer
    цепочка = [звено.strip() for звено in (forwarded_for or "").split(",") if звено.strip()]
    if len(цепочка) < trusted_proxies:
        return peer
    return цепочка[-trusted_proxies]
