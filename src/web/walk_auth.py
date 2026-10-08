"""Кто открыл мини-апп обхода — по подписи Telegram, а не по куке админки (#418).

Мини-апп открывается из бота, внутри Telegram, и у аудитора нет учётки веба:
его опознаёт сам Telegram. Клиент кладёт в страницу строку `initData`,
подписанную ключом из токена бота, и сервер проверяет подпись тем же
токеном. Проверку подписи не пишем сами — берём `safe_parse_webapp_init_data`
из aiogram, который у проекта уже стоит ради бота: самописная сверка HMAC —
ровно то место, где ошибаются молча.

Отдельного списка допущенных здесь нет — и это решение, а не пропуск. Подпись
доказывает, кто открыл, а показывается ровно проверка ЕГО чата: завести её
мог только бот, а бот уже решил, пускать ли человека (`ALLOWED_TELEGRAM_IDS`
плюс привязанные через веб учётки, `src/bot/access.py`). Свой список здесь
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

from aiogram.utils.web_app import safe_parse_webapp_init_data

from src.domain.walk_users import parse_walk_users

#: Сколько живёт подпись. Telegram выдаёт свежую при каждом открытии, а
#: обход длится час-два; шесть часов — с запасом на свёрнутое окно, и при
#: этом утёкшая строка не живёт до завтра.
MAX_AGE_SECONDS = 6 * 60 * 60

TOKEN_VAR = "TELEGRAM_BOT_TOKEN"  # noqa: S105 — имя переменной, а не токен
PREVIEW_VAR = "WEB_WALK_PREVIEW_CHAT"

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
ENDPOINTS = frozenset(
    {
        PAGE_ENDPOINT,
        DATA_ENDPOINT,
        PHOTO_ENDPOINT,
        PHOTO_VIEW_ENDPOINT,
        FINDING_ENDPOINT,
        INFO_ENDPOINT,
        SUGGEST_ENDPOINT,
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

    @property
    def enabled(self) -> bool:
        return self.bot_token is not None or self.preview_chat is not None


def load_walk_settings(env: Mapping[str, str] | None = None) -> WalkSettings:
    """Настройки из окружения. Противоречивые — отказ на старте, а не на запросе."""
    src = os.environ if env is None else env
    token = (src.get(TOKEN_VAR) or "").strip() or None
    preview_raw = (src.get(PREVIEW_VAR) or "").strip()
    preview: int | None = None
    if preview_raw:
        if not preview_raw.lstrip("-").isdigit():
            raise ValueError(f"{PREVIEW_VAR}: «{preview_raw}» — не номер чата")
        if token is not None:
            raise ValueError(
                f"{PREVIEW_VAR} задан вместе с {TOKEN_VAR}: просмотр без подписи — только "
                "для стенда без бота, на проде он открыл бы обход любому"
            )
        preview = int(preview_raw)
        if not PREVIEW_CHATS[0] <= preview <= PREVIEW_CHATS[1]:
            raise ValueError(
                f"{PREVIEW_VAR}: чат {preview} не из вымышленного диапазона сидов "
                f"{PREVIEW_CHATS[0]}–{PREVIEW_CHATS[1]}. Просмотр без подписи пишет в "
                "проверку (D312) и на настоящий чат не открывается"
            )
    return WalkSettings(
        bot_token=token,
        preview_chat=preview,
        users=parse_walk_users(src),
    )


def chat_of(init_data: str, settings: WalkSettings, *, now: float | None = None) -> int:
    """Чат, чью проверку показывать: номер пользователя из подписанной строки.

    Мини-апп открывается из личного чата с ботом, а там номер чата равен
    номеру пользователя, — по нему бот и хранит проверку (`chat_<id>`).
    """
    if not init_data:
        if settings.preview_chat is not None:
            return settings.preview_chat
        raise WalkAccessError("нет initData")
    if settings.bot_token is None:
        raise WalkAccessError("токен бота не задан — подпись нечем проверить")
    try:
        data = safe_parse_webapp_init_data(settings.bot_token, init_data)
    except ValueError as exc:
        raise WalkAccessError("подпись initData не сошлась") from exc
    moment = time.time() if now is None else now
    if moment - data.auth_date.timestamp() > MAX_AGE_SECONDS:
        raise WalkAccessError("подпись initData устарела")
    if data.user is None:
        raise WalkAccessError("в initData нет пользователя")
    return data.user.id
