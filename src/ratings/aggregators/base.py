"""Общее для сборщиков агрегаторов: найденная точка, HTTP с паузой и повтором.

Агрегаторы — неофициальные интерфейсы их же сайтов (docs/17-aggregators.md):
ответ может поменяться без предупреждения. Поэтому всё внешнее разбирается
осторожно — запись без нужного поля отбрасывается, а не роняет сбор, — и
каждый запрос идёт с паузой: частые запросы агрегаторы режут (Wolt — 429
после сотни подряд).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
TIMEOUT_SEC = 40
RETRIES = 3
BACKOFF_SEC = 15
RETRY_CODES = frozenset({429, 500, 502, 503, 504})


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


def _https(url: str) -> str:
    """Только https: адреса агрегаторов — константы кода, но схему держим явно."""
    if not url.startswith("https://"):
        raise AggregatorError(f"Не https-адрес: {url[:60]}")
    return url


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
        for attempt in range(RETRIES):
            time.sleep(self.gap_sec if attempt == 0 else BACKOFF_SEC * attempt)
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in RETRY_CODES:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
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
