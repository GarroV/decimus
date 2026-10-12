"""Публичные адреса админки и MCP — для подключения Claude через OAuth (D417).

Сервер за туннелем не знает, каким адресом его видят снаружи (Worker стирает
`Host`), а OAuth без этого не работает: адреса входа, выдачи токенов и самого
MCP клиент берёт из метаданных, и они обязаны быть внешними. Поэтому они
задаются явно переменными окружения — обеими, у веба и у MCP: веб объявляет
себя сервером авторизации для MCP, MCP называет веб своим сервером авторизации.

Без любой из двух OAuth выключен, и обе поверхности работают как до D417.

Правило разбора одно на оба блока (`web` и `mcp` — пиры и друг друга не
импортируют), поэтому оно здесь, ярусом ниже.
"""

from __future__ import annotations

from urllib.parse import urlsplit

ADMIN_PUBLIC_URL_VAR = "ADMIN_PUBLIC_URL"
MCP_PUBLIC_URL_VAR = "MCP_PUBLIC_URL"

#: Документ защищённого ресурса (RFC 9728): MCP называет в нём свой сервер авторизации.
PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource"

#: Метаданные сервера авторизации (RFC 8414).
AUTHORIZATION_SERVER_PATH = "/.well-known/oauth-authorization-server"

#: Хосты, которым разрешён `http`: стенд на машине разработчика и тесты.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


def parse_public_url(raw: str, *, var: str) -> str | None:
    """Внешний адрес без хвостовой «/». Пусто — `None`; кривой — `ValueError` с именем переменной.

    Только `https` (кроме петли): адрес уходит в метаданные OAuth, и по `http`
    коды и токены поехали бы открытым текстом. Строки запроса и якоря нет:
    к адресу дописываются пути, и хвост `?x` сломал бы каждый.
    """
    value = raw.strip()
    if not value:
        return None
    части = urlsplit(value)
    годен = (
        (части.scheme == "https" or (части.scheme == "http" and части.hostname in _LOOPBACK_HOSTS))
        and bool(части.hostname)
        and not части.query
        and not части.fragment
        and not части.username
        and not части.password
        and "\\" not in value
    )
    if not годен:
        raise ValueError(
            f"{var} — внешний адрес вида https://хост[/путь] без строки запроса; "
            f"http допустим только для localhost и 127.0.0.1"
        )
    return value.rstrip("/")
