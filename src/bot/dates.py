"""Разбор даты из живой фразы аудитора — перенесён в домен (`src/domain/dates.py`).

Дату разбирают две поверхности — бот и загрузка через MCP, — а mcp бота не
импортирует. Здесь остался тонкий повтор имён, чтобы зовущий код бота и тесты о
переносе не знали.
"""

from __future__ import annotations

from ..domain.dates import DATE_FORMAT, parse_date

__all__ = ["DATE_FORMAT", "parse_date"]
