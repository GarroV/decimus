"""Отправка отзыва из кнопки «Обратная связь» в чат Telegram команды (D761 п.6).

**ВЫКЛЮЧЕНО, ПОКА ЧАТ НЕ ЗАДАН.** Чат — настройка главного админа во вкладке «Обратная
связь» (`db.feedback.chat_id`). Миграция чат не задаёт, и пока его нет, `deliver` ничего не
шлёт и сети не касается: отзыв только сохраняется. Текст сообщения, адресат и условие
отправки согласует владелец (правило «никакой коммуникации с людьми без владельца»): включить
отправку — значит задать чат уже после его «да».

Шлёт Bot API тем же ботом проекта (`TELEGRAM_BOT_TOKEN`), простым текстом без разметки: в
тексте человека могут быть любые знаки. Фото в Telegram не уходят — их количество названо в
сообщении, сами они лежат в «Администрировании»: на снимках бывают данные проверок.

Сбой отправки отзыв не ломает: он уже записан, итог (код причины, без текста ответа и без
адреса с токеном) ложится в строку отзыва и в журнал.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from src.db import feedback as db_feedback

logger = logging.getLogger(__name__)

TOKEN_VAR = "TELEGRAM_BOT_TOKEN"  # noqa: S105 — имя переменной, а не токен
API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SEC = 5
#: Предел текста сообщения Bot API — 4096; запас под шапку.
MAX_TEXT = 3300

#: Коды причин в строке отзыва: коротко и без чужого текста.
NO_TOKEN = "no_token"  # noqa: S105 — код причины, не токен
NETWORK = "network"
REFUSED = "refused"

Sender = Callable[[str, str], str | None]


def message(
    *,
    login: str,
    role: str,
    space: str,
    page: str,
    body: str,
    photos: int,
    moment: datetime,
) -> str:
    """Текст сообщения команде: кто, откуда, когда, что написал и сколько фото."""
    when = moment.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")
    text = body if len(body) <= MAX_TEXT else body[: MAX_TEXT - 1] + "…"
    lines = [
        "💬 Обратная связь · Decimus",
        f"{login} · {role} · {space} · {when}",
        f"Страница: {page}",
        "",
        text,
    ]
    if photos:
        lines += ["", f"Фото: {photos} — в «Администрирование → Обратная связь»"]
    return "\n".join(lines)


def send(chat: str, text: str) -> str | None:
    """Отправить одно сообщение. `None` — ушло, иначе код причины."""
    token = (os.environ.get(TOKEN_VAR) or "").strip()
    if not token:
        return NO_TOKEN
    payload = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(  # noqa: S310 — адрес Bot API задан константой
        API.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
            answer = json.load(response)
    except urllib.error.HTTPError as exc:
        return f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        # Адрес запроса содержит токен: в журнал и в строку — только код.
        return NETWORK
    return None if answer.get("ok") else REFUSED


def deliver(
    feedback_id: str,
    *,
    login: str,
    role: str,
    space: str,
    page: str,
    body: str,
    photos: int,
    sender: Sender = send,
) -> bool:
    """Отправить сохранённый отзыв, если чат задан. `True` — ушло.

    Чат не задан — `False` без отправки и без отметки в строке. Любой сбой (чтение чата,
    сеть, запись итога) идёт в журнал и наружу не выходит: отзыв уже в базе.
    """
    try:
        chat = db_feedback.chat_id()
        if chat is None:
            return False
        text = message(
            login=login,
            role=role,
            space=space,
            page=page,
            body=body,
            photos=photos,
            moment=datetime.now(UTC),
        )
        error = sender(chat, text)
        db_feedback.record_delivery(feedback_id, sent=error is None, error=error)
    except Exception:
        logger.exception("Отзыв %s сохранён, но отправка в Telegram не выполнена", feedback_id)
        return False
    if error is not None:
        logger.warning("Отзыв %s не ушёл в Telegram: %s", feedback_id, error)
    return error is None
