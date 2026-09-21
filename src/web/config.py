"""Окружение веб-админки: адрес, порт, тенант, язык интерфейса, ключ подписи.

Тенант — обязательный параметр стенда и значения по умолчанию не имеет. Так же
устроено чтение истории (`src/db/queries.py`, T110): подстановка «default»
выглядела бы работающей ровно до второго тенанта, а потом показала бы историю
одной страны сотрудникам другой. Из веба тенант приходит один раз, из
окружения, а не из адреса: подставить его в адрес мог бы кто угодно. Вход
(T323) этого не меняет: учётка принадлежит арендатору, а стенд показывает
своего — и сверяется это на каждом запросе.

Адрес прослушивания — только петля, и это проверка, а не договорённость.
Причина та же, что у MCP (`src/mcp/config.py`): площадка общая, а история
проверок партнёров — не то, что публикуют по недосмотру. Наружу выводит
туннель (D100), сервер остаётся на петле; появление входа этого не отменяет —
опубликованный порт открыл бы соседям по машине ещё и форму входа для перебора.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import WebConfigError
from .texts import default_ui_lang

WEB_HOST_VAR = "WEB_HOST"
WEB_PORT_VAR = "WEB_PORT"
WEB_TENANT_VAR = "WEB_TENANT"
WEB_SECRET_KEY_VAR = "WEB_SECRET_KEY"  # noqa: S105 — это ИМЯ переменной, а не значение
WEB_TRUSTED_PROXIES_VAR = "WEB_TRUSTED_PROXIES"
WEB_URL_PREFIX_VAR = "WEB_URL_PREFIX"

#: Сколько СВОИХ звеньев стоит перед сервером, когда переменная не задана.
#: Ноль — не верить `X-Forwarded-For` вовсе: заголовок ставит кто угодно, и
#: доверие к нему по умолчанию раздало бы перебирающему бесконечный запас
#: «адресов» одной строкой в запросе (`src/web/remote.py`).
DEFAULT_TRUSTED_PROXIES = 0

#: Выше этого числа звеньев настройка не принимается. Это не предел
#: устройства, а ловушка на опечатку: `WEB_TRUSTED_PROXIES=10` при одном
#: туннеле велит брать адрес из начала цепочки — то есть оттуда, куда пишет
#: сам перебирающий.
MAX_TRUSTED_PROXIES = 8

#: Короче этого ключ подписи не принимается. Подобранный ключ означает
#: поддельную куку, то есть вход под кем угодно без пароля, — и «пусть будет
#: хоть какой-нибудь» здесь дороже, чем отказ подняться.
MIN_SECRET_KEY_LENGTH = 32

#: Сколько байт случайности берёт временный ключ, когда переменная не задана.
SECRET_KEY_BYTES = 32

DEFAULT_HOST = "127.0.0.1"
#: Следующий свободный за MCP: 8265 занимает сам сервер, 8266 — звено до него
#: (`docker-compose.yml`, сервис `link`). Номер — умолчание продукта, а не
#: рабочей копии: у копий свои диапазоны, и задаются они переменной, а не
#: правкой кода.
DEFAULT_PORT = 8267

#: Границы порта. Ниже 1024 — привилегированные, выше 65535 порта нет.
MIN_PORT = 1024
MAX_PORT = 65535


@dataclass(frozen=True)
class Settings:
    """Разобранное окружение блока."""

    host: str
    port: int
    tenant: str
    ui_lang: str
    #: Чем подписывается сессионная кука. Умолчания у поля нет намеренно:
    #: ключ подписи со значением по умолчанию — это ключ, известный всем.
    secret_key: str
    #: Ключ сделан на этот запуск, потому что переменная не задана. Стенд от
    #: этого работает, но сессии не переживут перезапуск, и сказать об этом
    #: вслух обязан тот, кто запускает (`src/web/__main__.py`).
    secret_key_is_ephemeral: bool = False
    #: Сколько своих звеньев (туннель, обратный проси) стоит перед сервером.
    #: От этого зависит, чей адрес считает ограничитель перебора: ноль —
    #: адрес соединения, больше — соответствующее звено `X-Forwarded-For`.
    trusted_proxies: int = DEFAULT_TRUSTED_PROXIES
    #: Путь, на котором админка живёт снаружи, когда общий вход площадки отдан
    #: не ей. Пусто — своё имя целиком, и это умолчание. Непустой префикс
    #: уходит в `SCRIPT_NAME`, поэтому ссылки страницы собираются вместе с ним:
    #: иначе первая же кнопка увела бы человека в корень чужого продукта.
    url_prefix: str = ""


def _parse_url_prefix(raw: str) -> str:
    """Путь, под которым админка видна снаружи. Пусто — под своим именем.

    Нужен там, где общий вход площадки уже занят соседним продуктом, а своего
    имени у админки нет: тогда снаружи её выделяют путём
    (`https://площадка/audit`), а не портом в адресе.

    Приводится к одному виду, а не принимается как написали: ведущая косая
    обязательна, хвостовая убирается. Иначе `audit` и `/audit/` дали бы разные
    `SCRIPT_NAME` при одном и том же намерении, а разошлись бы они молча —
    страница открылась бы, а ссылки на ней вели бы мимо.
    """
    путь = raw.strip().strip("/")
    if not путь:
        return ""
    return f"/{путь}"


def _parse_host(raw: str) -> str:
    host = raw.strip() or DEFAULT_HOST
    if host == "localhost":
        return host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise WebConfigError(
            f"Адрес {WEB_HOST_VAR}={host} не петля. Наружу админка выходит туннелем (D100), "
            f"а не открытым портом: площадка общая, и опубликованный порт отдал бы соседям "
            f"по машине форму входа для перебора вместе с историей проверок за ней"
        )
    return host


def _parse_port(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_PORT
    try:
        port = int(value)
    except ValueError:
        raise WebConfigError(f"Порт {WEB_PORT_VAR}={value} не число") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise WebConfigError(
            f"Порт {WEB_PORT_VAR}={port} вне допустимого: ожидается от {MIN_PORT} до {MAX_PORT}"
        )
    return port


def _parse_tenant(raw: str) -> str:
    tenant = raw.strip()
    if not tenant:
        raise WebConfigError(
            f"Не задана переменная окружения {WEB_TENANT_VAR}. Чью историю показывает этот "
            f"стенд — не додумывается: значения по умолчанию у тенанта нет намеренно"
        )
    return tenant


def _parse_secret_key(raw: str) -> tuple[str, bool]:
    """Ключ подписи сессионной куки: заданный или сделанный на этот запуск.

    **Незаданный ключ не мешает подняться, и это не послабление.** Стенд
    обязан заводиться одной командой, а случайные 32 байта криптографически
    сильнее любого ключа, который вписали бы «чтобы запустилось». Платится за
    это ровно одним: сессии не переживают перезапуск, — и об этом говорится
    вслух при старте, а не выясняется по вылетевшему человеку.

    **Заданный, но короткий — отказ.** Здесь послабление было бы настоящим:
    слабый ключ подбирается, а подобранный означает поддельную куку, то есть
    вход без пароля под любым логином.
    """
    key = raw.strip()
    if not key:
        return secrets.token_urlsafe(SECRET_KEY_BYTES), True
    if len(key) < MIN_SECRET_KEY_LENGTH:
        raise WebConfigError(
            f"Ключ {WEB_SECRET_KEY_VAR} короче {MIN_SECRET_KEY_LENGTH} знаков. Подобранный "
            f"ключ — это поддельная кука, то есть вход без пароля. Взять новый: "
            f"python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return key, False


def _parse_trusted_proxies(raw: str) -> int:
    """Сколько звеньев впереди считать своими. Пусто — ни одного.

    **Умолчание «не верить» выбрано сознательно, и цена у него есть.** За
    туннелем без этой настройки все запросы приходят с одного адреса, и
    счётчик по адресу становится общим на всех: перебор запрёт форму входа не
    только себе. Обратная ошибка дороже — доверие к `X-Forwarded-For` без
    своего звена впереди снимает счётчик по адресу совсем, а выглядит при этом
    работающим.
    """
    value = raw.strip()
    if not value:
        return DEFAULT_TRUSTED_PROXIES
    try:
        число = int(value)
    except ValueError:
        raise WebConfigError(f"Значение {WEB_TRUSTED_PROXIES_VAR}={value} не число") from None
    if not 0 <= число <= MAX_TRUSTED_PROXIES:
        raise WebConfigError(
            f"{WEB_TRUSTED_PROXIES_VAR}={число} вне допустимого: от 0 до "
            f"{MAX_TRUSTED_PROXIES}. Это число СВОИХ звеньев перед сервером "
            f"(туннель — одно), а не запас на будущее: чем оно больше, тем ближе "
            f"к началу цепочки берётся адрес, а начало пишет тот, кто пришёл"
        )
    return число


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Прочитать окружение админки. Отказ — `WebConfigError`."""
    src = os.environ if env is None else env
    secret_key, ephemeral = _parse_secret_key(src.get(WEB_SECRET_KEY_VAR) or "")
    return Settings(
        host=_parse_host(src.get(WEB_HOST_VAR) or ""),
        port=_parse_port(src.get(WEB_PORT_VAR) or ""),
        tenant=_parse_tenant(src.get(WEB_TENANT_VAR) or ""),
        ui_lang=default_ui_lang(src),
        secret_key=secret_key,
        secret_key_is_ephemeral=ephemeral,
        trusted_proxies=_parse_trusted_proxies(src.get(WEB_TRUSTED_PROXIES_VAR) or ""),
        url_prefix=_parse_url_prefix(src.get(WEB_URL_PREFIX_VAR) or ""),
    )
