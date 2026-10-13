"""Уведомление о сбое суточного сбора агрегаторов (D434).

Migros ходит через домашний сервер, а тот засыпает и сам не просыпается, —
сбой там ожидаем, и он не должен быть молча пустой колонкой. Поэтому после
суточного сбора, если хоть один агрегатор не собрался, уходит одна тревога в
канал FURCA (D438, D439): `POST {FURCA_NOTIFY_URL}/notify` с ключом
`FURCA_SECRET`, проект `decimus`, вид `alert` — тем же путём, что тревоги
бэкапов сервера. Канал доводит её до владельца в Telegram. Переменные не заданы —
никуда ничего не уходит. Сбор по заявке не уведомляет: его исход и так видит
тот, кто нажал кнопку.

Решение «писать ли и что» — чистая функция `message`; отправка — `send`.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.request
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from .collect import Outcome

URL_VAR = "FURCA_NOTIFY_URL"
SECRET_VAR = "FURCA_SECRET"  # noqa: S105 — имя переменной, не значение
PROJECT = "decimus"
REASON_MAX = 160
TIMEOUT_SEC = 15

#: Подписи площадок в сообщении — как на странице рейтингов.
_NAMES = {
    "wolt": "Wolt", "bolt_food": "Bolt Food", "glovo": "Glovo", "chowdeck": "Chowdeck",
    "trendyol_go": "Trendyol Go", "yemeksepeti": "Yemeksepeti", "pyszne_pl": "Pyszne.pl",
    "yandex_eda": "Yandex Eda", "migros_yemek": "Migros Yemek",
}  # fmt: skip

_TEXT = {
    "ru": {
        "head": "Децимус: суточный сбор оценок агрегаторов прошёл с ошибками.",
        "tail": "Оценки этих площадок не обновятся до следующего удачного сбора.",
        "migros": "Migros ходит через домашний сервер — проверь, не спит ли он.",
    },
    "en": {
        "head": "Decimus: the daily aggregator ratings run had failures.",
        "tail": "These platforms' ratings will not update until the next successful run.",
        "migros": "Migros goes through the home server — check that it is awake.",
    },
}


def _is_internal_host(host: str) -> bool:
    """Внутреннее имя: localhost, имя без точки (сеть docker) или локальный адрес."""
    if host == "localhost" or "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # имя с точкой — публичное
    return address.is_loopback or address.is_private


def channel(env: Mapping[str, str]) -> tuple[str, str] | None:
    """Адрес `/notify` канала и ключ; чего-то нет — уведомление выключено.

    `http://` годится только для внутреннего имени (localhost, имя без точки);
    внешний хост по открытому http — тоже выключено, нужен https.
    """
    base = (env.get(URL_VAR) or "").strip().rstrip("/")
    secret = (env.get(SECRET_VAR) or "").strip()
    if not base.startswith(("http://", "https://")) or not secret:
        return None
    # Ключ канала уходит заголовком: по открытому http через интернет он ушёл бы
    # читаемым. http — только для внутренних имён, иначе https обязателен.
    if base.startswith("http://") and not _is_internal_host(urlsplit(base).hostname or ""):
        return None
    return f"{base}/notify", secret


def send(target: tuple[str, str], text: str) -> None:
    """Отправить тревогу в канал; ошибка сети или канала — исключение вызывающему."""
    url, secret = target
    request = urllib.request.Request(  # noqa: S310 — адрес из окружения площадки
        url,
        data=json.dumps({"project": PROJECT, "kind": "alert", "text": text}).encode(),
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
        response.read()


def message(outcomes: Sequence[Outcome], lang: str = "ru") -> str | None:
    """Текст уведомления или `None` — все агрегаторы собрались, писать не о чем."""
    failed = [o for o in outcomes if not o.ok]
    if not failed:
        return None
    words = _TEXT.get(lang, _TEXT["en"])
    lines = [words["head"], ""]
    for o in failed:
        reason = (o.error or "").strip().replace("\n", " ")
        if len(reason) > REASON_MAX:
            reason = reason[: REASON_MAX - 1] + "…"
        lines.append(f"• {_NAMES.get(o.aggregator, o.aggregator)}: {reason}".rstrip(": "))
    lines += ["", words["tail"]]
    if any(o.aggregator == "migros_yemek" for o in failed):
        lines.append(words["migros"])
    return "\n".join(lines)
