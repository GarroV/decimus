"""Ссылка загрузки кадров к черновику загрузки проверки: подписанный токен с жизнью в 2 часа.

Модель не может передать байты картинки аргументом инструмента, поэтому MCP
(`import_photo_upload_link`) выдаёт ссылку, а кадры идут на веб мимо модели: из
песочницы Claude командой `curl` или руками человека — страницей по той же
ссылке. Токен — подписанная (HMAC-SHA256, `itsdangerous`, как кука админки)
пара «проверка, пространство» со сроком; ни входа, ни куки у такого запроса нет,
поэтому доступ держится только на токене.

Токен не доказывает, что черновик ещё не принят: это проверяет приёмник по базе
на каждом запросе. Секрет — `WEB_SECRET_KEY`, один на веб и MCP (общий `.env`).
Модуль в `domain`, потому что `mcp` и `web` друг друга не импортируют.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from itsdangerous import BadSignature, URLSafeTimedSerializer

#: Соль отделяет эти токены от кук и состояний входа, подписанных тем же ключом.
SALT = "import-photo-upload"
#: Срок жизни ссылки — решение заказчика: два часа.
TTL_SEC = 2 * 3600
#: Короче — подобранный ключ даёт поддельную ссылку (как у куки, `web.config`).
MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class UploadGrant:
    """На что даёт право ссылка: черновик и пространство, которым он принадлежит."""

    inspection_id: str
    tenant: str


def _signer(secret: str) -> URLSafeTimedSerializer:
    if len(secret) < MIN_SECRET_LENGTH:
        raise ValueError("Ключ подписи короче допустимого")
    return URLSafeTimedSerializer(
        secret, salt=SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )


def issue(secret: str, *, inspection_id: str, tenant: str) -> str:
    """Подписать ссылку на черновик своего пространства."""
    return _signer(secret).dumps([inspection_id, tenant])


def verify(secret: str, token: str, *, max_age: int = TTL_SEC) -> UploadGrant | None:
    """Право по токену — или `None`: подделан, просрочен, не той формы. Причина не различается."""
    try:
        value = _signer(secret).loads(token, max_age=max_age)
    except BadSignature:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(part, str) and part for part in value)
    ):
        return None
    return UploadGrant(inspection_id=value[0], tenant=value[1])
