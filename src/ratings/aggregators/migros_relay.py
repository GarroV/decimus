"""Ретранслятор площадок на домашнем сервере (D434, D661).

Migros отвечает 403 адресу сервера площадки целиком, Яндекс Еда — 429 и 401, а
с домашнего адреса обе открыты. Поэтому прод ходит за ними сюда, на MUSPELHEIM,
по сети Tailscale, и ретранслятор делает ровно три вида запроса:

    GET  /stores/<slug>  →  GET  https://www.migros.com.tr/rest/food-bff/api/stores/<slug>
    POST /yandex/search  →  POST https://eda.yandex.by/eats/v1/full-text-search/v1/search
    GET  /yandex/catalog/<slug>?latitude=&longitude=
                         →  GET  https://eda.yandex.by/api/v2/catalog/<slug>?latitude=&longitude=

Это не открытый прокси: хосты зашиты, `slug` и координаты проверяются по шаблону,
тело поиска — только `text` и `location` с числами и пересобирается заново,
редиректы не идут, тело ограничено. Ответ площадки отдаётся как есть, с её
кодом, — решает сборщик на проде (`migros.py`, `yandex_eda.py`). Пауза между
запросами — своя у каждой площадки и на стороне ретранслятора. `GET /health` —
жив ли ретранслятор. Всё прочее — 404. Слушает только локальный адрес контейнера;
в сеть Tailscale его выводит `tailscale serve` (docs/17-aggregators.md,
«Площадки через домашний сервер»).

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
YANDEX_HOST = "https://eda.yandex.by"
YANDEX_SEARCH = YANDEX_HOST + "/eats/v1/full-text-search/v1/search"
YANDEX_CARD = YANDEX_HOST + "/api/v2/catalog/{slug}?latitude={lat}&longitude={lng}"
YANDEX_HEADERS = {"x-platform": "desktop_web"}
_YANDEX_CARD_PATH = re.compile(
    r"^/yandex/catalog/(?P<slug>[A-Za-z0-9][A-Za-z0-9_-]{0,159})"
    r"\?latitude=(?P<lat>-?\d{1,3}(?:\.\d{1,10})?)&longitude=(?P<lng>-?\d{1,3}(?:\.\d{1,10})?)$"
)
BODY_MAX_BYTES = 2_000_000
REQUEST_MAX_BYTES = 1_000
TEXT_MAX_CHARS = 64
TIMEOUT_SEC = 20
GAP_SEC = 1.0
#: Пауза до следующего запроса к Яндексу: на 1,5 с он отвечал 429 (D397).
YANDEX_GAP_SEC = 4.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

_lock = threading.Lock()
#: Когда ушёл последний запрос к площадке; у каждой своя пауза и свой замок.
_last: dict[str, float] = {"migros": 0.0, "yandex": 0.0}
_gaps = {"migros": GAP_SEC, "yandex": YANDEX_GAP_SEC}


def target(path: str) -> str | None:
    """Адрес Migros для пути запроса или `None` — такого ретранслятор не делает."""
    match = _PATH.fullmatch(path)
    return UPSTREAM.format(slug=match["slug"]) if match else None


def yandex_card_target(path: str) -> str | None:
    """Адрес карточки Яндекс Еды для пути запроса или `None`."""
    match = _YANDEX_CARD_PATH.fullmatch(path)
    if not match:
        return None
    return YANDEX_CARD.format(slug=match["slug"], lat=match["lat"], lng=match["lng"])


def _coordinate(value: object, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if abs(value) <= limit else None


def yandex_search_body(raw: bytes) -> bytes | None:
    """Тело поиска для Яндекс Еды, пересобранное из проверенных полей, или `None`.

    Пропускаются ровно `text` (короткая строка) и `location` с числами
    `latitude`, `longitude`; любое другое поле — отказ."""
    if len(raw) > REQUEST_MAX_BYTES:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(body, dict) or set(body) != {"text", "location"}:
        return None
    text, location = body["text"], body["location"]
    if not isinstance(text, str) or not 0 < len(text) <= TEXT_MAX_CHARS:
        return None
    if not isinstance(location, dict) or set(location) != {"latitude", "longitude"}:
        return None
    lat, lng = _coordinate(location["latitude"], 90), _coordinate(location["longitude"], 180)
    if lat is None or lng is None:
        return None
    return json.dumps({"text": text, "location": {"latitude": lat, "longitude": lng}}).encode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def fetch(url: str, body: bytes | None = None) -> tuple[int, bytes]:
    """Код и тело ответа площадки; не чаще раза в её паузу (`GAP_SEC`, `YANDEX_GAP_SEC`).

    `body` — тело POST (только поиск Яндекс Еды)."""
    site = "yandex" if url.startswith(YANDEX_HOST) else "migros"
    with _lock:
        wait = _gaps[site] - (time.monotonic() - _last[site])
        if wait > 0:
            time.sleep(wait)
        _last[site] = time.monotonic()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if site == "yandex":
        headers.update(YANDEX_HEADERS)
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(  # noqa: S310 — хосты зашиты в UPSTREAM и YANDEX_HOST
        url, data=body, headers=headers, method="POST" if body is not None else "GET"
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

    def _forward(self, url: str, body: bytes | None = None) -> None:
        try:
            status, reply = fetch(url) if body is None else fetch(url, body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Площадка не ответила: %s", type(exc).__name__)
            self._send(502, json.dumps({"error": "upstream", "kind": type(exc).__name__}).encode())
            return
        self._send(status, reply)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b'{"ok":true}')
            return
        url = target(self.path) or yandex_card_target(self.path)
        if url is None:
            self._send(404, b'{"error":"not_found"}')
            return
        self._forward(url)

    def do_POST(self) -> None:
        if self.path != "/yandex/search":
            self._send(404, b'{"error":"not_found"}')
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            size = -1
        body = self.rfile.read(size) if 0 < size <= REQUEST_MAX_BYTES else b""
        checked = yandex_search_body(body)
        if checked is None:
            self._send(400, b'{"error":"bad_request"}')
            return
        self._forward(YANDEX_SEARCH, checked)

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s %s", self.address_string(), format % args)


def main(host: str = "0.0.0.0", port: int = 9021) -> None:  # noqa: S104 — внутри контейнера
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
