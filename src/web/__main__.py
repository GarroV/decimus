"""Точка входа веб-админки: `python -m src.web`.

Сервер — `waitress`: чистый Python, синхронный, без сборки и без второго
процесса-менеджера, тот же образ, что у бота и MCP. Встроенный сервер Flask
здесь не годится — он сам пишет, что не для работы, и на одном запросе за раз
реестр в сотню строк выглядел бы поломкой.

Отказ окружения печатается строкой, а не трассировкой: не задан тенант или
адрес не петля — человеку нужно имя переменной, а не стек.

`load_dotenv()` подставляет переменные из файла окружения до чтения настроек —
тем же приёмом и по той же причине, что в `src/bot/__main__.py` (issue #75) и
`src/mcp/__main__.py`. Без него `make web` поднимался без `DATABASE_URL`, и
реестр отвечал «База недоступна» при живой базе: человек шёл по доке и не мог
отличить незаведённую базу от непрочитанного окружения (issue #290).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Путь строится от файла, а не от текущего каталога, — как у бота и MCP.
# Отсутствие файла отказом не является: в контейнере переменные приходят из
# `docker compose`, и уже стоящие в окружении значения `load_dotenv` не трогает
# (`override=False` по умолчанию).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from waitress import serve  # noqa: E402 -- окружение читается до импорта конфигурации

from .app import create_app  # noqa: E402
from .config import (  # noqa: E402
    WEB_SECRET_KEY_VAR,
    WEB_TRUSTED_PROXY_ADDR_VAR,
    load_settings,
    require_signing_key,
)
from .errors import WebError  # noqa: E402
from .proxy import guard_forwarded, serve_options, untrusted_network  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = load_settings()
        require_signing_key(settings)
        app = create_app(settings)
    except WebError as exc:
        print(f"Веб-админка не поднялась: {exc}", file=sys.stderr)
        return 2
    # Адрес печатается строкой, а не только уходит в лог: человек запускает эту
    # команду, чтобы ОТКРЫТЬ админку, и первым делом ему нужен адрес, по
    # которому можно щёлкнуть. Собирается он из тех же настроек, с которыми
    # сервер сейчас встанет, — второй записи того же факта (в Makefile, в доке)
    # здесь быть не должно: она разъедется с портом при первой же правке.
    print(f"Веб-админка: http://{settings.host}:{settings.port}{settings.url_prefix}/inspections")
    print(f"Тенант: {settings.tenant} · язык интерфейса: {settings.ui_lang}")
    # Временный ключ подписи — законное состояние стенда, но молчать о нём
    # нельзя: человек, которого выбросило на форму входа после перезапуска,
    # иначе ищет поломку там, где её нет.
    if settings.secret_key_is_ephemeral:
        print(
            f"{WEB_SECRET_KEY_VAR} не задан — ключ подписи сделан на этот запуск. "
            f"Стенд работает, но перезапуск закроет все открытые сессии."
        )
    print(flush=True)
    logger.info(
        "веб-админка слушает http://%s:%s, тенант %s, язык интерфейса %s",
        settings.host,
        settings.port,
        settings.tenant,
        settings.ui_lang,
    )
    if untrusted_network(settings):
        # Звенья обещаны, а адрес звена не назван: заголовкам звена не верим
        # (F-038). Счётчик перебора — один на всех, формы за HTTPS-прокси
        # получат 403 заслона происхождения. Сказать это обязан запуск.
        logger.warning(
            "%s не задан: заголовкам X-Forwarded-* не верим ни от кого. Назовите адрес "
            "или подсеть своего прокси (docs/08-deploy.md, §8.1)",
            WEB_TRUSTED_PROXY_ADDR_VAR,
        )
    serve(
        guard_forwarded(app, settings),
        host=settings.host,
        port=settings.port,
        ident="decimus",
        **serve_options(settings),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
