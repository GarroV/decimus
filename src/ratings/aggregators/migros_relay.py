"""Ретранслятор Migros Yemek на домашнем сервере (D434).

Migros отвечает 403 адресу сервера площадки целиком, а с домашнего адреса
карточка магазина открыта. Поэтому прод ходит за ней сюда, на MUSPELHEIM, по
сети Tailscale, и ретранслятор делает ровно один вид запроса:

    GET /stores/<slug>  →  GET https://www.migros.com.tr/rest/food-bff/api/stores/<slug>

Это не открытый прокси: хост зашит, `slug` проверяется по шаблону, редиректы не
идут, тело ограничено. Ответ Migros отдаётся как есть, с его кодом, — решает
сборщик на проде (`migros.py`). `GET /health` — жив ли ретранслятор. Всё прочее
— 404. Слушает только локальный адрес контейнера; в сеть Tailscale его выводит
`tailscale serve` (docs/17-aggregators.md, «Migros Yemek через домашний сервер»).

Зависимостей нет — только стандартная библиотека: образ — голый Python.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger("migros_relay")

UPSTREAM = "https://www.migros.com.tr/rest/food-bff/api/stores/{slug}"
_PATH = re.compile(r"^/stores/(?P<slug>[a-z0-9][a-z0-9-]{0,159})$")
BODY_MAX_BYTES = 2_000_000
TIMEOUT_SEC = 20
GAP_SEC = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

_lock = threading.Lock()
_last = [0.0]


def target(path: str) -> str | None:
    """Адрес Migros для пути запроса или `None` — такого ретранслятор не делает."""
    match = _PATH.fullmatch(path)
    return UPSTREAM.format(slug=match["slug"]) if match else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def fetch(url: str) -> tuple[int, bytes]:
    """Код и тело ответа Migros; не чаще раза в `GAP_SEC`."""
    with _lock:
        wait = GAP_SEC - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
    request = urllib.request.Request(  # noqa: S310 — хост зашит в UPSTREAM
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_SEC) as resp:
            return int(resp.status), resp.read(BODY_MAX_BYTES)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(BODY_MAX_BYTES) if exc.fp else b""


class Handler(BaseHTTPRequestHandler):
    server_version = "migros-relay"
    sys_version = ""

    def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b'{"ok":true}')
            return
        url = target(self.path)
        if url is None:
            self._send(404, b'{"error":"not_found"}')
            return
        try:
            status, body = fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Migros не ответил: %s", type(exc).__name__)
            self._send(502, json.dumps({"error": "upstream", "kind": type(exc).__name__}).encode())
            return
        self._send(status, body)

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s %s", self.address_string(), format % args)


def main(host: str = "0.0.0.0", port: int = 9021) -> None:  # noqa: S104 — внутри контейнера
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
