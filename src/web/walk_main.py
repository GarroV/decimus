"""Точка входа сервиса мини-аппа обхода: `python -m src.web.walk_main`.

Тот же сервер (`waitress`) и те же настройки окружения, что у админки
(`WEB_HOST`, `WEB_PORT`, `WEB_LISTEN_NETWORK`, `WEB_URL_PREFIX`), — другой
набор адресов: только `/tg/walk*` (`walk_app.py`). Порт в `docker-compose.yml`
задаётся сервису своим (`WEB_WALK_PORT`), и админка передаёт ему запросы
обхода по `WEB_WALK_UPSTREAM`.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Тот же приём, что у админки (`src/web/__main__.py`): окружение читается до
# импорта настроек, уже заданные переменные не перекрываются.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from waitress import serve  # noqa: E402 -- окружение читается до импорта конфигурации

from .config import load_settings  # noqa: E402
from .errors import WebError  # noqa: E402
from .proxy import _proxy_options  # noqa: E402
from .walk_app import create_walk_app  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = load_settings()
        app = create_walk_app(settings)
    except (WebError, ValueError) as exc:
        # `ValueError` — отказ настроек обхода (`walk_auth.load_walk_settings`):
        # просмотр без подписи вместе с токеном, кривой круг тестеров.
        print(f"Сервис обхода не поднялся: {exc}", file=sys.stderr)
        return 2
    print(f"Мини-апп обхода: http://{settings.host}:{settings.port}{settings.url_prefix}/tg/walk")
    print(flush=True)
    logger.info("сервис обхода слушает http://%s:%s", settings.host, settings.port)
    serve(
        app,
        host=settings.host,
        port=settings.port,
        ident="decimus-walk",
        **_proxy_options(settings),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
