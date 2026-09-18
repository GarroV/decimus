"""Точка входа веб-админки: `python -m src.web`.

Сервер — `waitress`: чистый Python, синхронный, без сборки и без второго
процесса-менеджера, тот же образ, что у бота и MCP. Встроенный сервер Flask
здесь не годится — он сам пишет, что не для работы, и на одном запросе за раз
реестр в сотню строк выглядел бы поломкой.

Отказ окружения печатается строкой, а не трассировкой: не задан тенант или
адрес не петля — человеку нужно имя переменной, а не стек.
"""

from __future__ import annotations

import logging
import sys

from waitress import serve

from .app import create_app
from .config import load_settings
from .errors import WebError

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = load_settings()
        app = create_app(settings)
    except WebError as exc:
        print(f"Веб-админка не поднялась: {exc}", file=sys.stderr)
        return 2
    logger.info(
        "веб-админка слушает http://%s:%s, тенант %s, язык интерфейса %s",
        settings.host,
        settings.port,
        settings.tenant,
        settings.ui_lang,
    )
    serve(app, host=settings.host, port=settings.port, ident="decimus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
