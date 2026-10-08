"""Загрузка рейтингов через Claude (D320): MCP-инструмент `import_ratings`.

Тот же импортёр, что у веба (`src.ratings.importer`): одна транзакция на файл,
повтор — `duplicate`. Открыт только токену пространства УК — заслон стоит на
входе (`rpc._call_tool`, вид `KIND_RATINGS`) и ещё раз здесь. Свой вход в Dodo
IS сервер не хранит: снимок Claude собирает в браузере сотрудника
(`docs/15-ratings.md`).
"""

from __future__ import annotations

from src.db.errors import RatingsError
from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.ratings.importer import CHANNEL_MCP, import_file
from src.ratings.model import FORMATS, RatingsFormatError

from .errors import ToolError

OUTCOME_DUPLICATE = "duplicate"


def import_ratings(
    *, tenant: str, kind: str, content: str, file_name: str | None = None
) -> dict[str, object]:
    код = canonical_tenant(tenant)
    if код != HQ_TENANT:
        raise ToolError("Загружать рейтинги может только токен пространства УК")
    if kind not in FORMATS:
        raise ToolError(f"Вид «{kind}» не знаком. Есть: {', '.join(FORMATS)}")
    try:
        итог = import_file(
            content.encode("utf-8"),
            kind=kind,
            channel=CHANNEL_MCP,
            actor=f"mcp:{код}",
            file_name=file_name,
        )
    except RatingsFormatError as exc:
        raise ToolError(f"Файл не принят ({exc.code}): {exc}") from exc
    except RatingsError as exc:
        raise ToolError(str(exc)) from exc
    loaded_at = итог.loaded_at.isoformat() if итог.loaded_at else None
    ответ: dict[str, object] = {
        "import_id": итог.import_id,
        "format": итог.format,
        "outcome": итог.outcome,
        "accepted": итог.accepted,
        "updated": итог.updated,
        "skipped": итог.skipped,
        "unmatched": итог.unmatched,
        "issues": итог.issues,
        "label": итог.label,
        "chunk_index": итог.chunk_index,
        "chunk_of": итог.chunk_of,
        "loaded_at": loaded_at,
    }
    if итог.outcome == OUTCOME_DUPLICATE:
        ответ["message"] = f"Этот файл уже загружен {loaded_at or 'ранее'}; ничего не изменилось"
    return ответ
