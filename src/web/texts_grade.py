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
    # --- режим итогов по процессам (D714, прототип) --------------------------
    "explain.d3_process": {
        "ru": "D3 в процессе «{process}» — процесс обнулён, −{loss}%",
        "en": "D3 in “{process}” — the process is zeroed, −{loss}%",
    },
    "explain.d3_process_many": {
        "ru": "D3 × {n} в процессе «{process}» — процесс обнулён один раз, −{loss}%",
        "en": "D3 × {n} in “{process}” — the process is zeroed once, −{loss}%",
    },
    "explain.skipped_process": {
        "ru": "Не снижали балл (процесс уже обнулён D3): {what}",
        "en": "Did not lower the score (the process is already zeroed by D3): {what}",
    },
    "card.proc.title": {"ru": "Итог по процессам", "en": "Result by process"},
    "card.proc.total": {"ru": "вычтено {loss} п.п.", "en": "deducted {loss} pp"},
    "card.proc.ok": {"ru": "OK", "en": "OK"},
    "card.proc.zeroed": {"ru": "процесс обнулён", "en": "process zeroed"},
    "card.proc.found": {"ru": "найдено: {zones}", "en": "found in: {zones}"},
    "card.proc.absorbed": {
        "ru": "не вычитается — процесс обнулён",
        "en": "not deducted — the process is zeroed",
    },
    "card.proc.repeat": {"ru": "повтор", "en": "repeat"},
    "card.proc.records": {"ru": "записей: {n}", "en": "records: {n}"},
    "card.proc.clean": {"ru": "нарушений нет", "en": "no violations"},
    "card.proc.tip.label": {"ru": "Как считается итог", "en": "How the result is counted"},
    "card.proc.tip.walk": {
        "ru": "Обход идёт по зонам, итог сводится к процессам",
        "en": "The walk goes by zone, the result is summed up by process",
    },
    "card.proc.tip.once": {
        "ru": "Одно нарушение в нескольких зонах считается один раз, по старшему классу",
        "en": "One violation found in several zones counts once, at its highest class",
    },
    "card.proc.tip.d3": {
        "ru": "D3 обнуляет процесс один раз; прочие нарушения этого процесса уже не вычитаются",
        "en": "A D3 zeroes the process once; its other violations are no longer deducted",
    },
    "card.zones.addr.title": {"ru": "Зоны обхода", "en": "Walk zones"},
    "card.zones.addr.note": {
        "ru": "Зона — адрес находки. Потерь у зоны нет: итог считается по процессам",
        "en": "A zone is where a finding was made. Zones lose nothing: the result is by process",
    },
    "card.findings.by_zone": {"ru": "Записи по зонам", "en": "Records by zone"},
    "explain.zones_only": {
        "ru": "Разбивка по классам недоступна. Вычтено по зонам:",
        "en": "The per-class split is unavailable. Deducted by zone:",
    },
    "explain.zone_loss": {"ru": "{zone} — −{loss}%", "en": "{zone} — −{loss}%"},
}
