"""Что сказать `waitress` про звенья перед нами — и кому из соседей верить.

Отдельный модуль, а не часть точки входа, по одной причине: точка входа
подставляет `.env` в окружение процесса на уровне модуля — то есть при первом
же импорте. Тесту, которому нужна только эта функция, приезжали бы вместе с
ней боевые подключения, токены и ключи площадки; на прогоне это уже стоило
39 падений и записи в базу стенда вместо одноразовой (#356).

**Своё звено называется адресом, а не «любой сосед» (F-038 аудита 12.10).** В
проде сервер слушает сеть контейнера (`WEB_LISTEN_NETWORK`, D211), и общий
прокси приходит с адреса docker-сети. До 12.10 доверие здесь было `*`: любой,
кто дотянулся до порта контейнера (процесс на машине через опубликованный на
петле порт, соседний контейнер), сам выбирал себе адрес в `X-Forwarded-For`,
схему и хост — и с ним ключ счётчика перебора. Теперь адреса своих звеньев
(адрес или подсеть, через запятую) называет `WEB_TRUSTED_PROXY_ADDR`; заголовки
остальных вырезаются.

**Подсети мало: общий секрет сверяется самим origin (F-107).** Сосед по общей
сети тоже лежит в подсети звена, поэтому при `WEB_FRONT_KEY_MODE=enforce` верим
только запросу с верным `X-Decimus-Front-Key`. Режимы `off` и `log` нужны порядку
выката, чтобы не запереть живой вход, пока Caddy ключ ещё не пропускает.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from waitress.proxy_headers import proxy_headers_middleware

from .config import (
    ANY_PEER,
    FRONT_KEY_ENFORCE,
    FRONT_KEY_OFF,
    WEB_FRONT_KEY_MODE_VAR,
    Settings,
)

logger = logging.getLogger(__name__)

#: Заголовки звена, которым верим от своего звена. Всё, что не названо,
#: вырезается — именно этого мы и хотим от постороннего, который решит
#: представиться сам.
TRUSTED_HEADERS = frozenset({"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"})

#: Заголовок, в котором Worker фронта шлёт ключ (`front/src/proxy.js`); Caddy
#: проверяет его и пропускает дальше, origin сверяет ещё раз (F-107).
FRONT_KEY_ENVIRON = "HTTP_X_DECIMUS_FRONT_KEY"

#: Не чаще раза в такой срок пишем несовпадение ключа в режиме `log`: подделка
#: иначе заливает журнал, а наблюдателю хватает первого случая и повторов раз в минуту.
MISMATCH_LOG_INTERVAL_SECONDS = 60.0

WsgiApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]


def _на_петле(host: str) -> bool:
    return host == "localhost" or ipaddress.ip_address(host).is_loopback


def _proxy_options(settings: Settings) -> dict[str, Any]:
    """Что сказать `waitress` про звенья перед нами, когда приложение не обёрнуто.

    Без этого настройка `WEB_TRUSTED_PROXIES` не работала ВОВСЕ, хотя и
    читалась: `waitress` по умолчанию (`clear_untrusted_proxy_headers`) режет
    заголовки `X-Forwarded-*` на входе, потому что доверенного звена ему никто
    не назвал. До приложения они не доезжали, и следствий было два, оба тихих.
    Заслон происхождения считал запрос пришедшим по HTTP (`origin.over_https`),
    сравнивал со схемой `https` в `Origin` и отвечал 403 на КАЖДУЮ отправку
    формы — за туннелем нельзя было ни войти, ни выйти, ни снять проверку.
    Счётчик неудачных входов (`remote.client_address`) видел один адрес на всех
    пришедших снаружи, то есть запирал вход всем сразу.

    Звено на петле — сама петля: добраться до неё может лишь тот, кто уже на
    машине. В сети контейнера доверия здесь нет никому: «любой сосед» (`*`) до
    12.10 отдавал выбор адреса и схемы каждому, кто дотянулся до порта. Кому
    верить в сети, решает `guard_forwarded` по названному адресу звена — так
    поднимается админка (`serve_options`); сервису обхода заголовки звена не
    нужны вовсе, и он получает просто «никому».
    """
    опции: dict[str, Any] = {}
    # Префикс уходит в `SCRIPT_NAME`, и от этого зависят ВСЕ ссылки страницы:
    # `url_for` собирает их вместе с ним. Без этого админка под общим входом
    # площадки открывалась бы по своему пути, а первая же кнопка уводила бы
    # человека в корень — то есть в чужой продукт, который там стоит.
    if settings.url_prefix:
        опции["url_prefix"] = settings.url_prefix
    if settings.trusted_proxies > 0 and _на_петле(settings.host):
        опции["trusted_proxy"] = settings.host
        опции["trusted_proxy_count"] = settings.trusted_proxies
        опции["trusted_proxy_headers"] = set(TRUSTED_HEADERS)
    return опции


def serve_options(settings: Settings) -> dict[str, Any]:
    """Опции `waitress` для приложения, обёрнутого `guard_forwarded`.

    Адрес звена назван — заголовки доезжают до обёртки сырыми: `waitress`
    сравнивает звено с одним адресом и подсети не понимает, поэтому решает
    обёртка, по адресу соединения. Не назван — как `_proxy_options`.
    """
    опции = _proxy_options(settings)
    if settings.trusted_proxies <= 0 or not settings.trusted_proxy_addrs:
        return опции
    return {
        **{ключ: значение for ключ, значение in опции.items() if not ключ.startswith("trusted_")},
        "clear_untrusted_proxy_headers": False,
    }


def untrusted_network(settings: Settings) -> bool:
    """Звенья обещаны, сервер слушает сеть, а адреса звена не названы.

    Тогда заголовкам не верим вовсе: счётчик перебора видит адрес прокси (один
    на всех — строже, чем нужно), а заслон происхождения — HTTP. Это осторожный
    конец развилки; точка входа говорит о нём в журнал при старте.
    """
    return (
        settings.trusted_proxies > 0
        and not settings.trusted_proxy_addrs
        and not _на_петле(settings.host)
    )


def peer_trusted(peer: str, addrs: tuple[str, ...]) -> bool:
    """Соединение пришло от своего звена: адрес совпал с названным или лежит в его подсети."""
    if ANY_PEER in addrs:
        return True
    try:
        адрес = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(адрес in ipaddress.ip_network(сеть, strict=False) for сеть in addrs)


def front_key_matches(expected: str, given: str) -> bool:
    """Ключ фронта совпал: сравнение за постоянное время, пустой присланный — нет."""
    return bool(given) and hmac.compare_digest(expected.encode(), given.encode())


def guard_forwarded(app: WsgiApp, settings: Settings) -> WsgiApp:
    """Обернуть приложение: заголовки звена — только от своего звена по адресу.

    Разбор заголовков — тот же, что у самого `waitress` (`proxy_headers_middleware`),
    чтобы правило «сколько звеньев своих» не жило в двух реализациях. Звена нет в
    настройке — обёртки нет: заголовки режет `waitress` (`_proxy_options`).
    """
    if settings.trusted_proxies <= 0 or not settings.trusted_proxy_addrs:
        return app
    addrs = settings.trusted_proxy_addrs
    front_key = settings.front_key
    mode = settings.front_key_mode
    if mode == FRONT_KEY_OFF:
        logger.warning(
            "%s=%s: origin не проверяет ключ фронта, заголовкам X-Forwarded-* верим любому "
            "соседу по подсети звена (docs/08-deploy.md, §8.9)",
            WEB_FRONT_KEY_MODE_VAR,
            mode,
        )
    # Единственное изменяемое место: момент последней записи в журнал (список из одного
    # числа, чтобы замыкание его меняло). Гонка потоков даёт лишнюю строку, не ошибку.
    last_logged = [float("-inf")]
    matched_logged = [False]

    доверяя = proxy_headers_middleware(
        app,
        trusted_proxy=ANY_PEER,
        trusted_proxy_count=settings.trusted_proxies,
        trusted_proxy_headers=set(TRUSTED_HEADERS),
        clear_untrusted=True,
    )
    не_доверяя = proxy_headers_middleware(app, trusted_proxy=None, clear_untrusted=True)

    def пропустить(запрос: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        given = str(запрос.pop(FRONT_KEY_ENVIRON, "") or "")  # приложению ключ ни к чему
        свой = peer_trusted(str(запрос.get("REMOTE_ADDR") or ""), addrs)
        if свой and mode != FRONT_KEY_OFF:
            if front_key_matches(front_key, given):
                if not matched_logged[0]:
                    matched_logged[0] = True
                    logger.info("Ключ фронта дошёл до origin и совпал (режим %s)", mode)
            else:
                now = time.monotonic()
                if now - last_logged[0] >= MISMATCH_LOG_INTERVAL_SECONDS:
                    last_logged[0] = now
                    logger.warning(
                        "Сосед %s из подсети звена пришёл без верного ключа фронта (режим %s%s)",
                        запрос.get("REMOTE_ADDR"),
                        mode,
                        ": X-Forwarded-* отброшены" if mode == FRONT_KEY_ENFORCE else ", верим",
                    )
                if mode == FRONT_KEY_ENFORCE:
                    свой = False
        if свой:
            return доверяя(запрос, start_response)
        return не_доверяя(запрос, start_response)

    return пропустить
