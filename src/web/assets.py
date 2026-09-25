"""Статика админки: отпечаток в адресе и долгий кеш.

Зачем. Без этого каждый переход между разделами переспрашивал у сервера три
таблицы стилей и шрифты (`Cache-Control: no-cache`), а стенд стоит за
Tailscale Funnel — около 0,3 с на запрос (замер 24.09.2026). Браузер не рисует
страницу, пока стили не подтверждены, и владелец видел это как моргание экрана
на каждом клике.

Как. К адресу каждого файла статики `url_for` дописывает `?v=<отпечаток
содержимого>`. Такой адрес меняется вместе с файлом, поэтому его можно кешировать
на год без перепроверки: поменяли CSS — поменялся адрес, старая копия просто
больше не запрашивается.

Шрифты адресуются из CSS относительным путём, без отпечатка. Им дан кеш на
неделю: файлы шрифтов меняются раз в смену дизайн-системы, а неделя устаревшего
начертания — мелочь по сравнению с перепроверкой на каждом клике.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Flask, request

VERSION_ARG = "v"
IMMUTABLE_MAX_AGE = 365 * 24 * 3600
FONT_MAX_AGE = 7 * 24 * 3600
FONTS_DIR = "fonts/"
DIGEST_LEN = 12


@lru_cache(maxsize=None)
def _digest(path: Path, mtime_ns: int) -> str:
    """Отпечаток содержимого. `mtime_ns` в ключе — чтобы правка файла на
    разработческом сервере сбрасывала запомненное без перезапуска."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LEN]


def fingerprint(static_dir: Path, filename: str) -> str | None:
    """Отпечаток файла статики или `None`, если файла нет."""
    path = (static_dir / filename).resolve()
    if not path.is_relative_to(static_dir.resolve()) or not path.is_file():
        return None
    return _digest(path, path.stat().st_mtime_ns)


def install(app: Flask) -> None:
    """Подключить отпечатки к `url_for('static', …)` и сроки кеша к ответам."""
    static_dir = Path(str(app.static_folder))

    @app.url_defaults
    def _add_fingerprint(endpoint: str, values: dict[str, Any]) -> None:
        filename = str(values.get("filename", ""))
        # Шрифт без отпечатка: CSS зовёт его голым путём, и адрес с `?v=`
        # был бы для браузера другим файлом — вторая загрузка того же шрифта.
        if endpoint != "static" or VERSION_ARG in values or filename.startswith(FONTS_DIR):
            return
        digest = fingerprint(static_dir, filename)
        if digest:
            values[VERSION_ARG] = digest

    def _max_age(filename: str | None) -> int | None:
        if request.args.get(VERSION_ARG):
            return IMMUTABLE_MAX_AGE
        if filename and filename.startswith(FONTS_DIR):
            return FONT_MAX_AGE
        return None

    app.get_send_file_max_age = _max_age  # type: ignore[method-assign]
