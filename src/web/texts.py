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
    # --- вход, выход, отказ (T323) -----------------------------------------
    # Отказ ОДИН на все причины. Раздельные «нет такого логина» и «пароль не
    # тот» превращают форму в справочник заведённых людей: перебором по ней
    # узнают, кто здесь есть, ещё не зная ни одного пароля.
    "auth.title": {"ru": "Вход", "en": "Sign in"},
    "auth.lead": {
        "ru": "Админка управляющей компании. Учётку заводит команда проекта.",
        "en": "Management company admin panel. Accounts are created by the project team.",
    },
    "auth.login": {"ru": "Логин", "en": "Login"},
    "auth.password": {"ru": "Пароль", "en": "Password"},
    "auth.submit": {"ru": "Войти", "en": "Sign in"},
    "auth.failed": {
        "ru": "Логин или пароль не подошли.",
        "en": "That login and password did not match.",
    },
    "auth.aside": {
        "ru": (
            "Забыли пароль или нужна учётка — обратитесь к команде проекта: "
            "самостоятельной регистрации здесь нет."
        ),
        "en": (
            "Forgot your password or need an account — ask the project team: "
            "there is no self-service sign-up here."
        ),
    },
    # Запрет после перебора (T325). Про счётчик говорится прямо: человек,
    # который трижды промахнулся раскладкой, обязан понять, что дверь закрыта
    # временем, а не сломалась, — иначе он пойдёт стучать в поддержку, а
    # вместе с ним пойдут и те, кому просто не повезло попасть в общий адрес.
    "auth.locked": {
        "ru": (
            "Слишком много неудачных попыток. Вход с этого адреса или под этим "
            "логином закрыт на {minutes} мин."
        ),
        "en": (
            "Too many failed attempts. Sign-in from this address or with this "
            "login is closed for {minutes} min."
        ),
    },
    "auth.logout": {"ru": "Выйти", "en": "Sign out"},
    "auth.signed_in": {"ru": "Вошли", "en": "Signed in"},
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
    "registry.checklist": {"ru": "чек-лист {version}", "en": "checklist {version}"},
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
    # «Заморожена» — не украшение к «завершена», а отдельное состояние, которое
    # обязано быть видно: завершённая проверка не пересчитывается правкой
    # чек-листа задним числом (`dodo/decimus/domain.css`, раздел «Заморожено»),
    # и в эталоне состояние написано именно так.
    "state.sealed": {"ru": "Завершена · заморожена", "en": "Completed · frozen"},
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
    # --- письмо партнёру (T321) --------------------------------------------
    #
    # «Собралось» и «можно отправлять» разведены намеренно и в текстах тоже:
    # письмо с пустой шапкой или подставленным сроком выглядит законченным,
    # и человеку надо сказать это словами, а не оставить сверять глазами.
    "letter.title": {"ru": "Письмо партнёру", "en": "Letter to the partner"},
    "letter.open": {"ru": "Письмо партнёру", "en": "Letter to the partner"},
    "letter.lead": {
        "ru": (
            "Письмо собирается заново по этой проверке и по методике той версии, "
            "которой она помечена. В системе оно не хранится: отправляет его человек "
            "из почты."
        ),
        "en": (
            "The letter is rebuilt from this inspection on the methodology version it "
            "was scored by. It is not stored in the system: a human sends it from mail."
        ),
    },
    "letter.back": {"ru": "К карточке проверки", "en": "Back to the inspection"},
    "letter.meta.lang": {"ru": "Язык письма", "en": "Letter language"},
    "letter.lang.pick": {"ru": "Собрать письмо на языке", "en": "Build the letter in"},
    "letter.lang.note": {
        "ru": (
            "По умолчанию — язык отчёта этой проверки. Формулировки находок движок "
            "не переводит ни на каком языке письма: это слова аудитора."
        ),
        "en": (
            "Defaults to this inspection's report language. The engine translates no "
            "finding wordings in any letter language: they are the auditor's own words."
        ),
    },
    "letter.meta.source": {"ru": "Методика", "en": "Methodology"},
    "letter.meta.score": {"ru": "Оценка сошлась с записанной", "en": "Score matches the record"},
    "letter.source.snapshot": {
        "ru": "снимок той версии, по которой считалась проверка",
        "en": "snapshot of the version this inspection was scored by",
    },
    "letter.source.live": {
        "ru": "боевая методика — это ровно та версия",
        "en": "live methodology, which is that exact version",
    },
    "letter.source.shelf": {
        "ru": "снимок, отложенный ботом на старте проверки",
        "en": "snapshot the bot kept when this inspection was started",
    },
    "letter.ready.title": {"ru": "Письмо готово к отправке", "en": "Ready to send"},
    "letter.ready.text": {
        "ru": "Оценка, посчитанная движком заново, совпала с записанной в базе.",
        "en": "The score the engine recomputed matches the one recorded.",
    },
    "letter.caveats.title": {
        "ru": "Отправлять как есть нельзя",
        "en": "Not ready to send as it stands",
    },
    "letter.caveats.lead": {
        "ru": (
            "Письмо собрано, и оценка в нём верна, но восстановилось не всё. "
            "По виду письма это не заметно — поэтому названо здесь:"
        ),
        "en": (
            "The letter is built and its score is correct, but not everything was "
            "restored. The letter itself does not show it — hence the list:"
        ),
    },
    "letter.caveat.cover.auditor": {
        "ru": "не восстановлено имя аудитора",
        "en": "auditor name not restored",
    },
    "letter.caveat.cover.city": {"ru": "не восстановлен город", "en": "city not restored"},
    "letter.caveat.cover.partner": {"ru": "не восстановлен партнёр", "en": "partner not restored"},
    "letter.caveat.cover.contact": {"ru": "не восстановлен контакт", "en": "contact not restored"},
    "letter.caveat.plan_due": {
        "ru": (
            "срок плана действий в письме подставлен расчётом, а не взят из ответа "
            "аудитора — партнёр может получить не тот срок, что у него на руках"
        ),
        "en": (
            "the action plan deadline is computed, not taken from the auditor's answer "
            "— the partner may get a deadline different from the one they hold"
        ),
    },
    "letter.caveat.speech_lang": {
        "ru": (
            "часть формулировок напечатана на языке речи аудитора: их не переводит "
            "никто, это его слова"
        ),
        "en": (
            "some wordings are printed in the auditor's speech language: nobody "
            "translates them, they are the auditor's own words"
        ),
    },
    "letter.caveat.blank": {
        "ru": (
            "у части находок формулировки нет ни на одном языке — движок называет "
            "пункт пунктом, и дописать слова может только аудитор"
        ),
        "en": (
            "some findings have no wording in any language — the engine names the item "
            "instead, and only the auditor can supply the words"
        ),
    },
    "letter.failed.title": {
        "ru": "Письмо собрать не удалось",
        "en": "The letter could not be built",
    },
    "letter.edit.label": {"ru": "Текст письма", "en": "Letter text"},
    "letter.edit.hint": {
        "ru": (
            "Правки здесь никуда не сохраняются — письмо каждый раз собирается заново. "
            "Поправьте и выгрузите файл либо скопируйте текст в почту."
        ),
        "en": (
            "Edits here are not stored — the letter is rebuilt every time. Adjust it and "
            "download the file, or copy the text into mail."
        ),
    },
    "letter.export.submit": {"ru": "Выгрузить файлом", "en": "Download as a file"},
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
