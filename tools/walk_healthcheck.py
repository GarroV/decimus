"""Проба здоровья сервиса мини-аппа обхода — изнутри его контейнера.

Стучится на страницу обхода по петле контейнера и требует ответа НАШЕГО
сервиса (`Server: decimus-walk`, см. `src/web/walk_main.py`): площадка общая, и
радоваться любому ответу на порту значит однажды порадоваться чужому.

Здоровьем считаются 200 (обход включён) и 404 (токена бота нет — обход
выключен, но сервис отвечает). Своя проба нужна потому, что запечённая в образ
ищет процесс бота (`Dockerfile`) и для этого сервиса была бы красной всегда.

    python tools/walk_healthcheck.py

Код возврата 0 — здоров, 1 — нет; причина одной строкой в stderr.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

SERVER_IDENT = "decimus-walk"
HEALTHY = (200, 404)
DEFAULT_PORT = "8269"
TIMEOUT_SEC = 4.0


def main() -> int:
    port = os.environ.get("WEB_PORT") or DEFAULT_PORT
    prefix = (os.environ.get("WEB_URL_PREFIX") or "").strip().strip("/")
    path = f"/{prefix}/tg/walk" if prefix else "/tg/walk"
    url = f"http://127.0.0.1:{port}{path}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=TIMEOUT_SEC) as got:
            status, server = got.status, got.headers.get("Server", "")
    except urllib.error.HTTPError as exc:
        status, server = exc.code, exc.headers.get("Server", "")
    except (urllib.error.URLError, OSError) as exc:
        print(f"сервис обхода не отвечает на {url}: {exc}", file=sys.stderr)
        return 1
    if server != SERVER_IDENT:
        print(f"на {url} ответил не сервис обхода: Server={server!r}", file=sys.stderr)
        return 1
    if status not in HEALTHY:
        print(f"сервис обхода ответил {status} на {url}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
