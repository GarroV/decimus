"""Уведомление о сбое суточного сбора агрегаторов (D434).

Migros ходит через домашний сервер, а тот засыпает и сам не просыпается, —
сбой там ожидаем, и он не должен быть молча пустой колонкой. Поэтому после
суточного сбора, если хоть один агрегатор не собрался, уходит одна тревога в
канал FURCA (D438, D439): `POST {FURCA_NOTIFY_URL}/notify` с ключом
`FURCA_SECRET`, проект `decimus`, вид `alert` — тем же путём, что тревоги
бэкапов сервера. Канал доводит её до владельца в Telegram. Переменные не заданы —
никуда ничего не уходит. Сбор по заявке не уведомляет: его исход и так видит
тот, кто нажал кнопку.

Решение «писать ли и что» — чистая функция `message`; адрес канала и отправка — общие,
`src/notify/furca.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

# Адрес канала и отправка — общие с оповещениями о подключениях (`src/notify/furca.py`);
# имена остаются здесь: ими пользуются загрузчики и тесты.
from src.notify.furca import SECRET_VAR, URL_VAR, channel, send

from .collect import Outcome

__all__ = ["SECRET_VAR", "URL_VAR", "channel", "message", "send"]

REASON_MAX = 160

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
