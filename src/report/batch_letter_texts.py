"""Тексты общего письма по нескольким проверкам (D739): словарь «ключ → язык → текст».

Строк внутри сборки нет — только `say(key, lang, **значения)`. Третий язык добавляется
записями сюда. Слова из одиночного письма (счёт нарушений, находки по зонам, обратная
связь аудитора, «немедленно») сюда не копируются: они приезжают готовыми от движка
(`engine/report.py letter-parts`), и вторая копия разошлась бы с первой молча.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.models import REPORT_LANGS
from .errors import ReportError

TEXTS: Mapping[str, Mapping[str, str]] = {
    "subject": {
        "ru": "Тема: Результаты проверок {units} за {period}",
        "en": "Subject: Inspection results for {units} for {period}",
        "tr": "Konu: {units} denetim sonuçları, {period}",
    },
    "hello": {
        "ru": "Здравствуйте!",
        "en": "Hello,",
        "tr": "Merhaba,",
    },
    "lead.day": {
        "ru": "{date}",
        "en": "On {date}",
        "tr": "{date} tarihinde",
    },
    "lead.range": {
        "ru": "С {start} по {end}",
        "en": "Between {start} and {end}",
        "tr": "{start} ile {end} arasında",
    },
    "intro": {
        "ru": "{lead} мы провели выездные проверки {n} пиццерий: {units}.",
        "en": "{lead} we carried out on-site inspections of {n} pizzerias: {units}.",
        "tr": "{lead} {n} pizzacıda yerinde denetim gerçekleştirdik: {units}.",
    },
    "auditor.one": {
        "ru": "Проверяющий: {names}",
        "en": "Auditor: {names}",
        "tr": "Denetçi: {names}",
    },
    "auditor.many": {
        "ru": "Проверяющие: {names}",
        "en": "Auditors: {names}",
        "tr": "Denetçiler: {names}",
    },
    "results.title": {
        "ru": "Результаты проверок:",
        "en": "Inspection results:",
        "tr": "Denetim sonuçları:",
    },
    "table.head": {
        "ru": "Пиццерия | Дата | Оценка | Буква | D1 | D2 | D3",
        "en": "Pizzeria | Date | Score | Grade | D1 | D2 | D3",
        "tr": "Pizzacı | Tarih | Puan | Not | D1 | D2 | D3",
    },
    "summary.ok": {
        "ru": "Все пиццерии соответствуют стандарту. Значительных (D2) и критических (D3) "
        "нарушений нет.",
        "en": "All pizzerias meet the standard. There are no significant (D2) or critical (D3) "
        "violations.",
        "tr": "Tüm pizzacılar standardı karşılamaktadır. "
        "Önemli (D2) veya kritik (D3) uygunsuzluk yoktur.",
    },
    "summary.failing": {
        "ru": "{k} из {n} пиццерий — оценка {grades}.",
        "en": "{k} of {n} pizzerias scored grade {grades}.",
        "tr": "{n} pizzacıdan {k} tanesinin notu {grades}.",
    },
    "summary.below": {
        "ru": "{k} из {n} пиццерий ниже стандарта (оценка C).",
        "en": "{k} of {n} pizzerias are below the standard (grade C).",
        "tr": "{n} pizzacıdan {k} tanesi standardın altındadır (not C).",
    },
    "summary.totals": {
        "ru": "Всего зафиксировано: критических (D3) — {d3}, значительных (D2) — {d2}.",
        "en": "Recorded in total: critical (D3) — {d3}, significant (D2) — {d2}.",
        "tr": "Toplam kaydedilen: kritik (D3) — {d3}, önemli (D2) — {d2}.",
    },
    "attached": {
        "ru": "Подробный отчёт по каждой пиццерии — с фотографиями и разбивкой по зонам — "
        "во вложении.",
        "en": "The detailed report for each pizzeria, with photographs and the breakdown by "
        "zone, is attached.",
        "tr": "Her pizzacı için fotoğraflı ve bölgelere göre dağılımı içeren ayrıntılı rapor "
        "ekte yer almaktadır.",
    },
    "findings.title": {
        "ru": "Основные замечания по пиццериям:",
        "en": "Main findings by pizzeria:",
        "tr": "Pizzacılara göre başlıca bulgular:",
    },
    "unit.head": {
        "ru": "{unit} — {pct}%, оценка {grade}",
        "en": "{unit} — {pct}%, grade {grade}",
        "tr": "{unit} — %{pct}, not {grade}",
    },
    "unit.critical": {
        "ru": " — критично",
        "en": " — critical",
        "tr": " — kritik",
    },
    "unit.none": {
        "ru": "Нарушений не зафиксировано.",
        "en": "No violations recorded.",
        "tr": "Uygunsuzluk tespit edilmedi.",
    },
    "todo.title": {
        "ru": "Что необходимо сделать по итогам проверок:",
        "en": "What needs to be done:",
        "tr": "Denetimler sonucunda yapılması gerekenler:",
    },
    "todo.d3": {
        "ru": "Критические нарушения (D3) — {when}:",
        "en": "Critical violations (D3) — {when}:",
        "tr": "Kritik uygunsuzluklar (D3) — {when}:",
    },
    "todo.d2": {
        "ru": "Значительные нарушения (D2) — до {due}:",
        "en": "Significant violations (D2) — by {due}:",
        "tr": "Önemli uygunsuzluklar (D2) — son tarih {due}:",
    },
    "todo.line": {
        "ru": "• {unit}: {text} — {zone}",
        "en": "• {unit}: {text} — {zone}",
        "tr": "• {unit}: {text} — {zone}",
    },
    "todo.units": {
        "ru": "По пиццериям:",
        "en": "By pizzeria:",
        "tr": "Pizzacılara göre:",
    },
    "todo.unit_line": {
        "ru": "• {unit}: критических D3 — {d3}, значительных D2 — {d2}, незначительных D1 — {d1}",
        "en": "• {unit}: critical D3 — {d3}, significant D2 — {d2}, minor D1 — {d1}",
        "tr": "• {unit}: kritik D3 — {d3}, önemli D2 — {d2}, küçük D1 — {d1}",
    },
    "terms.plan": {
        "ru": "Просим подготовить план устранения выявленных отклонений.",
        "en": "Please prepare an action plan to address the identified deviations.",
        "tr": "Tespit edilen uygunsuzlukların giderilmesi için bir eylem planı hazırlamanızı "
        "rica ederiz.",
    },
    "terms.due": {
        "ru": "Просим устранить все нарушения до {due}.",
        "en": "Please eliminate all violations by {due}.",
        "tr": "Tüm uygunsuzlukların {due} tarihine kadar giderilmesini rica ederiz.",
    },
    "terms.none": {
        "ru": "План устранения нарушений не требуется.",
        "en": "No action plan to address violations is required.",
        "tr": "Uygunsuzlukların giderilmesi için eylem planı gerekmemektedir.",
    },
    "thanks": {
        "ru": "Спасибо за работу. Готовы обсудить любой пункт отчётов.",
        "en": "Thank you for your work. We are happy to walk through any item in the reports.",
        "tr": "Çalışmanız için teşekkür ederiz. Raporlardaki her maddeyi sizinle "
        "değerlendirmeye hazırız.",
    },
}


def say(key: str, lang: str, **values: object) -> str:
    """Текст по ключу на языке письма; незнакомый язык или ключ — отказ, не подмена русским."""
    if lang not in REPORT_LANGS:
        raise ReportError(
            f"Язык общего письма «{lang}» не заведён. Доступны: {', '.join(REPORT_LANGS)}"
        )
    return TEXTS[key][lang].format(**values)
