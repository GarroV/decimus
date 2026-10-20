"""Пункт чек-листа для человека на экранах веба: «Порядок 13», а не `CLN13` (20.10.2026).

Правило метки одно на все поверхности — `domain.item_label`; здесь только то,
откуда веб берёт тексты пунктов:

* карточка проверки — методика ТОЙ версии, по которой её считали (`pinned`):
  название процесса и формулировка меняются от издания к изданию;
* экраны, сводящие проверки разных изданий («Главная», «Страны», карточка
  пиццерии), — ДЕЙСТВУЮЩАЯ методика пространства (`current`), как и
  подписи-формулировки там (`app._item_titles`): метка здесь подпись к коду,
  а не текст той проверки. Код остаётся связью — в адресах и формах.

Методика не настроена или не прочиталась — пустые тексты, и метка честно остаётся
кодом: отказ здесь не повод не показать экран.
"""

from __future__ import annotations

from collections.abc import Callable

from flask import g

from src.db.models import InspectionDetail
from src.domain import item_label
from src.report import info_titles
from src.report.letters import sources as letter_sources

from . import auth
from . import methodology as method
from .errors import MethodologyRefused

_CACHE_KEY = "_current_item_texts"


def current_texts() -> dict[str, item_label.ItemTexts]:
    """Тексты пунктов действующей методики пространства; на запрос читаются один раз."""
    cached = g.get(_CACHE_KEY)
    if cached is not None:
        return dict(cached)
    texts: dict[str, item_label.ItemTexts] = {}
    state = method.load_store()
    if state.store is not None:
        try:
            состав = method.load_composition(state.store, tenant=auth.current_tenant())
            texts = item_label.from_csv(
                {k: None if v is None else str(v) for k, v in row.items()} for row in состав.items
            )
        except MethodologyRefused:
            texts = {}
    setattr(g, _CACHE_KEY, texts)
    return dict(texts)


def current_label(code: str, lang: str) -> str:
    """Метка пункта по действующей методике (экраны сети)."""
    return item_label.label(code, current_texts(), lang)


def current_full(code: str, lang: str) -> str:
    """Метка с формулировкой по действующей методике."""
    return item_label.full(code, current_texts(), lang)


def pinned(version: str, lang: str) -> tuple[Callable[[str], str], Callable[[str], str]]:
    """Метка и «метка — формулировка» по методике этой версии: две функции от кода."""
    texts, _ = info_titles.item_texts(version, papers=letter_sources())
    return (
        lambda code: item_label.label(code, texts, lang),
        lambda code: item_label.full(code, texts, lang),
    )


def for_detail(detail: InspectionDetail, lang: str) -> Callable[[str], str]:
    """Метка пункта для карточки проверки — по версии этой проверки."""
    label, _ = pinned(detail.inspection.checklist_version, lang)
    return label
