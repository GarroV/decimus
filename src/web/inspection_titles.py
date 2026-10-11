"""Формулировки пунктов методики по коду — для деталей проверки в API Swarm (D391).

Берётся издание, по которому прошла проверка (`inspections.checklist_version`),
а не действующее: формулировка пункта меняется от издания к изданию. Поиск
издания общий с карточкой проверки и письмом — `report.info_titles.titles`
(сверка отпечатка, а не имени каталога, T236), своего здесь нет.

Издания на машине нет, версия кривая, файл не читается — пустой словарь, а не
отказ ответа: детали проверки ценны и без подписей, код остаётся связью.
"""

from __future__ import annotations

from src.report import info_titles
from src.report.letters import sources as letter_sources


def item_titles(version: str) -> dict[str, tuple[str | None, str | None]]:
    """Код пункта (верхним регистром) → (формулировка RU, EN); пусто — не нашлось."""
    if not version.strip():
        return {}
    papers = letter_sources()
    ru, _ = info_titles.titles(version, lang="ru", papers=papers)
    en, _ = info_titles.titles(version, lang="en", papers=papers)
    return {code: (ru.get(code), en.get(code)) for code in ru.keys() | en.keys()}
