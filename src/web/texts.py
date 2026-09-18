"""Тексты веб-админки: каталог по ключам, язык — параметр.

Та же форма, что у бота (`src/bot/texts.py`): в шаблонах и обработчиках строк
нет вовсе, есть `t(key, lang)`. Своя копия, а не общий модуль, потому что
`bot` и `web` — пиры по контрактам `import-linter`: импортировать друг друга им
запрещено, и правильный ответ здесь не «снять контракт», а «у каждой
поверхности свой словарь». Общего у них и правда нет ни одного ключа: бот
говорит аудитору в переписке, админка — управляющей компании с экрана.

Три языка продукта по-прежнему разведены: язык ИНТЕРФЕЙСА живёт здесь, язык
РЕЧИ аудитора приезжает вместе с находкой из базы, язык ОТЧЁТА записан у
проверки. Смешивать их нельзя: формулировку находки показываем на языке речи
той проверки, где она записана, а подписи вокруг — на языке интерфейса.

Неизвестный язык — отказ, а не откат на русский: тем же правилом живут
методика (`domain.models.pick_text`) и бот.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .errors import WebTextError

#: Языки интерфейса. Третий добавляется строками в каталоге, не кодом.
UI_LANGS = ("ru", "en")

#: Язык интерфейса стенда. Имя в духе соседнего `BOT_UI_LANG`.
UI_LANG_VAR = "WEB_UI_LANG"

#: Чем админка говорит, пока переменная не задана. Русский — потому что первый
#: её пользователь управляющая компания, а не совместимость с чем-либо.
DEFAULT_UI_LANG = "ru"

TEXTS: dict[str, dict[str, str]] = {
    # --- шапка и навигация -------------------------------------------------
    "app.name": {"ru": "DECIMUS", "en": "DECIMUS"},
    "app.mark": {"ru": "Аудиты", "en": "Audits"},
    "app.tenant_label": {"ru": "Тенант", "en": "Tenant"},
    "nav.wip": {"ru": "в разработке", "en": "in progress"},
    "nav.lang": {"ru": "Язык интерфейса", "en": "Interface language"},
    # Названия разделов. Ключи (`registry`, `orders`, …) взяты из прототипа и
    # остаются кодами: переводится название, не ключ.
    "section.overview.title": {"ru": "Обзор", "en": "Overview"},
    "section.registry.title": {"ru": "Проверки", "en": "Inspections"},
    "section.plans.title": {"ru": "Планы", "en": "Action plans"},
    "section.orders.title": {"ru": "Предписания", "en": "Orders"},
    "section.country.title": {"ru": "Страна", "en": "Country"},
    "section.calendar.title": {"ru": "Календарь", "en": "Calendar"},
    "section.admin.title": {"ru": "Методика", "en": "Methodology"},
    "section.tenants.title": {"ru": "Проект", "en": "Project"},
    "section.mini.title": {"ru": "Мини-апп", "en": "Mini app"},
    # --- экран непостроенного раздела (D138) -------------------------------
    "wip.title": {"ru": "Раздел ещё в разработке", "en": "This section is not built yet"},
    "wip.text": {
        "ru": (
            "«{section}» есть в эталоне продукта, но ещё не построен. Здесь ничего не "
            "показывается намеренно: пустая или нарисованная страница выглядела бы рабочей."
        ),
        "en": (
            "“{section}” is part of the product reference, but it is not built yet. Nothing is "
            "shown here on purpose: an empty or decorative page would look like a working one."
        ),
    },
    "wip.aside": {
        "ru": (
            "Построен раздел «{built}». Остальные показаны, чтобы карта продукта была "
            "видна целиком."
        ),
        "en": (
            "The built section is “{built}”. The rest are shown so the product map stays visible."
        ),
    },
    "wip.calendar_note": {
        "ru": "Календарь и планирование проверок в текущий объём не входят (решение D139).",
        "en": "The calendar and inspection planning are out of the current scope (decision D139).",
    },
    # --- реестр проверок ---------------------------------------------------
    "registry.lead": {
        "ru": (
            "Проведённые проверки. Процент, буква и разбивка показаны такими, какими их "
            "посчитал движок при завершении проверки, — здесь ничего не пересчитывается."
        ),
        "en": (
            "Completed inspections. Percentage, grade and breakdown are shown exactly as the "
            "engine computed them when the inspection was closed — nothing is recomputed here."
        ),
    },
    "registry.count": {"ru": "Проверок: {count}", "en": "Inspections: {count}"},
    "registry.retracted_count": {"ru": "снятых: {count}", "en": "retracted: {count}"},
    "registry.col.grade": {"ru": "Оценка", "en": "Grade"},
    "registry.col.unit": {"ru": "Пиццерия", "en": "Pizzeria"},
    "registry.col.score": {"ru": "Итог, %", "en": "Total, %"},
    "registry.col.date": {"ru": "Дата обхода", "en": "Visit date"},
    "registry.col.kind": {"ru": "Вид", "en": "Kind"},
    "registry.col.auditor": {"ru": "Аудитор", "en": "Auditor"},
    "registry.col.findings": {"ru": "Записей", "en": "Findings"},
    "registry.col.status": {"ru": "Состояние", "en": "State"},
    "registry.empty.title": {"ru": "Проверок пока нет", "en": "No inspections yet"},
    "registry.empty.text": {
        "ru": "В историю этого тенанта ещё не слита ни одна завершённая проверка.",
        "en": "No completed inspection has been pushed into this tenant's history yet.",
    },
    "registry.retracted_hidden.title": {
        "ru": "Снятые проверки не видны",
        "en": "Retracted inspections are not visible",
    },
    "registry.retracted_hidden.text": {
        "ru": (
            "Подключение администратора истории ({var}) не задано. Это не значит, что снятых "
            "проверок нет, — это значит, что отсюда их не видно, и снять проверку тоже нельзя."
        ),
        "en": (
            "The history administrator connection ({var}) is not configured. That does not mean "
            "there are no retracted inspections — it means they are invisible here, and "
            "retraction is unavailable too."
        ),
    },
    "state.sealed": {"ru": "Завершена", "en": "Completed"},
    "state.retracted": {"ru": "Снята", "en": "Retracted"},
    # --- карточка проверки -------------------------------------------------
    "card.back": {"ru": "К реестру", "en": "Back to the registry"},
    "card.meta": {
        "ru": "{date} · {kind} · чек-лист {version}",
        "en": "{date} · {kind} · checklist {version}",
    },
    "card.fact.auditor": {"ru": "Аудитор", "en": "Auditor"},
    "card.fact.city": {"ru": "Город", "en": "City"},
    "card.fact.partner": {"ru": "Партнёр", "en": "Partner"},
    "card.fact.report_lang": {"ru": "Язык отчёта", "en": "Report language"},
    "card.score.unit": {"ru": "%", "en": "%"},
    "card.score.note": {
        "ru": "Вычтено {deductions} % · записей {findings}",
        "en": "Deducted {deductions} % · findings {findings}",
    },
    "card.counts.title": {"ru": "Записи по классам", "en": "Findings by class"},
    "card.zones.title": {"ru": "Потери по зонам", "en": "Loss by zone"},
    "card.zones.col.zone": {"ru": "Зона", "en": "Zone"},
    "card.zones.col.share": {"ru": "Доля", "en": "Share"},
    "card.zones.col.loss": {"ru": "Потеряно", "en": "Lost"},
    "card.zones.col.left": {"ru": "Осталось", "en": "Left"},
    "card.zones.zeroed": {"ru": "обнулена", "en": "zeroed"},
    "card.findings.title": {"ru": "Записи проверки", "en": "Inspection findings"},
    "card.findings.col.n": {"ru": "№", "en": "No."},
    "card.findings.col.code": {"ru": "Пункт", "en": "Item"},
    "card.findings.col.level": {"ru": "Класс", "en": "Class"},
    "card.findings.col.zone": {"ru": "Зона", "en": "Zone"},
    "card.findings.col.text": {"ru": "Формулировка", "en": "Wording"},
    "card.findings.zone_unusual": {"ru": "зона нетипична", "en": "unusual zone"},
    "card.findings.speech_lang": {"ru": "язык речи: {lang}", "en": "speech language: {lang}"},
    "card.findings.empty": {
        "ru": "Записей у проверки нет.",
        "en": "This inspection has no findings.",
    },
    "card.info.title": {"ru": "Информационная часть", "en": "Information part"},
    "card.not_found.title": {"ru": "Проверка не найдена", "en": "Inspection not found"},
    "card.not_found.text": {
        "ru": (
            "Такой проверки у тенанта нет. Тот же ответ приходит на проверку другого тенанта "
            "и на снятую, когда снятые не видны, — и это намеренно."
        ),
        "en": (
            "There is no such inspection for this tenant. The same answer comes for another "
            "tenant's inspection and for a retracted one when retracted are invisible — "
            "deliberately so."
        ),
    },
    # --- снятие проверки ---------------------------------------------------
    "retract.title": {"ru": "Снять проверку из истории", "en": "Retract from history"},
    "retract.hint": {
        "ru": (
            "Снятие — пометка, а не удаление: строка остаётся в истории вместе с причиной, "
            "обычной роли не видна, кадры убираются из хранилища. Причина обязательна."
        ),
        "en": (
            "Retraction marks, it does not delete: the row stays in history with its reason, "
            "is invisible to the ordinary role, and the photos are purged from storage. "
            "A reason is required."
        ),
    },
    "retract.reason_label": {"ru": "Причина снятия", "en": "Reason for retraction"},
    "retract.submit": {"ru": "Снять проверку", "en": "Retract inspection"},
    "retract.done": {
        "ru": "Проверка снята. Кадров убрано: {photos}.",
        "en": "The inspection is retracted. Photos purged: {photos}.",
    },
    "retract.failed": {"ru": "Снять не удалось: {reason}", "en": "Retraction failed: {reason}"},
    "retract.banner.title": {"ru": "Проверка снята", "en": "This inspection is retracted"},
    "retract.banner.text": {
        "ru": (
            "Причина: {reason}. Оценка не участвует в аналитике, письмо и PDF по ней не "
            "выдаются. Нужна новая проверка по точке."
        ),
        "en": (
            "Reason: {reason}. Its score does not take part in analytics, and no letter or PDF "
            "is issued for it. A new inspection of the unit is required."
        ),
    },
    # --- отказы ------------------------------------------------------------
    "error.db.title": {"ru": "База недоступна", "en": "The database is unavailable"},
    "error.db.text": {
        "ru": "История проверок не прочиталась: {reason}",
        "en": "The inspection history could not be read: {reason}",
    },
    "error.not_found.title": {"ru": "Страницы нет", "en": "No such page"},
    "error.not_found.text": {
        "ru": "Такого адреса в админке нет. Разделы — в навигации слева.",
        "en": "There is no such address in the admin. The sections are in the navigation.",
    },
}


def t(key: str, lang: str, /, **params: object) -> str:
    """Взять текст по ключу на нужном языке и подставить параметры.

    Ключ и язык — только позиционные: среди параметров текстов есть `lang`
    (язык речи аудитора в подписи к находке), и без этого он столкнулся бы с
    языком интерфейса на ровном месте.

    Отказ вместо подстановки по умолчанию во всех трёх случаях: нет ключа, нет
    языка, не хватает параметра. Показать управляющей компании «Проверок:
    {count}» хуже, чем упасть на тесте.
    """
    entry = TEXTS.get(key)
    if entry is None:
        raise WebTextError(f"Текста «{key}» нет в каталоге src/web/texts.py")
    if lang not in UI_LANGS:
        raise WebTextError(f"Язык интерфейса «{lang}» не заведён. Доступны: {', '.join(UI_LANGS)}")
    try:
        return entry[lang].format(**params)
    except KeyError as exc:
        raise WebTextError(f"Тексту «{key}» не передан параметр {exc.args[0]}") from exc


def default_ui_lang(env: Mapping[str, str] | None = None) -> str:
    """Язык интерфейса этого стенда: `WEB_UI_LANG`, иначе умолчание продукта.

    Неизвестный язык — отказ на старте, а не молчаливый откат: опечатка в
    переменной демо-стенда иначе обнаружилась бы на самом показе.
    """
    src = os.environ if env is None else env
    value = (src.get(UI_LANG_VAR) or "").strip()
    if not value:
        return DEFAULT_UI_LANG
    if value not in UI_LANGS:
        raise WebTextError(
            f"Язык интерфейса «{value}» ({UI_LANG_VAR}) не заведён. Доступны: {', '.join(UI_LANGS)}"
        )
    return value


def lang_or_default(lang: str | None, *, fallback: str) -> str:
    """Язык, названный в запросе, если он заведён; иначе язык стенда.

    Нужно ровно одному месту — переключателю языка в шапке (`?lang=en`).
    Непонятное значение в адресе не роняет страницу: это ввод снаружи, а не
    настройка стенда, и на границе он приводится к допустимому.
    """
    return lang if lang in UI_LANGS else fallback
