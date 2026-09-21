"""Письмо партнёру по записанной проверке — для протокола MCP.

Сама пересборка живёт ярусом ниже (`src/report/letters.py`): её зовут ДВЕ
поверхности — этот протокол и веб-админка, — а `src.mcp` и `src.web` по
контракту слоёв пиры и друг друга не импортируют. Копия на 700 строк у каждого
разошлась бы с первой правкой, и увидел бы это партнёр: письмо на его столе
собрано одним из двух экземпляров правил.

Здесь остаётся ровно перевод отказа в словарь этого блока — точка входа ловит
`ToolError` одним `except` — и имена общего модуля под прежними адресами,
чтобы зовущие не переучивались на новый путь.
"""

from __future__ import annotations

from typing import Any

from ..db.models import InspectionDetail
from ..report.letters import BLANK_TEXT_FIELD as BLANK_TEXT_FIELD
from ..report.letters import COVER_FIELDS as COVER_FIELDS
from ..report.letters import FINDING_TEXT_FIELD as FINDING_TEXT_FIELD
from ..report.letters import FROM_LIVE as FROM_LIVE
from ..report.letters import FROM_SHELF as FROM_SHELF
from ..report.letters import FROM_SNAPSHOT as FROM_SNAPSHOT
from ..report.letters import PLAN_DUE_FIELD as PLAN_DUE_FIELD
from ..report.letters import REPORT_SCRIPT as REPORT_SCRIPT
from ..report.letters import VERSIONS_DIR as VERSIONS_DIR
from ..report.letters import LetterError
from ..report.letters import Papers as Papers
from ..report.letters import _run as _run
from ..report.letters import _verify as _verify
from ..report.letters import build as _build
from ..report.letters import check_version as _check_version
from ..report.letters import pinned as _pinned
from ..report.letters import sources as sources
from ..report.letters import state_json as state_json
from ..report.letters import version_of as version_of
from .errors import ToolError


def check_version(version: str) -> str:
    """Имя версии как кусок пути — или отказ протокола.

    Само правило общее (`src/report/letters.py`), здесь только словарь отказов
    этого блока: клиенту протокола уходит `ToolError`, а не тип чужого слоя.
    """
    try:
        return _check_version(version)
    except LetterError as отказ:
        raise ToolError(str(отказ)) from None


def pinned(version: str, papers: Papers) -> Any:
    """Снимок методики, которым помечена проверка, — или отказ протокола.

    Перевод отказа нужен здесь так же, как у `build`: `pinned` зовёт не только
    письмо, но и информационная часть карточки (`info_part`), и до переноса
    оба места ловили `ToolError` одним `except`.
    """
    try:
        return _pinned(version, papers)
    except LetterError as отказ:
        raise ToolError(str(отказ)) from None


def build(detail: InspectionDetail, *, lang: str | None, papers: Papers) -> dict[str, Any]:
    """Собрать письмо — или отказать словами, понятными клиенту протокола."""
    try:
        return _build(detail, lang=lang, papers=papers)
    except LetterError as отказ:
        raise ToolError(str(отказ)) from None
