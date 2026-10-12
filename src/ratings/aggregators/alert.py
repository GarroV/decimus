"""Уведомление о сбое суточного сбора агрегаторов (D434).

Migros ходит через домашний сервер, а тот засыпает и сам не просыпается, —
сбой там ожидаем, и он не должен быть молча пустой колонкой. Поэтому после
суточного сбора бот пишет одному человеку — тому, чей Telegram ID стоит в
`AGG_ALERT_CHAT_ID`, — если хоть один агрегатор не собрался. Переменная пуста —
никому ничего не уходит (правило: сообщение людям — только по «да» владельца на
текст, адресата и условие). Сбор по заявке не уведомляет: его исход и так видит
тот, кто нажал кнопку.

Здесь — только решение «писать ли и что»: чистая функция над итогами сбора.
"""

from __future__ import annotations

from collections.abc import Sequence

from .collect import Outcome

CHAT_VAR = "AGG_ALERT_CHAT_ID"
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


def chat_id(raw: str | None) -> int | None:
    """Telegram ID из переменной; пусто или не число — уведомление выключено."""
    text = (raw or "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


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
