"""Общее для сборщиков агрегаторов: найденная точка, HTTP с паузой и повтором.

Агрегаторы — неофициальные интерфейсы их же сайтов (docs/17-aggregators.md):
ответ может поменяться без предупреждения. Поэтому всё внешнее разбирается
осторожно — запись без нужного поля отбрасывается, а не роняет сбор, — и
каждый запрос идёт с паузой: частые запросы агрегаторы режут (Wolt — 429
после сотни подряд).
"""

from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
TIMEOUT_SEC = 40
RETRIES = 3
BACKOFF_SEC = 15
RETRY_CODES = frozenset({429, 500, 502, 503, 504})
#: Потолок тела ответа (F-126). Ответы агрегаторов — JSON со списком точек, самые
#: большие — единицы мегабайт; 20 МБ с большим запасом, а чужой сервер или
#: перехваченный канал не заставит читать гигабайты в память.
BODY_MAX_BYTES = 20_000_000
#: Общий срок на запрос со всеми повторами и паузами. Без повторов укладывается
#: (40 с), с тремя попытками и паузами 15 + 30 с — тоже (≈ 165 с); срок не даёт
#: суммарно зависнуть дольше, если сервер отвечает медленно на каждой попытке.
DEADLINE_SEC = 200.0


class AggregatorError(Exception):
    """Агрегатор не ответил или ответил не тем — текст для журнала сбора."""


@dataclass(frozen=True)
class Found:
    """Точка агрегатора, как её увидел сборщик, с оценкой на сегодня.

    `score is None` — у точки ещё нет оценок (новая). `lat/lng is None` —
    агрегатор координат не отдаёт (Glovo), привязка тогда задана справочником.
    """

    point_key: str
    name: str
    url: str | None
    lat: float | None
    lng: float | None
    score: float | None
    scale: int
    votes: int | None
    votes_exact: bool
    is_open: bool | None
    extra: Mapping[str, object] = field(default_factory=dict)


def is_dodo(name: object) -> bool:
    """Заведение Dodo Pizza по названию. «Dodonut», «Dodo Doner», «Dodo Burger»,
    «Dodos Tost» — не Додо: сеть везде называется «Dodo Pizza» / «Додо Пицца»
    (сверено по всем витринам 11.10.2026)."""
    text = str(name or "").lower()
    return "dodo pizza" in text or "додо пицца" in text


def number(value: object) -> float | None:
    """Число из ответа: 4.4, "4.4", "4,5". Иначе — None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def votes_of(value: object) -> tuple[int | None, bool]:
    """Число оценок и точное ли оно: 1467 → (1467, True); "500+", "(1500+)" → (…, False)."""
    if isinstance(value, bool):
        return None, True
    if isinstance(value, int):
        return value, True
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return int(digits), "+" not in value
    return None, True


#: Сеть Tailscale (CGNAT): канал между машинами шифрует сам Tailscale, поэтому
#: ретранслятору Migros на домашнем сервере (D434) хватает http. Плюс петля — тесты.
_PLAIN_HTTP_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("127.0.0.0/8"))


def _https(url: str) -> str:
    """Только https: адреса агрегаторов — константы кода, но схему держим явно.
    Исключение — http на адрес сети Tailscale или петлю, по IP, не по имени."""
    if url.startswith("https://"):
        return url
    parts = urlsplit(url)
    try:
        host = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        host = None
    if parts.scheme == "http" and host and any(host in net for net in _PLAIN_HTTP_NETS):
        return url
    raise AggregatorError(f"Не https-адрес: {url[:60]}")


class Http:
    """Запросы одного агрегатора: пауза перед каждым, повтор на 429/5xx."""

    def __init__(self, gap_sec: float, headers: Mapping[str, str] | None = None) -> None:
        self.gap_sec = gap_sec
        self.headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> object:
        request = urllib.request.Request(  # noqa: S310 — схема проверена в `_https`
            _https(url), headers={**self.headers, **(headers or {})}
        )
        return self._call(request)

    def post(self, url: str, body: object, headers: Mapping[str, str] | None = None) -> object:
        request = urllib.request.Request(  # noqa: S310 — схема проверена в `_https`
            _https(url),
            data=json.dumps(body).encode(),
            headers={**self.headers, "Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        return self._call(request)

    def _call(self, request: urllib.request.Request) -> object:
        last = ""
        deadline = time.monotonic() + DEADLINE_SEC
        for attempt in range(RETRIES):
            pause = self.gap_sec if attempt == 0 else BACKOFF_SEC * attempt
            if attempt and time.monotonic() + pause >= deadline:
                last = f"{last}, общий срок {DEADLINE_SEC:g} с"
                break
            time.sleep(pause)
            timeout = min(TIMEOUT_SEC, max(1.0, deadline - time.monotonic()))
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                    body = response.read(BODY_MAX_BYTES + 1)
                if len(body) > BODY_MAX_BYTES:
                    # Повтор тот же ответ не уменьшит.
                    raise AggregatorError(
                        f"Ответ больше {BODY_MAX_BYTES} байт — {request.full_url.split('?')[0]}"
                    )
                return json.loads(body)
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in RETRY_CODES:
                    break
            # ConnectionError — обрыв соединения (в том числе `RemoteDisconnected`):
            # так выглядит Tailscale, принявший соединение к уснувшему сервису.
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                last = exc.__class__.__name__
        raise AggregatorError(f"{last} — {request.full_url.split('?')[0]}")


def dig(payload: object, *path: str | int) -> object:
    """Значение по пути в ответе или None, если по дороге не то."""
    here = payload
    for step in path:
        if isinstance(step, int) and isinstance(here, list) and -len(here) <= step < len(here):
            here = here[step]
        elif isinstance(step, str) and isinstance(here, dict):
            here = here.get(step)
        else:
            return None
    return here


def items(payload: object, *path: str | int) -> list[object]:
    """Список по пути в ответе; не список — пусто."""
    found = dig(payload, *path)
    return found if isinstance(found, list) else []
