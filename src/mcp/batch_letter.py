"""Общее письмо партнёру по нескольким проверкам одной страны для протокола MCP (D739).

Сборка и правило выбора живут ярусом ниже (`src/report/batch_letter.py`) — их зовут и сайт,
и этот протокол, и вторая копия правила разошлась бы молча. Здесь — граница инструмента:
разбор аргументов, перевод отказа правила в `ToolError`, автор записи из токена.

Права те же, что у одиночного письма: охват — только своё пространство (`own_reach`),
запись — действие матрицы `inspection.letter` (`policy.KIND_ACTIONS`). Правило выбора
(одна страна, не меньше двух, между крайними датами не больше 7 дней, только принятые)
проверяется и при сборке, и при сохранении: инструмент записи его не обходит.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError
from ..db.models import InspectionDetail
from ..domain.models import TEXT_LANGS
from ..report.batch_letter import BatchLetterError, check_selection
from ..report.batch_letter import build as _build
from ..report.letters import LetterError
from .db_target import config_refusal
from .errors import ToolError
from .letters import sources
from .tools import HISTORY_NOT_CONNECTED, _require_inspection_id

NOT_CONNECTED = (
    "Сохранение писем на этом стенде не настроено: нет подключения к базе. Это отказ "
    "настройки, а не отказ в сохранении"
)
NO_SUCH_INSPECTION = "no inspection found with that id in this space"
_WEB_ACTOR = "web:"


def _ids(raw: Any) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        raise ToolError("Нужен список идентификаторов проверок: 'ids' — массив строк-UUID")
    return [_require_inspection_id(str(x)) for x in raw]


def _details(ids: list[str], tenant: str) -> list[InspectionDetail]:
    from ..db.queries import get_inspection
    from ..db.reach import own_reach

    found: list[InspectionDetail] = []
    for ident in ids:
        detail = get_inspection(ident, reach=own_reach(tenant))
        if detail is None:
            raise ToolError(f"{NO_SUCH_INSPECTION}: {ident}")
        found.append(detail)
    return found


def batch_letter(
    *,
    tenant: str,
    ids: Any,
    lang: str | None = None,
    template: int | None = None,
    fresh: bool = False,
) -> dict[str, object]:
    """Общее письмо по списку проверок: сохранённое людьми или заготовка из записанного."""
    identifiers = _ids(ids)
    try:
        details = _details(identifiers, tenant)
        ordered = check_selection(details, tenant=tenant)
        if not fresh:
            from ..db import batch_letters as store

            saved = store.latest_for_set(identifiers, tenant=tenant, lang=lang)
            if saved is not None:
                return {
                    "tenant": tenant,
                    "source": "saved",
                    "letter": saved.body,
                    "lang": saved.lang,
                    "version": store.count_for_set(identifiers, tenant=tenant, lang=saved.lang),
                    "saved_by": saved.saved_by,
                    "saved_at": saved.created_at.isoformat(),
                    "inspection_ids": list(saved.inspection_ids),
                    "units": [d.inspection.unit_name for d in ordered],
                    "status": (
                        "the saved joint letter, as people last approved it: show it, do not "
                        "rebuild it. Plain lines plus <b> <i> <s> <a href> markup; & < > are "
                        "escaped. Pass fresh=true for a new template instead"
                    ),
                }
        built = _build(details, tenant=tenant, papers=sources(), lang=lang, template=template)
    except BatchLetterError as отказ:
        raise ToolError(str(отказ)) from None
    except LetterError as отказ:
        raise ToolError(str(отказ)) from None
    except DbConfigError as отказ:
        raise config_refusal(отказ, HISTORY_NOT_CONNECTED) from None
    except DbError as отказ:
        raise ToolError(str(отказ)) from None
    return {"tenant": tenant, "source": "template", **built}


def save_batch_letter(
    *, tenant: str, actor: str, ids: Any, text: str, lang: str | None = None
) -> dict[str, object]:
    """Положить общее письмо новой версией; правило выбора проверяется заново."""
    from ..db import batch_letters as store
    from ..report import letter_markup

    identifiers = _ids(ids)
    if not isinstance(text, str) or not text.strip():
        raise ToolError("Письмо не сохранено: в нём нет текста")
    if lang is not None and lang not in TEXT_LANGS:
        raise ToolError(
            f"Письмо не сохранено: язык «{lang}» не поддерживается, "
            f"ожидается один из: {', '.join(sorted(TEXT_LANGS))}"
        )
    try:
        details = _details(identifiers, tenant)
        ordered = check_selection(details, tenant=tenant)
        язык = lang or ordered[-1].inspection.report_lang
        saved = store.save_batch_letter(
            identifiers,
            tenant=tenant,
            country=ordered[0].inspection.unit_country,
            body=letter_markup.for_saving(text),
            lang=язык,
            saved_by=actor.removeprefix(_WEB_ACTOR),
        )
        версия = store.count_for_set(identifiers, tenant=tenant, lang=язык)
    except BatchLetterError as отказ:
        raise ToolError(str(отказ)) from None
    except DbConfigError as отказ:
        raise config_refusal(отказ, NOT_CONNECTED) from None
    except DbError as отказ:
        raise ToolError(str(отказ)) from None
    return {
        "tenant": tenant,
        "saved": True,
        "id": saved.id,
        "lang": saved.lang,
        "version": версия,
        "inspection_ids": list(saved.inspection_ids),
        "saved_by": saved.saved_by,
        "saved_at": saved.created_at.isoformat(),
        "note": "saved; each inspection card on the site now shows 'included in the joint letter'",
    }
