"""Идентификаторы людей и пространств в журнале — меткой, а не как есть (F-015).

Номер Telegram, номер чата, код пространства, логин учётки — личные или
служебные идентификаторы. В журнале контейнера они лежат без срока хранения и
видны каждому, кто читает журнал, поэтому в строки INFO и WARNING попадает не
сам идентификатор, а его метка `id:xxxxxxxx`.

Метка — ключевой отпечаток (HMAC-SHA256), а не простой: номеров Telegram мало,
и отпечаток без ключа перебором превращается обратно в номер. Ключ —
переменная `LOG_ID_SALT`. Задана — метка одна и та же у бота, веба и обхода и
переживает перезапуск: по известному номеру её можно вычислить и найти
человека в журнале (`python -m src.domain.log_ids <номер>`). Не задана — ключ
случайный на процесс: строки одного процесса между собой связываются, наружу
метка не обращается вовсе.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import os
import secrets
import sys

SALT_VAR = "LOG_ID_SALT"

#: Длина метки в шестнадцатеричных знаках: различает сотни людей без
#: совпадений и не тянет строку журнала.
TAG_LEN = 8


@functools.cache
def _key() -> bytes:
    # Читается при первой метке, а не при импорте: `.env` грузится позже
    # импорта модулей, и ключ из него иначе не успел бы прийти.
    return (os.environ.get(SALT_VAR) or "").encode() or secrets.token_bytes(32)


def log_id(value: object) -> str:
    """Метка идентификатора для журнала. `None` — так и пишется: «нет» не личное."""
    if value is None:
        return "id:-"
    digest = hmac.new(_key(), str(value).encode(), hashlib.sha256).hexdigest()
    return f"id:{digest[:TAG_LEN]}"


if __name__ == "__main__":  # pragma: no cover — справка для дежурного
    for arg in sys.argv[1:]:
        print(arg, log_id(arg))
