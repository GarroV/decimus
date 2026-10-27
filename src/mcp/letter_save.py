"""Инструмент «сохранить письмо партнёру в проверку» (D665) — тот же путь, что у сайта.

Ничего своего здесь нет: разметку чистит `src.report.letter_markup.for_saving` (её же
зовёт кнопка «Сохранить» на сайте), запись и историю версий держит
`src.db.letters.save_letter`. Здесь только граница инструмента: разбор аргументов,
отказы словами и автор из токена.

Право — действие матрицы `inspection.letter` (`policy.KIND_ACTIONS`), то есть те же
роли, что у сохранения на сайте; «только своё пространство» держит выбор проверки по
охвату пространства (`own_reach`): проверка чужого пространства отвечает так же, как
несуществующая. Непринятая (D199) и загруженная через MCP (D310) проверки письма не
получают — как на сайте.
"""

from __future__ import annotations

from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError
from ..domain.models import TEXT_LANGS
from .db_target import config_refusal
from .errors import ToolError
from .tools import _require_inspection_id

NOT_CONNECTED = (
    "Сохранение писем на этом стенде не настроено: нет подключения к базе. Это отказ "
    "настройки, а не отказ в сохранении"
)
NO_SUCH_INSPECTION = "no inspection found with that id in this space"
_WEB_ACTOR = "web:"


def _saved_by(actor: str) -> str:
    """Автор записи: логин человека, как у сайта; у служебного токена — его подпись."""
    return actor.removeprefix(_WEB_ACTOR)


def save_inspection_letter(
    *, tenant: str, actor: str, id: str, text: str, lang: str | None = None
) -> dict[str, object]:
    """Положить письмо новой версией в историю писем проверки своего пространства."""
    from ..db import letters as letters_store
    from ..db import queries
    from ..db.reach import own_reach
    from ..report import letter_markup

    ident = _require_inspection_id(id)
    if not isinstance(text, str) or not text.strip():
        raise ToolError("Письмо не сохранено: в нём нет текста")
    if lang is not None and lang not in TEXT_LANGS:
        raise ToolError(
            f"Письмо не сохранено: язык «{lang}» не поддерживается, "
            f"ожидается один из: {', '.join(sorted(TEXT_LANGS))}"
        )
    try:
        detail = queries.get_inspection(ident, reach=own_reach(tenant))
        if detail is None:
            raise ToolError(NO_SUCH_INSPECTION)
        if detail.inspection.is_uploaded:
            raise ToolError(
                "У загруженной через MCP проверки письма нет: оно собирается только по "
                "проверке, проведённой в боте"
            )
        if detail.inspection.on_review:
            raise ToolError(
                "Проверка ещё не принята (идёт вычитка): письмо партнёру сохраняется после приёмки"
            )
        язык = lang or detail.inspection.report_lang
        saved = letters_store.save_letter(
            ident,
            tenant=tenant,
            body=letter_markup.for_saving(text),
            lang=язык,
            saved_by=_saved_by(actor),
        )
        версия = letters_store.count_letters(ident, lang=язык)
    except DbConfigError as отказ:
        raise config_refusal(отказ, NOT_CONNECTED) from None
    except DbError as отказ:
        raise ToolError(str(отказ)) from None
    return {
        "tenant": tenant,
        "id": ident,
        "saved": True,
        "lang": saved.lang,
        "version": версия,
        "saved_by": saved.saved_by,
        "saved_at": saved.created_at.isoformat(),
        "note": "saved; the letter is now what the site shows in the inspection card",
    }
