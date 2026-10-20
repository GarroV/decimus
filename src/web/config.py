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
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from src.domain.demo import DEMO_URL_VAR, DEMO_VAR
from src.domain.public_urls import ADMIN_PUBLIC_URL_VAR, MCP_PUBLIC_URL_VAR, parse_public_url
from src.domain.tenants import canonical_tenant

from .errors import WebConfigError
from .texts import default_ui_lang

WEB_HOST_VAR = "WEB_HOST"
WEB_PORT_VAR = "WEB_PORT"
WEB_TENANT_VAR = "WEB_TENANT"
WEB_SECRET_KEY_VAR = "WEB_SECRET_KEY"  # noqa: S105 — это ИМЯ переменной, а не значение
WEB_TRUSTED_PROXIES_VAR = "WEB_TRUSTED_PROXIES"
#: Адреса своих звеньев (адрес или подсеть, через запятую; `*` — любой сосед):
#: только от них верим `X-Forwarded-*` (F-038 аудита 12.10, `src/web/proxy.py`).
WEB_TRUSTED_PROXY_ADDR_VAR = "WEB_TRUSTED_PROXY_ADDR"
#: Ключ фронта Cloudflare (тот же, что секрет `FRONT_KEY` у Worker'ов): если задан,
#: `X-Forwarded-*` верим только запросу с верным `X-Decimus-Front-Key`
#: (F-107 аудита, `src/web/proxy.py`). Не задан — доверие по подсети, как раньше.
WEB_FRONT_KEY_VAR = "WEB_FRONT_KEY"
WEB_URL_PREFIX_VAR = "WEB_URL_PREFIX"
WEB_LISTEN_NETWORK_VAR = "WEB_LISTEN_NETWORK"
#: Имя бота в Telegram без «@» — для ссылки привязки `t.me/<бот>?start=...`
#: (D286). Необязательна: без неё кнопки «Привязать бота» нет, а вкладка
#: называет переменную.
WEB_BOT_USERNAME_VAR = "WEB_BOT_USERNAME"
#: Слать ли `Strict-Transport-Security` (#489). Только для стенда, который
#: снаружи открывается ИСКЛЮЧИТЕЛЬНО по HTTPS: заголовок браузер помнит год, и
#: включённый на стенде без сертификата он закрыл бы стенд на этот год.
WEB_HSTS_VAR = "WEB_HSTS"
#: Где живёт сервис мини-аппа обхода (`python -m src.web.walk_main`), которому
#: админка передаёт адреса `/tg/walk*`. Админка состояние проверок только
#: читает; пишет в него этот сервис, отдельным контейнером со своим томом на
#: запись. Пусто — адресов обхода у админки нет.
WEB_WALK_UPSTREAM_VAR = "WEB_WALK_UPSTREAM"

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

#: «Любой сосед» в `WEB_TRUSTED_PROXY_ADDR`. Только явно: пустая переменная
#: значит «никому», а не «всем».
ANY_PEER = "*"

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
    #: Адреса и подсети своих звеньев (`WEB_TRUSTED_PROXY_ADDR`): заголовкам
    #: `X-Forwarded-*` верим только от них. Пусто — звено не названо.
    trusted_proxy_addrs: tuple[str, ...] = ()
    #: Ключ фронта (`WEB_FRONT_KEY`): пусто — origin ключ не проверяет. Значение
    #: секретное: в журнал и в `repr` не попадает.
    front_key: str = field(default="", repr=False)
    #: Путь, на котором админка живёт снаружи, когда общий вход площадки отдан
    #: не ей. Пусто — своё имя целиком, и это умолчание. Непустой префикс
    #: уходит в `SCRIPT_NAME`, поэтому ссылки страницы собираются вместе с ним:
    #: иначе первая же кнопка увела бы человека в корень чужого продукта.
    url_prefix: str = ""
    #: Имя бота для ссылки привязки (D286); `None` — привязка не настроена.
    bot_username: str | None = None
    #: Слать `Strict-Transport-Security` (`WEB_HSTS=1`). По умолчанию нет.
    hsts: bool = False
    #: Стенд открытого демо (`WEB_DEMO=1`, D524): вход `/demo` без пароля и плашка.
    #: На проде переменной нет, и `/demo` отвечает 404.
    demo: bool = False
    #: Адрес демо для кнопки лендинга (`WEB_DEMO_URL`). `None` — кнопки нет.
    demo_url: str | None = None
    #: Адрес сервиса мини-аппа обхода (`WEB_WALK_UPSTREAM`): `http://хост:порт`.
    #: `None` — адреса обхода админкой не отдаются.
    walk_upstream: str | None = None
    #: Внешний адрес админки (`ADMIN_PUBLIC_URL`, D417): издатель OAuth.
    admin_public_url: str | None = None
    #: Внешний адрес MCP (`MCP_PUBLIC_URL`, D417): ресурс, к которому выдаются токены.
    mcp_public_url: str | None = None
    #: Домен ключей доступа (`WEBAUTHN_RP_ID`, D463): хост внешнего адреса админки. Ключ
    #: привязан к нему навсегда: сменили адрес — ключи выпускаются заново. `None` — ключи
    #: доступа выключены (остаётся приложение-аутентификатор и резервные коды).
    webauthn_rp_id: str | None = None
    #: Происхождение, которое обязан назвать браузер (`WEBAUTHN_ORIGIN`): схема + хост
    #: внешнего адреса. Берётся из настройки, а не из заголовков запроса.
    webauthn_origin: str | None = None

    @property
    def webauthn_enabled(self) -> bool:
        """Ключи доступа включены: известны и домен, и происхождение (D463)."""
        return self.webauthn_rp_id is not None and self.webauthn_origin is not None

    @property
    def oauth_enabled(self) -> bool:
        """Подключение Claude входом через сайт включено: оба адреса заданы (D417)."""
        return self.admin_public_url is not None and self.mcp_public_url is not None


WEBAUTHN_RP_ID_VAR = "WEBAUTHN_RP_ID"
WEBAUTHN_ORIGIN_VAR = "WEBAUTHN_ORIGIN"

#: Публичные суффиксы, на которые ключ доступа не привязывается: ими пользуются тысячи
#: чужих сайтов. Привязка к `workers.dev` дала бы чужому Worker'у право на наши ключи, а
#: браузер такой домен всё равно отвергнет. Полный список (PSL) не тянем — это ловушка на
#: частую ошибку, а не замена списку.
_SHARED_SUFFIXES = frozenset({"workers.dev", "pages.dev", "github.io", "vercel.app", "netlify.app"})


def _parse_webauthn(
    src: Mapping[str, str], admin_public_url: str | None
) -> tuple[str | None, str | None]:
    """Домен и происхождение ключей доступа: из настроек, иначе из внешнего адреса админки."""
    origin_raw = (src.get(WEBAUTHN_ORIGIN_VAR) or "").strip()
    rp_raw = (src.get(WEBAUTHN_RP_ID_VAR) or "").strip().lower()
    if origin_raw:
        try:
            origin = parse_public_url(origin_raw, var=WEBAUTHN_ORIGIN_VAR)
        except ValueError as отказ:
            raise WebConfigError(str(отказ)) from None
    elif admin_public_url:
        origin = admin_public_url
    else:
        origin = None
    if origin is None:
        if rp_raw:
            raise WebConfigError(
                f"{WEBAUTHN_RP_ID_VAR} задан без {WEBAUTHN_ORIGIN_VAR} и без {ADMIN_PUBLIC_URL_VAR}"
            )
        return None, None
    части = urlsplit(origin)
    if origin_raw and части.path:
        raise WebConfigError(
            f"{WEBAUTHN_ORIGIN_VAR} — только схема и хост (https://хост[:порт]), без пути"
        )
    # Из внешнего адреса берётся только происхождение: путь к нему не относится.
    origin = f"{части.scheme}://{части.netloc}"
    host = части.hostname or ""
    rp_id = rp_raw or host
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", rp_id) or re.fullmatch(
        r"[0-9.]+", rp_id
    ):
        raise WebConfigError(
            f"{WEBAUTHN_RP_ID_VAR}={rp_id!r} — нужен домен без схемы, порта и пути"
        )
    if host != rp_id and not host.endswith(f".{rp_id}"):
        raise WebConfigError(
            f"{WEBAUTHN_RP_ID_VAR}={rp_id!r} не годится для {origin}: домен ключа обязан быть "
            f"хостом происхождения или его родителем"
        )
    if rp_id in _SHARED_SUFFIXES:
        raise WebConfigError(
            f"{WEBAUTHN_RP_ID_VAR}={rp_id!r} — общий суффикс, на нём ключи не выпускаются: "
            f"укажите полный хост продукта"
        )
    return rp_id, origin


def _parse_public(src: Mapping[str, str], var: str) -> str | None:
    """Внешний адрес из окружения; кривой — отказ запуска, а не тихо выключенный OAuth."""
    try:
        return parse_public_url(src.get(var) or "", var=var)
    except ValueError as отказ:
        raise WebConfigError(str(отказ)) from None


#: Имя бота Telegram: 5–32 знака латиницы, цифр и `_` (правило Telegram).
_BOT_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")


def _parse_bot_username(raw: str) -> str | None:
    """Имя бота без «@». Пусто — привязка не настроена; непохожее — отказ запуска."""
    имя = raw.strip().removeprefix("@")
    if not имя:
        return None
    if not _BOT_USERNAME.fullmatch(имя):
        raise WebConfigError(
            f"{WEB_BOT_USERNAME_VAR} — имя бота в Telegram без «@»: 5–32 знака латиницы, "
            f"цифр и «_». Получено то, что ссылкой привязки не станет"
        )
    return имя


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


def _parse_walk_upstream(raw: str) -> str | None:
    """Адрес сервиса обхода: ровно `http://хост:порт`, без пути и учётных данных.

    Сервис живёт во внутренней сети стенда, поэтому только `http`. Путь не
    принимается: к нему приклеивается путь запроса, и лишний сегмент увёл бы
    каждый запрос мимо адресов обхода молча.
    """
    value = raw.strip()
    if not value:
        return None
    refusal = WebConfigError(
        f"{WEB_WALK_UPSTREAM_VAR}={value} не понят: ожидается http://хост:порт сервиса "
        f"обхода, без пути, например http://walk:8269"
    )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise refusal from None
    if (
        parts.scheme != "http"
        or not parts.hostname
        or port is None
        or parts.username is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise refusal
    return f"http://{parts.hostname}:{port}"


def _parse_listen_network(raw: str) -> bool:
    """Разрешено ли слушать сеть контейнера, а не только петлю.

    Нужен там, где перед админкой стоит общий прокси в сети контейнеров, а
    звена-посредника нет (VPS, общий Caddy в сети `edge`): петля контейнера
    оттуда недостижима. Порт при этом на хост не публикуется — достижим он
    ровно так же, как раньше через звено. Любое значение, кроме пусто, `0` и
    `1`, — отказ: опечатка не должна тихо означать «нет» или «да».
    """
    value = raw.strip()
    if value in ("", "0"):
        return False
    if value == "1":
        return True
    raise WebConfigError(
        f"Значение {WEB_LISTEN_NETWORK_VAR}={value} не понято: ожидается 1 (слушать сеть "
        f"контейнера за общим прокси) или пусто/0 (только петля)"
    )


def _parse_demo(raw: str) -> bool:
    """Стенд ли демо. Пусто и `0` — нет, `1` — да, остальное — отказ запуска.

    Опечатка не смеет значить «да»: это вход без пароля.
    """
    value = raw.strip()
    if value in ("", "0"):
        return False
    if value == "1":
        return True
    raise WebConfigError(f"Значение {DEMO_VAR}={value} не понято: ожидается 1 или пусто/0")


def _parse_demo_url(raw: str) -> str | None:
    """Адрес демо для лендинга: только `https://…` без кавычек и пробелов."""
    value = raw.strip()
    if not value:
        return None
    if not value.startswith("https://") or any(c in value for c in " \"'<>"):
        raise WebConfigError(f"{DEMO_URL_VAR}={value} — ожидается адрес https://…")
    return value.rstrip("/")


def _parse_hsts(raw: str) -> bool:
    """Включён ли HSTS. Пусто и `0` — нет, `1` — да, остальное — отказ запуска.

    Опечатка не должна тихо значить ни «да» (стенд без сертификата закрыт на
    год), ни «нет» (защита, которую считают включённой, не работает).
    """
    value = raw.strip()
    if value in ("", "0"):
        return False
    if value == "1":
        return True
    raise WebConfigError(
        f"Значение {WEB_HSTS_VAR}={value} не понято: ожидается 1 (стенд снаружи только "
        f"по HTTPS, слать Strict-Transport-Security) или пусто/0 (не слать)"
    )


def _parse_host(raw: str, *, listen_network: bool = False) -> str:
    host = raw.strip() or DEFAULT_HOST
    if host == "localhost":
        return host
    try:
        адрес = ipaddress.ip_address(host)
    except ValueError:
        raise WebConfigError(f"Адрес {WEB_HOST_VAR}={host} не IP-адрес") from None
    if listen_network:
        return host
    if not адрес.is_loopback:
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
    tenant = canonical_tenant(raw)
    if not tenant:
        raise WebConfigError(
            f"Не задана переменная окружения {WEB_TENANT_VAR}. Чью историю показывает этот "
            f"стенд — не додумывается: значения по умолчанию у тенанта нет намеренно"
        )
    return tenant


def _parse_trusted_proxy_addrs(raw: str) -> tuple[str, ...]:
    """Адреса своих звеньев: адрес или подсеть через запятую, `*` — любой сосед.

    Кривая запись — отказ запуска: опечатка в адресе звена тихо означала бы
    «не верить никому», а в проде это 403 на каждую отправку формы.
    """
    части = tuple(часть.strip() for часть in raw.split(",") if часть.strip())
    for часть in части:
        if часть == ANY_PEER:
            continue
        try:
            ipaddress.ip_network(часть, strict=False)
        except ValueError:
            raise WebConfigError(
                f"{WEB_TRUSTED_PROXY_ADDR_VAR}: «{часть}» не адрес и не подсеть. Ожидается "
                f"адрес или подсеть своего звена через запятую, например 172.18.0.0/16"
            ) from None
    return части


def require_signing_key(settings: Settings) -> None:
    """Админка в сети контейнера без заданного ключа подписи — отказ запуска (F-008 аудита 12.10).

    Сеть контейнера (`WEB_LISTEN_NETWORK=1`, хост не петля) у админки — это прод
    за общим прокси; там временный ключ означает, что каждая выкатка молча
    выбрасывает всех и рвёт уход за согласием Google на полпути. На петле
    (разработка, стенд одной командой) временный ключ остаётся законным.

    Отдельной функцией, а не внутри `load_settings`: те же настройки читает
    сервис обхода, который слушает сеть на любом стенде, а ключом не подписывает
    ничего.
    """
    на_петле = settings.host == "localhost" or ipaddress.ip_address(settings.host).is_loopback
    if settings.secret_key_is_ephemeral and not на_петле:
        raise WebConfigError(
            f"Не задан {WEB_SECRET_KEY_VAR}, а админка слушает сеть контейнера "
            f"({WEB_LISTEN_NETWORK_VAR}=1). Временный ключ здесь — выход всех при каждой "
            f"выкатке. Взять ключ: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )


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
    admin_public_url = _parse_public(src, ADMIN_PUBLIC_URL_VAR)
    rp_id, origin = _parse_webauthn(src, admin_public_url)
    secret_key, ephemeral = _parse_secret_key(src.get(WEB_SECRET_KEY_VAR) or "")
    listen_network = _parse_listen_network(src.get(WEB_LISTEN_NETWORK_VAR) or "")
    return Settings(
        host=_parse_host(src.get(WEB_HOST_VAR) or "", listen_network=listen_network),
        port=_parse_port(src.get(WEB_PORT_VAR) or ""),
        tenant=_parse_tenant(src.get(WEB_TENANT_VAR) or ""),
        ui_lang=default_ui_lang(src),
        secret_key=secret_key,
        secret_key_is_ephemeral=ephemeral,
        trusted_proxies=_parse_trusted_proxies(src.get(WEB_TRUSTED_PROXIES_VAR) or ""),
        trusted_proxy_addrs=_parse_trusted_proxy_addrs(src.get(WEB_TRUSTED_PROXY_ADDR_VAR) or ""),
        front_key=(src.get(WEB_FRONT_KEY_VAR) or "").strip(),
        url_prefix=_parse_url_prefix(src.get(WEB_URL_PREFIX_VAR) or ""),
        bot_username=_parse_bot_username(src.get(WEB_BOT_USERNAME_VAR) or ""),
        hsts=_parse_hsts(src.get(WEB_HSTS_VAR) or ""),
        demo=_parse_demo(src.get(DEMO_VAR) or ""),
        demo_url=_parse_demo_url(src.get(DEMO_URL_VAR) or ""),
        walk_upstream=_parse_walk_upstream(src.get(WEB_WALK_UPSTREAM_VAR) or ""),
        admin_public_url=admin_public_url,
        mcp_public_url=_parse_public(src, MCP_PUBLIC_URL_VAR),
        webauthn_rp_id=rp_id,
        webauthn_origin=origin,
    )
