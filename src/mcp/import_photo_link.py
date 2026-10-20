"""`import_upload_photos`: команда для песочницы, по которой кадры к черновику идут мимо модели.

Модель не может передать байты картинки аргументом инструмента (`import_add_photo`
с base64 на практике не работает), поэтому инструмент выдаёт песочнице Claude команду
`curl` с подписанным адресом веба (`src/web/photo_upload.py`). Адрес человеку не
показывается никогда (решение владельца 20.10.2026: действия с отчётом — только через
MCP, «никаких левых ссылок»): нет сети в песочнице — человеку одна фраза про настройку
Claude. Право то же, что у `import_add_photo`: вид `import`, свой черновик.

Подпись — `WEB_SECRET_KEY` (общий `.env` веба и MCP): ключ, выдуманный на запуск,
веб не узнает, поэтому без заданного ключа инструмент отказывает, а не выдаёт
ссылку, которая не откроется.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from ..domain import photo_upload_link
from ..domain.public_urls import ADMIN_PUBLIC_URL_VAR, parse_public_url
from .checklist_layout import Store
from .errors import ToolError
from .imports import _only_import
from .tools import _require_inspection_id

SECRET_VAR = "WEB_SECRET_KEY"  # noqa: S105 — это ИМЯ переменной, а не значение
PATH = "/photo-upload/"
#: Подпись команды для песочницы: Claude подставляет номер находки и имя файла.
UPLOADS_DIR = "/mnt/user-data/uploads/"
#: Что сказать человеку, если песочница не достучалась до веба (адрес не называем).
NO_NETWORK_SAY = (
    "Фото не загрузились: в настройках Claude для выполнения кода не открыт доступ к "
    "сервису Decimus (Settings → Capabilities → Code execution → разрешённые домены: "
    "{domain}). Записи сохранены, фото можно догрузить после настройки"
)


def _secret() -> str:
    key = (os.environ.get(SECRET_VAR) or "").strip()
    if len(key) < photo_upload_link.MIN_SECRET_LENGTH:
        raise ToolError(
            "Photo upload is not configured on this stand (the web signing key "
            "is not set). Ask the administrator; photos can be skipped for now"
        )
    return key


def _base() -> str:
    try:
        base = parse_public_url(
            os.environ.get(ADMIN_PUBLIC_URL_VAR) or "", var=ADMIN_PUBLIC_URL_VAR
        )
    except ValueError:
        base = None
    if not base:
        raise ToolError(
            "Photo upload is not configured on this stand (the public web address "
            "is not set). Ask the administrator; photos can be skipped for now"
        )
    return base


def import_upload_photos(
    *, tenant: str, store: Store, actor: str, inspection_id: str
) -> dict[str, object]:
    """Выдать песочнице команду загрузки кадров к черновику своего пространства."""
    del store, actor
    ident = _require_inspection_id(inspection_id)
    detail, _ = _only_import(ident, tenant=tenant)
    if not detail.inspection.on_review:
        raise ToolError(f"Проверка {ident} уже подтверждена — кадры к ней не прикладываются")
    секрет = _secret()
    база = _base()
    token = photo_upload_link.issue(секрет, inspection_id=ident, tenant=tenant)
    url = f"{база}{PATH}{token}"
    return {
        "id": ident,
        "findings_total": len(detail.findings),
        # Поле для локального моста (`tools/mcp_bridge.sh`, `local_attach_photos`): он шлёт
        # кадры сам. Модели и человеку не показывается — так же, как адрес в `command`.
        "upload_target": url,
        "command": f'curl -sS -F n=<finding number> -F file=@{UPLOADS_DIR}<file name> "{url}"',
        "status": (
            "Run `command` in the sandbox once per photo (several photos of one finding: "
            "several -F file=@... in one command). The answer is JSON: attached / refused "
            "per file. NEVER show the address in `command` to the person. If the command "
            "cannot connect, tell the person in one sentence (in their language): "
            f"«{NO_NETWORK_SAY.format(domain=urlparse(база).hostname)}» and give no "
            "address. `upload_target` is a machine field for the local bridge: never show or "
            "repeat it. Works only while the draft is not accepted"
        ),
    }
