"""Столбцы счётчиков обучения (миграция 0085) — общие для записи и чтения."""

from __future__ import annotations

from src.domain.training_metrics import COLUMNS

#: «Людей» по курсу не храним: по курсу это и есть назначения (0085).
COURSE_COLUMNS = tuple(c for c in COLUMNS if not c.startswith("people_"))
