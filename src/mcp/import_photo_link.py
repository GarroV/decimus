"""`import_photo_upload_link`: ссылка, по которой кадры к черновику идут мимо модели.

Модель не может передать байты картинки аргументом инструмента (`import_add_photo`
с base64 на практике не работает), поэтому инструмент выдаёт подписанную ссылку на
веб (`src/web/photo_upload.py`): из песочницы Claude кадры уходят командой `curl`,
а если у песочницы закрыта сеть — человек открывает ту же ссылку и перетаскивает
фото на страницу. Право то же, что у `import_add_photo`: вид `import`, свой черновик.

Подпись — `WEB_SECRET_KEY` (общий `.env` веба и MCP): ключ, выдуманный на запуск,
веб не узнает, поэтому без заданного ключа инструмент отказывает, а не выдаёт
ссылку, которая не откроется.
"""

from __future__ import annotations

import os

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


def _secret() -> str:
    key = (os.environ.get(SECRET_VAR) or "").strip()
    if len(key) < photo_upload_link.MIN_SECRET_LENGTH:
        raise ToolError(
            "Photo upload links are not configured on this stand (the web signing key "
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
            "Photo upload links are not configured on this stand (the public web address "
            "is not set). Ask the administrator; photos can be skipped for now"
        )
    return base


def import_photo_upload_link(
    *, tenant: str, store: Store, actor: str, inspection_id: str
) -> dict[str, object]:
    """Выдать ссылку загрузки кадров к черновику своего пространства."""
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
        "url": url,
        "valid_until": "the draft is accepted (no time limit)",
        "findings_total": len(detail.findings),
        "command": f'curl -sS -F n=<finding number> -F file=@{UPLOADS_DIR}<file name> "{url}"',
        "status": (
            "Run `command` in the sandbox once per photo (several photos of one finding: "
            "several -F file=@... in one command). The answer is JSON: attached / refused "
            "per file. If the command cannot connect (no network), give the person the "
            "url: they open it and drop the photos on the right finding themselves. "
            "The link works only while the draft is not accepted and only for this draft"
        ),
    }
