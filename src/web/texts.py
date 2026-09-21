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
    # --- фиксация письма (T333, #310) ---------------------------------------
    #
    # «Сохранить», а не «Отправить»: отправки из системы нет и не заводится
    # (Q010, D035), письмо уходит из почты руками. Кнопка отвечает на «вот
    # текст, который мы считаем отправленным», и обещать большее ей нельзя.
    "letter.save.submit": {"ru": "Сохранить письмо", "en": "Save the letter"},
    "letter.save.ok": {
        "ru": "Письмо сохранено — теперь видно, какой текст ушёл партнёру",
        "en": "Letter saved — the text sent to the partner is now on record",
    },
    "letter.save.failed": {
        "ru": (
            "Письмо не сохранено. Пустой текст не записывается, "
            "а если текст есть — не ответила база"
        ),
        "en": (
            "Letter not saved. Empty text is never stored; "
            "if the text is there, the database did not answer"
        ),
    },
    "letter.saved.note": {
        "ru": "Сохранено: {who}, {when}. Показан сохранённый текст, а не пересобранный",
        "en": "Saved by {who} on {when}. Showing the saved text, not a rebuilt one",
    },
    "letter.saved.unknown": {
        "ru": "Сохранённое письмо сейчас недоступно: база не ответила. Показана заготовка",
        "en": (
            "The saved letter is unavailable right now: the database did not "
            "answer. Showing a draft"
        ),
    },
    "letter.saved.none": {
        "ru": (
            "Письмо ещё не сохраняли: показана заготовка, и правка пропадёт, если её не сохранить"
        ),
        "en": "Not saved yet: this is a draft, and edits are lost unless you save them",
    },
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
    "letter.draft.restore": {"ru": "Вернуть заготовку", "en": "Restore the draft"},
    "letter.draft.shown": {
        "ru": (
            "В поле — заготовка, собранная сейчас. Зафиксированное письмо "
            "осталось на месте: оно заменится только после сохранения."
        ),
        "en": (
            "The field shows a draft assembled just now. The saved letter is "
            "still there: it changes only once you save."
        ),
    },
    # --- отказы ------------------------------------------------------------
    "error.db.title": {"ru": "База недоступна", "en": "The database is unavailable"},
    "error.db.text": {
        "ru": "История проверок не прочиталась: {reason}",
        "en": "The inspection history could not be read: {reason}",
    },
    # --- методика: состав чек-листа и его версии (T320) --------------------
    # Слово «версия» здесь несёт весь смысл раздела: правка НИКОГДА не меняет
    # действующую методику, она кладёт рядом новую версию (D049, D050).
    # Поэтому тексты всюду говорят «записана», а «действует» — только про
    # опубликованную: иначе «сохранил» прочиталось бы как «теперь по ней и
    # считают», и управляющая компания решила бы, что предписания партнёрам
    # уже уехали по новым правилам.
    "methodology.lead": {
        "ru": (
            "Состав проверки: пункты, их классы, зоны и сроки. Любая правка кладёт рядом "
            "новую версию и проходит сверку движком; действующей она становится отдельным "
            "шагом — публикацией. Уже проведённые проверки остаются на своей версии и "
            "не пересчитываются."
        ),
        "en": (
            "What an inspection asks: items, their levels, zones and deadlines. Every edit "
            "stores a new version next to the current one and is validated by the audit "
            "engine; it takes effect only as a separate step — publishing. Inspections "
            "already scored stay on their own version and are not recalculated."
        ),
    },
    "methodology.count": {"ru": "Пунктов: {count}", "en": "{count} items"},
    "methodology.store.missing.title": {
        "ru": "Хранилище версий методики не настроено",
        "en": "The methodology version store is not configured",
    },
    "methodology.store.missing.text": {
        "ru": (
            "Не заданы переменные окружения: {vars}. Пока их нет, состав чек-листа "
            "показывать не из чего — пустая таблица читалась бы как «чек-лист пуст». "
            "Правка методики без хранилища версий невозможна по устройству: она обязана "
            "давать новую версию, а не переписывать действующую."
        ),
        "en": (
            "These environment variables are not set: {vars}. Until they are, there is "
            "nothing to show — an empty table would read as «the checklist is empty». "
            "Editing without a version store is impossible by design: an edit must produce "
            "a new version rather than overwrite the live one."
        ),
    },
    "methodology.version.viewing": {"ru": "Версия {version}", "en": "Version {version}"},
    "methodology.version.published": {
        "ru": "Действует: {version}",
        "en": "In effect: {version}",
    },
    "methodology.version.latest": {
        "ru": "Свежая записанная: {version}",
        "en": "Newest stored: {version}",
    },
    "methodology.version.badge.published": {"ru": "действует", "en": "in effect"},
    "methodology.version.badge.draft": {"ru": "не опубликована", "en": "not published"},
    "methodology.draft.title": {
        "ru": "Есть записанная версия, которой движок ещё не видит",
        "en": "A stored version the engine does not read yet",
    },
    "methodology.draft.text": {
        "ru": (
            "Записана {latest}, а проверки считаются по {current}. Публикация переставляет "
            "указатель и на уже посчитанные проверки не действует."
        ),
        "en": (
            "{latest} is stored, while inspections are scored by {current}. Publishing moves "
            "the pointer and does not touch inspections already scored."
        ),
    },
    "methodology.publish.submit": {"ru": "Опубликовать", "en": "Publish"},
    "methodology.published": {
        "ru": "Опубликована версия {version}. Проверки считаются по ней начиная с этой минуты.",
        "en": "Version {version} is published. Inspections are scored by it from now on.",
    },
    "methodology.saved": {
        "ru": (
            "Записана версия {version}. Движок её принял, но проверки считаются "
            "по-прежнему по действующей: опубликуйте её отдельным шагом."
        ),
        "en": (
            "Version {version} is stored and accepted by the engine, but inspections are "
            "still scored by the published one: publish it as a separate step."
        ),
    },
    "methodology.failed": {
        "ru": "Правка не принята: {reason}",
        "en": "The edit was refused: {reason}",
    },
    "methodology.failed.glossary": {
        "ru": (
            "Отказ пришёл словами хранилища методики — общего с разговором с агентом. "
            "На этой странице «publish_checklist_version» — это кнопка «Опубликовать», "
            "а «version_name» — поле «Имя набора»."
        ),
        "en": (
            "The refusal comes in the words of the methodology store, shared with the agent "
            "conversation. On this page «publish_checklist_version» is the «Publish» button, "
            "and «version_name» is the «Set name» field."
        ),
    },
    "methodology.old.title": {"ru": "Старая версия", "en": "An older version"},
    "methodology.old.text": {
        "ru": (
            "Показана версия {version} — правка от неё не отсчитывается, поэтому формы "
            "здесь нет. Править можно свежую записанную: {latest}."
        ),
        "en": (
            "This is version {version}; edits are not based on it, so there is no form here. "
            "The one that can be edited is the newest stored: {latest}."
        ),
    },
    "methodology.versions.title": {"ru": "Версии", "en": "Versions"},
    "methodology.versions.col.version": {"ru": "Версия", "en": "Version"},
    "methodology.versions.col.name": {"ru": "Набор", "en": "Set"},
    "methodology.versions.col.day": {"ru": "Издана", "en": "Issued"},
    "methodology.versions.hint": {
        "ru": "Версии не удаляются никогда: по ним посчитаны отчёты. Откат — публикация прежней.",
        "en": (
            "Versions are never deleted: reports were scored by them. A rollback is "
            "publishing an earlier one."
        ),
    },
    "methodology.items.title": {"ru": "Пункты", "en": "Items"},
    "methodology.col.id": {"ru": "Код", "en": "Code"},
    "methodology.col.kind": {"ru": "Вид строки", "en": "Row kind"},
    "methodology.col.process_ru": {"ru": "Процесс", "en": "Process"},
    "methodology.col.question_ru": {"ru": "Формулировка", "en": "Wording"},
    "methodology.col.levels": {"ru": "Классы", "en": "Levels"},
    "methodology.col.zones": {"ru": "Зоны", "en": "Zones"},
    "methodology.col.days": {"ru": "Срок, дней", "en": "Days"},
    "methodology.zones.title": {"ru": "Зоны", "en": "Zones"},
    "methodology.zones.col.code": {"ru": "Код", "en": "Code"},
    "methodology.zones.col.name": {"ru": "Название", "en": "Name"},
    "methodology.zones.col.share": {"ru": "Доля, %", "en": "Share, %"},
    "methodology.zones.hint": {
        "ru": (
            "Зоны и их доли правятся пока не отсюда, а из разговора с агентом: доли "
            "задаются набором сразу, потому что обязаны сойтись к 100%."
        ),
        "en": (
            "Zones and their shares are not edited here yet, only from the agent "
            "conversation: shares are set as a whole because they must add up to 100%."
        ),
    },
    "methodology.empty.title": {"ru": "Пунктов нет", "en": "No items"},
    "methodology.empty.text": {
        "ru": "В этой версии методики нет ни одного пункта.",
        "en": "This version of the methodology has no items.",
    },
    # --- правка пункта -----------------------------------------------------
    "methodology.add.title": {"ru": "Завести пункт", "en": "Add an item"},
    "methodology.add.hint": {
        "ru": (
            "Критерии стоит задать сразу: без них движок методику не примет — класс "
            "нарушения по фотографии оказался бы угадан, а не выведен из правил."
        ),
        "en": (
            "Give the criteria right away: without them the engine will not accept the "
            "methodology — the level would be guessed from a photo rather than derived."
        ),
    },
    "methodology.add.submit": {"ru": "Записать новой версией", "en": "Store as a new version"},
    "methodology.edit.title": {"ru": "Поправить пункт", "en": "Edit the item"},
    "methodology.edit.hint": {
        "ru": "Меняются только заполненные поля. Пустое поле означает «не трогать».",
        "en": "Only the fields you fill in are changed. An empty field means «leave as is».",
    },
    "methodology.edit.submit": {"ru": "Записать новой версией", "en": "Store as a new version"},
    "methodology.disable.submit": {"ru": "Выключить пункт", "en": "Switch the item off"},
    "methodology.disable.hint": {
        "ru": (
            "Выключенный пункт остаётся в методике и не предлагается на проверке — так "
            "видно, что его убрали, и вернуть его можно одной кнопкой."
        ),
        "en": (
            "A switched-off item stays in the methodology and is not offered during an "
            "inspection — so it is visible that it was withdrawn, and one button brings it back."
        ),
    },
    "methodology.restore.submit": {"ru": "Вернуть пункт", "en": "Switch the item back on"},
    "methodology.field.code": {"ru": "Код пункта", "en": "Item code"},
    "methodology.field.code.hint": {
        "ru": "Не задан — движок присвоит сам. Кодом пункт связан с проверками и картой слов.",
        "en": "Left empty, the engine assigns one. The code is what ties the item to everything.",
    },
    "methodology.field.process": {"ru": "Процесс, ru", "en": "Process, ru"},
    "methodology.field.process_en": {"ru": "Процесс, en", "en": "Process, en"},
    "methodology.field.question_ru": {"ru": "Формулировка, ru", "en": "Wording, ru"},
    "methodology.field.question_en": {"ru": "Формулировка, en", "en": "Wording, en"},
    "methodology.field.levels": {"ru": "Классы", "en": "Levels"},
    "methodology.field.levels.hint": {
        "ru": "Через точку с запятой, например D1;D2 — какими классами пункт вообще бывает.",
        "en": "Semicolon-separated, e.g. D1;D2 — the levels this item can be recorded at.",
    },
    "methodology.field.zones": {"ru": "Зоны", "en": "Zones"},
    "methodology.field.zones.hint": {
        "ru": "Коды зон через точку с запятой; * — пункт встречается в любой зоне.",
        "en": "Zone codes, semicolon-separated; * means the item appears in any zone.",
    },
    "methodology.field.days": {"ru": "Срок устранения, дней", "en": "Days to fix"},
    "methodology.field.days.hint": {
        "ru": (
            "Печатается партнёру предписанием. Ноль — «устранить немедленно», и это не то "
            "же самое, что пустое поле."
        ),
        "en": (
            "Printed to the partner as an order. Zero means «fix immediately», which is not "
            "the same as leaving the field empty."
        ),
    },
    "methodology.field.criteria": {"ru": "Критерии D1 / D2 / D3", "en": "Criteria D1 / D2 / D3"},
    "methodology.field.kind": {"ru": "Вид строки", "en": "Row kind"},
    "methodology.field.kind.hint": {
        "ru": "Выключить пункт — отдельная кнопка, а не вид строки: так это видно в журнале.",
        "en": "Switching an item off is a button, not a row kind: that way the journal shows it.",
    },
    "methodology.field.version_name": {"ru": "Имя набора", "en": "Set name"},
    "methodology.field.version_name.hint": {
        "ru": (
            "У этой методики имени ещё нет, а идентификатор версии складывается из имени, "
            "даты издания и отпечатка данных. Спрашивается один раз: дальше имя "
            "подхватывается само. Без даты в самом имени, например «imf»."
        ),
        "en": (
            "This methodology has no name yet, and a version identifier is made of the name, "
            "the issue date and a fingerprint of the data. Asked once: afterwards the name is "
            "carried over. No date inside the name itself, e.g. «imf»."
        ),
    },
    "methodology.field.note": {"ru": "Зачем правим", "en": "Why this edit"},
    "methodology.field.note.hint": {
        "ru": (
            "Одной фразой — попадёт в журнал правок вместе с вашим логином. Не длиннее "
            "{max} знаков."
        ),
        "en": (
            "One phrase — it goes into the edit journal together with your login. No longer "
            "than {max} characters."
        ),
    },
    "methodology.broken.title": {
        "ru": "Хранилище версий методики не читается",
        "en": "The methodology version store cannot be read",
    },
    "methodology.broken.text": {
        "ru": (
            "Состав чек-листа не показать: {reason}. Это не отклонённая правка, а беда "
            "самого хранилища — история проверок в соседнем разделе при этом цела."
        ),
        "en": (
            "The checklist composition cannot be shown: {reason}. This is not a refused edit "
            "but a fault of the store itself — the inspection history in the neighbouring "
            "section is unaffected."
        ),
    },
    "methodology.item.title": {"ru": "Пункт {code}", "en": "Item {code}"},
    "methodology.item.back": {"ru": "К составу", "en": "Back to the composition"},
    "methodology.item.criteria.title": {"ru": "Критерии", "en": "Criteria"},
    "methodology.item.criteria.empty": {
        "ru": "Критериев у пункта нет — класс нарушения выводить не из чего.",
        "en": "The item has no criteria — there is nothing to derive the level from.",
    },
    "methodology.item.fields.title": {"ru": "Как пункт записан", "en": "How the item is stored"},
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
