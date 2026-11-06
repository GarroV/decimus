"""Сообщение владельцу о каждом входе главного админа в админку (D720).

Вопрос — «это вошёл я?». Главный админ (`superadmin`) открыл сессию любым способом — Google,
пароль (после второй ступени), ключ доступа — владельцу уходит одно короткое сообщение: кто,
каким способом, с какого устройства и адреса, когда, и ссылка на «Выйти везде» в «Настройках»
на случай, если вошёл не он. Страны или города по адресу в продукте нет — сообщение их не
называет.

Канал — тот же, что у оповещений о подключениях (`src/notify/furca.py`, `FURCA_NOTIFY_URL` и
`FURCA_SECRET`); нового нет. Канала нет — ничего не уходит; в демо — никогда. Отправка идёт в
отдельном потоке: таймаут канала не задерживает вход, а сбой — строка в журнал, вход цел.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import urllib.error
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.demo import DEMO_VAR
from src.domain.journal import METHOD_GOOGLE, METHOD_PASSKEY, METHOD_PASSWORD
from src.domain.public_urls import ADMIN_PUBLIC_URL_VAR, parse_public_url
from src.notify import furca

logger = logging.getLogger(__name__)

#: Роль, чей вход оповещает: адресат один, владелец (главный админ).
ALERTED_ROLE = "superadmin"
SIGNOUT_PATH = "/settings?tile=signout"

_METHODS = {
    METHOD_GOOGLE: "через Google",
    METHOD_PASSWORD: "логином и паролем",
    METHOD_PASSKEY: "ключом доступа",
}
#: Первое совпадение выигрывает: Edge и Opera несут в строке и «Chrome», а Chrome — «Safari».
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("CriOS/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)
_MAX_RAW = 60
_SPACES = re.compile(r"\s+")


def device(user_agent: str | None) -> str:
    """Браузер и система коротко («Chrome на macOS»); не опознано — начало сырой строки."""
    raw = (user_agent or "").strip()
    if not raw:
        return "устройство неизвестно"
    browser = next((name for mark, name in _BROWSERS if mark in raw), None)
    system = next((name for mark, name in _SYSTEMS if mark in raw), None)
    if browser and system:
        return f"{browser} на {system}"
    return browser or system or _SPACES.sub(" ", raw)[:_MAX_RAW]


def compose(
    *,
    login: str,
    method: str,
    ip: str | None,
    user_agent: str | None,
    moment: datetime,
    base_url: str | None,
) -> str:
    """Текст сообщения: три строки — кто и как, откуда и когда, что делать."""
    how = _METHODS.get(method, method)
    when = moment.astimezone(UTC).strftime("%d.%m %H:%M UTC")
    where = f"{device(user_agent)}, адрес {ip or 'неизвестен'}, {when}"
    way_out = (
        f"Если это не вы — выйти везде: {base_url}{SIGNOUT_PATH}"
        if base_url
        else "Если это не вы — «Настройки» → «Выйти везде»."
    )
    return f"Вход в админку Decimus: {login} {how}.\n{where}.\n{way_out}"


def _base_url(env: Mapping[str, str]) -> str | None:
    try:
        return parse_public_url(env.get(ADMIN_PUBLIC_URL_VAR) or "", var=ADMIN_PUBLIC_URL_VAR)
    except ValueError:
        return None


def _deliver(target: tuple[str, str], text: str) -> None:
    """Отправка; любой сбой — строка в журнал, не исключение (вход уже состоялся)."""
    try:
        furca.send(target, text, furca.ALERT)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Сообщение о входе главного админа не ушло (%s)", exc)
    except Exception:
        logger.exception("Сообщение о входе главного админа не ушло: непредвиденный сбой")


def notify_login(
    account: Any,
    *,
    method: str,
    ip: str | None,
    user_agent: str | None,
    env: Mapping[str, str] | None = None,
    background: bool = True,
) -> bool:
    """Сообщить владельцу о входе. Возвращает, поставлена ли отправка (канал есть, роль та)."""
    if str(account.role) != ALERTED_ROLE:
        return False
    source = os.environ if env is None else env
    if (source.get(DEMO_VAR) or "").strip() not in ("", "0"):
        return False
    target = furca.channel(source)
    if target is None:
        return False
    try:
        text = compose(
            login=str(account.login),
            method=method,
            ip=ip,
            user_agent=user_agent,
            moment=datetime.now(UTC),
            base_url=_base_url(source),
        )
    except Exception:
        logger.exception("Сообщение о входе главного админа не собралось")
        return False
    if background:
        threading.Thread(target=_deliver, args=(target, text), daemon=True).start()
    else:
        _deliver(target, text)
    return True
