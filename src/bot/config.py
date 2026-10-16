"""Окружение бота: токен, кому отвечать, как запускаться.

Площадка — деталь реализации (решение D004): режим переключается переменной
`BOT_MODE`, значения по умолчанию для секретов не подставляются намеренно —
бот без токена не поднимается. Кого бот пускает, решает привязка Telegram ID
к учётке веба (`src/bot/access.py`), а не список в окружении: прежний
`ALLOWED_TELEGRAM_IDS` снят (D517).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from src.domain.walk_users import parse_walk_users, walk_open_to

from .errors import BotConfigError, BotTextError
from .texts import DEFAULT_UI_LANG, UI_LANG_VAR, default_ui_lang

# Подавление ниже: S105 видит «TOKEN» в имени и считает строку зашитым секретом.
# Здесь это имя переменной окружения, а не значение — сам токен в коде
# не появляется ни в каком виде.
TOKEN_VAR = "TELEGRAM_BOT_TOKEN"  # noqa: S105
MODE_VAR = "BOT_MODE"
#: Имя проверяющего для шапки отчёта по его Telegram ID (T063, решение D032).
#: Переменная необязательна: без неё имя берётся из профиля Telegram.
AUDITOR_NAMES_VAR = "AUDITOR_NAMES"

#: Адрес мини-аппа обхода (#418) — страница `/tg/walk` веб-сервиса. Пусто —
#: кнопки «Обход точки» нет, и бот ведёт себя как до мини-аппа. Telegram
#: открывает мини-апп только по https, поэтому иной адрес — отказ на старте.
WALK_URL_VAR = "BOT_WALK_URL"

#: Язык интерфейса до начала проверки (T131). Имя и разбор живут в `texts.py`,
#: рядом с самим каталогом языков, — здесь только проверка на старте.

#: `.env.example` объявляет только polling — единственный поддерживаемый режим
#: сейчас (разработка без публичного адреса). `webhook` зарезервирован решением
#: D004 на будущий переезд, но реализации у него пока нет: принимать значение,
#: для которого нет обработчика, хуже, чем отказать сразу на старте.
KNOWN_MODES = ("polling",)
DEFAULT_MODE = "polling"


@dataclass(frozen=True)
class BotSettings:
    """Разобранное окружение бота."""

    token: str
    mode: str
    #: Язык интерфейса стенда — тот, которым бот здоровается до начала проверки
    #: (T131). Начатая проверка перебивает его своим полем `ui_lang`.
    ui_lang: str = DEFAULT_UI_LANG
    #: Telegram ID → имя проверяющего, как оно должно стоять в отчёте партнёру.
    #: Пустая карта — законное состояние: имена возьмутся из профилей Telegram.
    auditor_names: Mapping[int, str] = field(default_factory=dict)
    walk_url: str | None = None
    #: Круг тестеров мини-аппа (`WALK_USERS`). `None` — кнопка всем с доступом.
    walk_users: frozenset[int] | None = None

    def walk_url_for(self, user_id: int) -> str | None:
        """Адрес мини-аппа для этого человека; `None` — кнопки ему нет."""
        if self.walk_url is None or not walk_open_to(self.walk_users, user_id):
            return None
        return self.walk_url


def _required(env: Mapping[str, str], name: str) -> str:
    raw = (env.get(name) or "").strip()
    if not raw:
        raise BotConfigError(
            f"Не задана переменная окружения {name}. Пример значения — в .env.example"
        )
    return raw


def _parse_auditor_names(raw: str) -> dict[int, str]:
    """Разобрать карту «ID:имя» через запятую.

    Кривая запись — отказ на старте, а не пропуск: пропущенная строка означала
    бы, что в отчёт партнёру молча уедет имя из профиля Telegram, и заметить
    это можно только по готовому отчёту.

    Сверки со списком разрешённых ID нет (D286, D517): кто работает ботом,
    решает привязка к учётке, а назвать человека в шапке отчёта уместно.
    """
    names: dict[int, str] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        if ":" not in piece:
            raise BotConfigError(
                f"{AUDITOR_NAMES_VAR}: запись «{piece}» без двоеточия. "
                f"Нужен вид 111111:Имя Фамилия через запятую"
            )
        raw_id, _, name = piece.partition(":")
        key, value = raw_id.strip(), name.strip()
        if not key.lstrip("-").isdigit():
            raise BotConfigError(
                f"{AUDITOR_NAMES_VAR}: «{key}» — не Telegram ID. Нужно число до двоеточия"
            )
        if not value:
            raise BotConfigError(f"{AUDITOR_NAMES_VAR}: у ID {key} пустое имя")
        names[int(key)] = value
    return names


def _parse_ui_lang(env: Mapping[str, str]) -> str:
    """Язык интерфейса стенда — или отказ на старте (T131).

    Разбор один на всех (`texts.default_ui_lang`), здесь он только переводится
    в отказ конфигурации: неизвестный язык обязан останавливать бота на старте,
    а не всплывать первой строкой в чате. Цена молчания — демо, тихо съехавшее
    на русский из-за опечатки в переменной, и узнают об этом на показе.
    """
    try:
        return default_ui_lang(env)
    except BotTextError as exc:
        raise BotConfigError(f"{UI_LANG_VAR}: {exc}") from exc


def _parse_walk_url(raw: str) -> str | None:
    url = raw.strip()
    if not url:
        return None
    if not url.startswith("https://"):
        raise BotConfigError(
            f"{WALK_URL_VAR} — «{url}»: Telegram открывает мини-апп только по https://"
        )
    return url


def _parse_walk_users(env: Mapping[str, str]) -> frozenset[int] | None:
    try:
        return parse_walk_users(env)
    except ValueError as exc:
        raise BotConfigError(str(exc)) from exc


def load_bot_settings(env: Mapping[str, str] | None = None) -> BotSettings:
    """Прочитать и проверить окружение бота. Отказ — `BotConfigError`."""
    src = os.environ if env is None else env
    token = _required(src, TOKEN_VAR)
    mode = (src.get(MODE_VAR) or DEFAULT_MODE).strip().lower()
    if mode not in KNOWN_MODES:
        raise BotConfigError(
            f"Режим «{mode}» ({MODE_VAR}) не поддержан. Доступно: {', '.join(KNOWN_MODES)}"
        )
    names = _parse_auditor_names(src.get(AUDITOR_NAMES_VAR) or "")
    return BotSettings(
        token=token,
        mode=mode,
        ui_lang=_parse_ui_lang(src),
        auditor_names=names,
        walk_url=_parse_walk_url(src.get(WALK_URL_VAR) or ""),
        walk_users=_parse_walk_users(src),
    )
