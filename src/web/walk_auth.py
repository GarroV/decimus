"""Кто открыл мини-апп обхода — по подписи Telegram, а не по куке админки (#418).

Мини-апп открывается из бота, внутри Telegram, и у аудитора нет учётки веба:
его опознаёт сам Telegram. Клиент кладёт в страницу строку `initData`,
подписанную ключом из токена бота, и сервер проверяет подпись тем же
токеном. Проверку подписи не пишем сами — берём `safe_parse_webapp_init_data`
из aiogram, который у проекта уже стоит ради бота: самописная сверка HMAC —
ровно то место, где ошибаются молча.

Отдельного списка допущенных здесь нет — и это решение, а не пропуск. Подпись
доказывает, кто открыл, а показывается ровно проверка ЕГО чата: завести её
мог только бот, а бот уже решил, пускать ли человека (привязанные через веб
учётки, `src/bot/access.py`). Свой список здесь
разъехался бы с ботом при первой же привязке. Чужой без проверки увидит
«проверка не начата» — и ничего больше.

**Просмотр без Telegram — только стенду.** `WEB_WALK_PREVIEW_CHAT` открывает
экран без подписи на заданный чат: так прототип щупают с телефона по ссылке.
На проде переменная не задаётся; заданная вместе с токеном бота она
отклоняется на старте, чтобы стенд нельзя было перепутать с продом.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiogram.utils.web_app import safe_parse_webapp_init_data

from src.domain.walk_users import parse_walk_users

#: Сколько живёт подпись. Telegram выдаёт свежую при каждом открытии, а
#: обход длится час-два; шесть часов — с запасом на свёрнутое окно, и при
#: этом утёкшая строка не живёт до завтра.
MAX_AGE_SECONDS = 6 * 60 * 60

TOKEN_VAR = "TELEGRAM_BOT_TOKEN"  # noqa: S105 — имя переменной, а не токен
PREVIEW_VAR = "WEB_WALK_PREVIEW_CHAT"
#: Второй чат просмотра — для браузера с русским языком (`Accept-Language: ru`):
#: демо показывает мини-апп на русском целиком, с русской проверкой, а не
#: английскую проверку с русскими кнопками. Без него — один чат на всех.
PREVIEW_RU_VAR = "WEB_WALK_PREVIEW_CHAT_RU"

#: Чаты, на которые открывается просмотр без подписи: вымышленный диапазон
#: демо-сидов (`tools/seed_*`), с номером человека в Telegram не совпадёт. Второй
#: замок после «не вместе с токеном»: с D312 просмотр пишет, и пропавший на
#: проде токен при забытой переменной не должен открыть настоящую проверку.
PREVIEW_CHATS = (999_000_000_000, 999_999_999_999)

#: Адреса обхода, открытые без учётки админки: здесь опознаёт подпись Telegram.
#: Одна константа на два потребителя — заслон входа (`auth.OPEN_ENDPOINTS`) и
#: политику заголовков (`security_headers`), — чтобы они не разошлись.
PAGE_ENDPOINT = "walk_page"
DATA_ENDPOINT = "walk_data"
#: Запись из мини-аппа (D312): кадр, его показ, запись проверки, сведение о визите.
PHOTO_ENDPOINT = "walk_photo"
PHOTO_VIEW_ENDPOINT = "walk_photo_view"
FINDING_ENDPOINT = "walk_finding"
INFO_ENDPOINT = "walk_info"
#: Поиск пункта по кадру и словам (D330) — распознавание бота.
SUGGEST_ENDPOINT = "walk_suggest"
#: Мгновенная подсказка пункта, пока модель думает (#1267, D646): без модели.
HINT_ENDPOINT = "walk_hint"
#: Перевод свободного текста на язык отчёта (D394): ничего не пишет.
TRANSLATE_ENDPOINT = "walk_translate"
#: Приложение аудитора (D373): настройки и круг доступа к MCP.
APP_ENDPOINT = "walk_app"
#: Начало проверки из мини-аппа (D392): мастер с полями вместо чата.
START_ENDPOINT = "walk_start"
#: Пути тех же адресов. Здесь, а не в `walk.py`: их вешают и сервис обхода
#: (`walk.py`, `walk_write.py`), и админка, передающая ему запросы
#: (`walk_proxy.py`), — две копии путей разошлись бы молча.
PAGE_PATH = "/tg/walk"
DATA_PATH = "/tg/walk/data"
PHOTO_PATH = "/tg/walk/photo"
PHOTO_VIEW_PATH = "/tg/walk/photo/view"
FINDING_PATH = "/tg/walk/finding"
INFO_PATH = "/tg/walk/info"
SUGGEST_PATH = "/tg/walk/suggest"
HINT_PATH = "/tg/walk/hint"
TRANSLATE_PATH = "/tg/walk/translate"
APP_PATH = "/tg/walk/app"
START_PATH = "/tg/walk/start"
ENDPOINTS = frozenset(
    {
        PAGE_ENDPOINT,
        DATA_ENDPOINT,
        PHOTO_ENDPOINT,
        PHOTO_VIEW_ENDPOINT,
        FINDING_ENDPOINT,
        INFO_ENDPOINT,
        SUGGEST_ENDPOINT,
        HINT_ENDPOINT,
        TRANSLATE_ENDPOINT,
        APP_ENDPOINT,
        START_ENDPOINT,
    }
)

#: Заголовок, которым клиент отдаёт подписанную строку в запросах записи: тело
#: там занято кадром или JSON, а в адресе строка осела бы в журналах прокси.
INIT_DATA_HEADER = "X-Telegram-Init-Data"


class WalkAccessError(Exception):
    """Открывшего не опознали. Текст — для журнала, не для экрана."""


@dataclass(frozen=True)
class WalkSettings:
    """Чем мини-апп опознаёт открывшего. Пустое — мини-апп выключен."""

    bot_token: str | None
    preview_chat: int | None
    #: Круг тестеров (`WALK_USERS`, тот же, что у кнопки бота). `None` — все.
    users: frozenset[int] | None = None
    #: Чат просмотра для русскоязычного браузера (`WEB_WALK_PREVIEW_CHAT_RU`).
    preview_chat_ru: int | None = None

    @property
    def enabled(self) -> bool:
        return self.bot_token is not None or self.preview_chat is not None


def load_walk_settings(env: Mapping[str, str] | None = None) -> WalkSettings:
    """Настройки из окружения. Противоречивые — отказ на старте, а не на запросе."""
    src = os.environ if env is None else env
    token = (src.get(TOKEN_VAR) or "").strip() or None
    preview = _preview_chat(src, PREVIEW_VAR, token)
    preview_ru = _preview_chat(src, PREVIEW_RU_VAR, token)
    if preview_ru is not None and preview is None:
        raise ValueError(
            f"{PREVIEW_RU_VAR} задан без {PREVIEW_VAR}: русский чат — второй, не единственный"
        )
    return WalkSettings(
        bot_token=token,
        preview_chat=preview,
        users=parse_walk_users(src),
        preview_chat_ru=preview_ru,
    )


def _preview_chat(src: Mapping[str, str], var: str, token: str | None) -> int | None:
    """Чат просмотра из переменной `var`: пусто — нет; не из вымышленного диапазона — отказ."""
    raw = (src.get(var) or "").strip()
    if not raw:
        return None
    if not raw.lstrip("-").isdigit():
        raise ValueError(f"{var}: «{raw}» — не номер чата")
    if token is not None:
        raise ValueError(
            f"{var} задан вместе с {TOKEN_VAR}: просмотр без подписи — только "
            "для стенда без бота, на проде он открыл бы обход любому"
        )
    chat = int(raw)
    if not PREVIEW_CHATS[0] <= chat <= PREVIEW_CHATS[1]:
        raise ValueError(
            f"{var}: чат {chat} не из вымышленного диапазона сидов "
            f"{PREVIEW_CHATS[0]}–{PREVIEW_CHATS[1]}. Просмотр без подписи пишет в "
            "проверку (D312) и на настоящий чат не открывается"
        )
    return chat


def chat_of(
    init_data: str,
    settings: WalkSettings,
    *,
    now: float | None = None,
    max_age: int = MAX_AGE_SECONDS,
    lang: str | None = None,
) -> int:
    """Чат, чью проверку показывать: номер пользователя из подписанной строки.

    Мини-апп открывается из личного чата с ботом, а там номер чата равен
    номеру пользователя, — по нему бот и хранит проверку (`chat_<id>`).

    Просмотр без подписи: русскому браузеру (`lang == "ru"`) — русский чат, если он
    задан, остальным — основной.
    """
    if not init_data and settings.preview_chat is not None:
        if lang == "ru" and settings.preview_chat_ru is not None:
            return settings.preview_chat_ru
        return settings.preview_chat
    return int(_signed_user(init_data, settings, now=now, max_age=max_age).id)


def full_name_of(init_data: str, settings: WalkSettings) -> str:
    """Имя профиля Telegram из подписанной строки — как `User.full_name` у бота (D392).

    Нужно началу проверки: проверяющего в шапке отчёта называют по профилю, если
    его нет в карте имён. Просмотр без подписи имени не имеет — пусто.
    """
    if not init_data and settings.preview_chat is not None:
        return ""
    user = _signed_user(init_data, settings)
    return " ".join(part for part in (user.first_name, user.last_name) if part)


def _signed_user(
    init_data: str,
    settings: WalkSettings,
    *,
    now: float | None = None,
    max_age: int = MAX_AGE_SECONDS,
) -> Any:
    """Пользователь из строки с проверенной подписью и свежестью."""
    if not init_data:
        raise WalkAccessError("нет initData")
    if settings.bot_token is None:
        raise WalkAccessError("токен бота не задан — подпись нечем проверить")
    try:
        data = safe_parse_webapp_init_data(settings.bot_token, init_data)
    except ValueError as exc:
        raise WalkAccessError("подпись initData не сошлась") from exc
    moment = time.time() if now is None else now
    if moment - data.auth_date.timestamp() > max_age:
        raise WalkAccessError("подпись initData устарела")
    if data.user is None:
        raise WalkAccessError("в initData нет пользователя")
    return data.user
