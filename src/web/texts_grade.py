"""Тексты «почему такая буква» и «расшифровка оценки» на карточке проверки (D490).

Решение владельца 14.10.2026: «необходимо, почему за что снято. То есть нужна
расшифровка 100%». Причина буквы называется по условию сработавшего правила
(`data/scoring.json`, `grades.rules`), а пороги в текст приезжают параметрами
из того же файла — в строках цифр методики нет.

Сливаются в общий каталог (`texts.TEXTS`).
"""

from __future__ import annotations

GRADE_TEXTS: dict[str, dict[str, str]] = {
    # --- причина буквы: по условию сработавшего правила --------------------
    "grade.why.d3": {
        "ru": "{grade} — критическое нарушение (D3)",
        "en": "{grade} — critical violation (D3)",
    },
    "grade.why.d2_many": {
        "ru": "{grade} — нарушений D2 не меньше {n}",
        "en": "{grade} — {n} or more D2 violations",
    },
    "grade.why.pct_below": {
        "ru": "{grade} — балл ниже {pct}%",
        "en": "{grade} — score below {pct}%",
    },
    "grade.why.top": {
        "ru": "{grade} — {pct}% и выше без D2",
        "en": "{grade} — {pct}% or higher with no D2",
    },
    "grade.why.mid_d2": {
        "ru": "{grade} — есть нарушение D2",
        "en": "{grade} — there is a D2 violation",
    },
    "grade.why.mid_pct": {
        "ru": "{grade} — балл ниже {pct}%",
        "en": "{grade} — score below {pct}%",
    },
    "grade.why.mid_both": {
        "ru": "{grade} — есть нарушение D2 и балл ниже {pct}%",
        "en": "{grade} — there is a D2 violation and the score is below {pct}%",
    },
    "grade.why.other": {
        "ru": "{grade} — по правилу оценки из методики",
        "en": "{grade} — by the grading rule of the methodology",
    },
    "grade.why.fallback": {
        "ru": "{grade} — ни одно из правил выше не подошло",
        "en": "{grade} — none of the rules above applied",
    },
    # --- расшифровка: от старта до итога ----------------------------------
    "explain.title": {"ru": "Расшифровка", "en": "Breakdown"},
    "explain.start": {"ru": "Старт — {pct}%", "en": "Start — {pct}%"},
    "explain.level": {"ru": "{level} × {n} — −{loss}%", "en": "{level} × {n} — −{loss}%"},
    "explain.level_repeat": {
        "ru": "{level} повтор × {n} — −{loss}%",
        "en": "{level} repeat × {n} — −{loss}%",
    },
    "explain.d3_zone": {
        "ru": "D3 в зоне «{zone}» — зона обнулена, −{loss}%",
        "en": "D3 in “{zone}” — the zone is zeroed, −{loss}%",
    },
    "explain.d3_zone_many": {
        "ru": "D3 × {n} в зоне «{zone}» — зона обнулена, −{loss}%",
        "en": "D3 × {n} in “{zone}” — the zone is zeroed, −{loss}%",
    },
    "explain.skipped": {
        "ru": "Не снижали балл (зона уже обнулена D3): {what}",
        "en": "Did not lower the score (the zone is already zeroed by D3): {what}",
    },
    "explain.total": {"ru": "Итог — {pct}%", "en": "Total — {pct}%"},
    "explain.zones_only": {
        "ru": "Разбивка по классам недоступна. Вычтено по зонам:",
        "en": "The per-class split is unavailable. Deducted by zone:",
    },
    "explain.zone_loss": {"ru": "{zone} — −{loss}%", "en": "{zone} — −{loss}%"},
}
