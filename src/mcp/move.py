"""Инструмент «исправить дату или пиццерию проверки» (D195) — та же функция, что у веба.

Ничего своего здесь нет: дату и точку правит `src.db.move.move_inspection`, она
же держит причину, отказ на отклонённую, чужую пиццерию и историю. Здесь только
граница инструмента: разбор даты, поиск точки по справочнику и отказы словами.
Право — действие матрицы `inspection.move` (`policy.KIND_ACTIONS`); загруженный
черновик до принятия правит и `import_edit_inspection`.
"""

from __future__ import annotations

from datetime import date as _date

from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError, MoveError
from .db_target import config_refusal
from .errors import ToolError
from .tools import _parse_date, _require_inspection_id

NOT_CONNECTED = (
    "Исправление проверок на этом стенде не настроено: не задана переменная окружения "
    "DATABASE_RETRACTION_URL. Это отказ настройки, а не отказ в исправлении"
)


def move_inspection(
    *,
    tenant: str,
    actor: str,
    inspection_id: str,
    reason: str,
    date: str | None = None,
    unit: str | None = None,
) -> dict[str, object]:
    """Перенести проверку по дате и/или пиццерии с причиной; оценка не меняется."""
    from ..db import move
    from ..db.directory import resolve_unit_id
    from ..db.reading import reading
    from ..domain.tenants import HQ_TENANT

    ident = _require_inspection_id(inspection_id)
    день = _parse_date(date, field="date") if date is not None else None
    if день is not None and день > _date.today():
        raise ToolError(f"Дата {день.isoformat()} в будущем: проверка не может быть позже сегодня")
    if день is None and unit is None:
        raise ToolError("Нечего менять: назовите date или unit")
    try:
        точка: str | None = None
        if unit is not None:
            with reading("справочник пиццерий") as conn:
                точка = resolve_unit_id(conn, unit, tenant=HQ_TENANT)
            if точка is None:
                raise ToolError(
                    f"Пиццерии «{unit}» нет в справочнике (или имя подходит нескольким). "
                    f"Назовите её так, как она записана в справочнике"
                )
        перенесено = move.move_inspection(
            ident, tenant=tenant, new_date=день, new_unit_id=точка, reason=reason, actor=actor
        )
    except DbConfigError as отказ:
        raise config_refusal(отказ, NOT_CONNECTED) from None
    except (MoveError, DbError) as отказ:
        raise ToolError(str(отказ)) from None
    return {
        "id": ident,
        "moved": перенесено,
        "note": "moved; history recorded" if перенесено else "nothing to change, already so",
    }
