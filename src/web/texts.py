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
from .texts_administration import ADMINISTRATION_TEXTS
from .texts_connections import CONNECTIONS_TEXTS
from .texts_country import COUNTRY_TEXTS
from .texts_demo import DEMO_TEXTS
from .texts_dodois import DODOIS_TEXTS
from .texts_grade import GRADE_TEXTS
from .texts_home import HOME_TEXTS
from .texts_journal import JOURNAL_TEXTS
from .texts_mailings import MAILINGS_TEXTS
from .texts_master import MASTER_TEXTS
from .texts_notifications import NOTIFICATION_TEXTS
from .texts_oauth import OAUTH_TEXTS
from .texts_plan_file import PLAN_FILE_TEXTS
from .texts_plan_rows import PLAN_ROW_TEXTS
from .texts_plans import PLAN_TEXTS
from .texts_prescriptions import PRESCRIPTION_TEXTS
from .texts_ratings import RATINGS_TEXTS
from .texts_refusals import REFUSAL_TEXTS
from .texts_registry import REGISTRY_TEXTS
from .texts_second_factor import SECOND_FACTOR_TEXTS
from .texts_service_keys import SERVICE_KEYS_TEXTS
from .texts_settings import SETTINGS_TEXTS
from .texts_training import TRAINING_TEXTS
from .texts_trips import TRIP_TEXTS
from .texts_units import UNIT_TEXTS
from .texts_usage import USAGE_TEXTS
from .texts_users import USERS_TEXTS
from .texts_walk import WALK_TEXTS

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
    # Название языка — на нём самом: ищущий свой язык читает его, а не перевод.
    "nav.lang.ru": {"ru": "Русский", "en": "Русский"},
    "nav.lang.en": {"ru": "English", "en": "English"},
    # Язык — словом на языке экрана (#1086): «Язык отчёта: английский», а не «en».
    "lang.name.ru": {"ru": "русский", "en": "Russian"},
    "lang.name.en": {"ru": "английский", "en": "English"},
    "nav.sections": {"ru": "Разделы", "en": "Sections"},
    "nav.more": {"ru": "Ещё", "en": "More"},
    "split.back": {"ru": "Назад", "en": "Back"},
    "split.close": {"ru": "Закрыть", "en": "Close"},
    "nav.search": {"ru": "Поиск пиццерии", "en": "Find a pizzeria"},
    "nav.theme": {"ru": "Тема", "en": "Theme"},
    "nav.theme.system": {"ru": "Как в системе", "en": "System"},
    "nav.theme.light": {"ru": "Светлая", "en": "Light"},
    "nav.theme.dark": {"ru": "Тёмная", "en": "Dark"},
    # ── Обзор: отбор выборки, разбивка, точки (канон прототипа) ─────────
    # Названия окон периода — подписи; сами окна живут кодами в
    # `overview.PERIODS`, потому что «30 дней» переводится, а 30 нет.
    "overview.assign": {"ru": "Назначить проверку", "en": "Schedule an audit"},
    "overview.scope.all": {"ru": "Вся сеть", "en": "The whole network"},
    "overview.filter.title": {"ru": "Выборка", "en": "Selection"},
    "overview.filter.country": {"ru": "Страна", "en": "Country"},
    "overview.filter.city": {"ru": "Город", "en": "City"},
    "overview.filter.grade": {"ru": "Оценка (A–D)", "en": "Grade (A–D)"},
    "overview.filter.period": {"ru": "Период", "en": "Period"},
    "overview.filter.reset": {"ru": "Сбросить", "en": "Reset"},
    # Подписи «все …» вместо «любая»: у русских названий отборов разный род
    # («страна» женский, «город» мужской), и одно слово на всех читается
    # как опечатка ровно в половине случаев.
    "overview.filter.all_countries": {"ru": "Все страны", "en": "All countries"},
    "overview.filter.all_cities": {"ru": "Все города", "en": "All cities"},
    "overview.filter.all_grades": {"ru": "Все оценки", "en": "All grades"},
    "overview.period.all": {"ru": "всё время", "en": "all time"},
    "overview.period.d30": {"ru": "30 дней", "en": "30 days"},
    "overview.period.d90": {"ru": "90 дней", "en": "90 days"},
    "overview.period.y1": {"ru": "год", "en": "a year"},
    "overview.breakdown.grades": {"ru": "Буквы", "en": "Grades"},
    "overview.sort": {"ru": "Сортировка", "en": "Sort"},
    "overview.sort.score": {"ru": "худшие сверху", "en": "worst first"},
    "overview.sort.delta": {"ru": "по движению", "en": "by movement"},
    "overview.sort.date": {"ru": "по дате проверки", "en": "by inspection date"},
    "overview.sort.unit": {"ru": "по названию", "en": "by name"},
    "overview.points.title": {"ru": "Точки выборки", "en": "Units in the selection"},
    "overview.points.hint": {
        "ru": "последняя проверка каждой точки",
        "en": "the latest inspection of each unit",
    },
    "overview.points.unit": {"ru": "Точка", "en": "Unit"},
    "overview.points.city": {"ru": "Город", "en": "City"},
    "overview.points.grade": {"ru": "Оценка", "en": "Grade"},
    "overview.points.score": {"ru": "Итог, %", "en": "Score, %"},
    "overview.points.delta": {"ru": "Δ", "en": "Δ"},
    "overview.points.process": {"ru": "Больше всего потерь", "en": "Most points lost"},
    "overview.points.date": {"ru": "Проверена", "en": "Inspected"},
    "overview.points.empty": {
        "ru": "В этой выборке нет ни одной проверенной точки. Снимите часть отбора.",
        "en": "No inspected unit in this selection. Clear part of the filter.",
    },
    "overview.points.nodelta": {
        "ru": "первая проверка точки в выборке",
        "en": "the unit's first inspection in the selection",
    },
    # Названия разделов. Ключи (`registry`, `orders`, …) взяты из прототипа и
    # остаются кодами: переводится название, не ключ.
    # ── Обзор сети (T354) ───────────────────────────────────────────────
    # Причина повода — КОД, а фраза собирается здесь: причина одна на оба
    # языка, а текст у каждого свой. Склейка фразы в шаблоне или в слое данных
    # означала бы печатать мимо словаря.
    "overview.kicker": {
        "ru": "Аналитика сети · {tenant}",
        "en": "Network analytics · {tenant}",
    },
    "overview.lead": {
        "ru": "Куда смотреть сегодня: что сеть теряет, где это повторяется и какие точки просели.",
        "en": "Where to look today: what the network loses, where it repeats, "
        "and which units slipped.",
    },
    "overview.tile.unchecked": {"ru": "Не проверено", "en": "Not inspected"},
    # Срез длиннее предела ряда (#470): молча обрезанный ряд читается как весь.
    "overview.truncated": {
        "ru": "В срезе больше {n} проверок. Таблицы пиццерий и городов и поводы "
        "посмотреть построены по последним {n}; плитки, буквы, потери по зонам и "
        "системные нарушения — по всему срезу. Сузьте период или место, чтобы "
        "увидеть в таблицах всё.",
        "en": "The slice has more than {n} inspections. The unit and city tables and "
        "the reasons to look cover the latest {n}; the tiles, grades, zone losses and "
        "systemic findings cover the whole slice. Narrow the period or place to see "
        "everything in the tables.",
    },
    "overview.tile.note.unchecked": {
        "ru": "точек без проверки за период",
        "en": "units with no inspection in the period",
    },
    "overview.problem.critical": {
        "ru": "критических нарушений: {count}, зона обнулена",
        "en": "critical findings: {count}, zone zeroed",
    },
    "overview.problem.dropped": {
        "ru": "просела против прошлой проверки на {delta}",
        "en": "dropped {delta} against the previous inspection",
    },
    "overview.problem.low_grade": {"ru": "оценка ниже порога", "en": "score below threshold"},
    "overview.units.hint2": {
        "ru": "Критические нарушения, падение оценки, слабая буква",
        "en": "Critical findings, dropped scores, weak grades",
    },
    "overview.tile.units": {"ru": "Точек в справочнике", "en": "Units on file"},
    "overview.tile.inspections": {"ru": "Проверок", "en": "Inspections"},
    "overview.tile.average": {"ru": "Средняя оценка", "en": "Average score"},
    "overview.tile.critical": {"ru": "С критическими", "en": "With critical"},
    "overview.tile.note.units": {"ru": "проверено {checked}", "en": "{checked} inspected"},
    "overview.tile.note.inspections": {"ru": "в реестре", "en": "in the registry"},
    "overview.tile.note.average": {
        "ru": "по записанным процентам",
        "en": "over recorded percentages",
    },
    "overview.tile.note.average_none": {"ru": "считать нечего", "en": "nothing to average"},
    "overview.tile.note.critical": {"ru": "зона обнулена целиком", "en": "a whole zone zeroed"},
    "overview.attention.cta": {"ru": "Письмо партнёру", "en": "Letter to the partner"},
    # Число ПОКАЗАННЫХ поводов: список ограничен, и «поводов: 6» читалось бы как
    # «всего шесть» рядом с плиткой критических по всему срезу (#503).
    "overview.attention.count": {"ru": "показано: {count}", "en": "{count} shown"},
    "overview.attention.title": {"ru": "Требует решения сегодня", "en": "Needs a decision today"},
    "tip.hint": {"ru": "Пояснение", "en": "Explanation"},
    "tip.counts": {"ru": "Сводка", "en": "Summary"},
    "overview.attention.hint": {
        "ru": "Критические нарушения и просевшие оценки, самое срочное сверху",
        "en": "Critical findings and dropped scores, most urgent first",
    },
    "overview.attention.empty": {
        "ru": "Поводов нет: критических нарушений и оценок ниже порога в выборке не записано.",
        "en": "Nothing pending: no critical findings and no below-threshold scores recorded here.",
    },
    "overview.why.critical": {
        "ru": "критических нарушений: {detail}",
        "en": "critical findings: {detail}",
    },
    "overview.why.low_grade": {"ru": "оценка {detail} %", "en": "score {detail}%"},
    "overview.processes.title": {
        "ru": "Где сеть теряет проценты",
        "en": "Where the network loses points",
    },
    "overview.processes.hint": {
        "ru": "Сумма потерь по блокам методики — кого учить и что править",
        "en": "Losses summed by methodology block — whom to train and what to fix",
    },
    "overview.processes.spread": {
        "ru": "точек: {units} · проверок: {inspections}",
        "en": "units: {units} · inspections: {inspections}",
    },
    "overview.systemic.title": {"ru": "Системные нарушения", "en": "Systemic findings"},
    "overview.systemic.hint": {
        "ru": "Один пункт на многих точках — кандидат на обучение или правку методики",
        "en": "One item across many units — a candidate for training or a methodology fix",
    },
    "overview.systemic.spread": {
        "ru": "точек: {units} · записей: {records}",
        "en": "units: {units} · records: {records}",
    },
    "overview.units.title": {"ru": "Проблемные точки", "en": "Units at risk"},
    "overview.units.hint": {
        "ru": "Снизу вверх по записанной оценке",
        "en": "Lowest recorded score first",
    },
    "overview.units.findings": {"ru": "записей: {count}", "en": "records: {count}"},
    "overview.units.empty": {
        "ru": "Проверок в выборке нет — показывать нечего.",
        "en": "No inspections in this selection — nothing to show.",
    },
    "country.kicker": {"ru": "Страна", "en": "Country"},
    "country.filter.title": {"ru": "Отбор", "en": "Filter"},
    "country.rail.title": {"ru": "Страны", "en": "Countries"},
    "country.choose.empty": {
        "ru": "В справочнике нет ни одной пиццерии со страной.",
        "en": "No pizzeria in the directory has a country.",
    },
    "country.history.latest": {"ru": "последняя", "en": "latest"},
    "section.overview.title": {"ru": "Главная", "en": "Home"},
    "section.registry.title": {"ru": "Проверки", "en": "Inspections"},
    "section.country.title": {"ru": "Страны", "en": "Countries"},
    "section.calendar.title": {"ru": "Календарь", "en": "Calendar"},
    "section.admin.title": {"ru": "Методика", "en": "Methodology"},
    # Слово владельца (D286): вкладка, где заводят людей и привязывают бота.
    "section.users.title": {"ru": "Пользователи", "en": "Users"},
    # --- вход, выход, отказ (T323) -----------------------------------------
    # Отказ ОДИН на все причины. Раздельные «нет такого логина» и «пароль не
    # тот» превращают форму в справочник заведённых людей: перебором по ней
    # узнают, кто здесь есть, ещё не зная ни одного пароля.
    "auth.title": {"ru": "Вход", "en": "Sign in"},
    "auth.sub": {
        "ru": "Выездные проверки пиццерий Dodo",
        "en": "Dodo pizzeria field inspections",
    },
    "auth.login": {"ru": "Логин", "en": "Login"},
    "auth.password": {"ru": "Пароль", "en": "Password"},
    "auth.submit": {"ru": "Войти", "en": "Sign in"},
    # Вход через учётку Google (T332). Кнопка РЯДОМ с паролем, а не вместо:
    # у партнёра почта может оказаться не гугловой, и отнимать единственную
    # дверь ради красоты схемы нельзя.
    "auth.google": {"ru": "Войти через Google", "en": "Sign in with Google"},
    "auth.or": {"ru": "или", "en": "or"},
    # Почта учётки пришла с другого аккаунта Google (аудит 12.10, F-027).
    "auth.google_other": {
        "ru": "Этот аккаунт Google не тот, которым учётка входила раньше. Войдите "
        "прежним аккаунтом Google или попросите администратора заново привязать почту.",
        "en": "This Google account is not the one this account signed in with before. "
        "Sign in with that Google account or ask an administrator to link the email again.",
    },
    "auth.failed": {
        "ru": "Логин или пароль не подошли.",
        "en": "That login and password did not match.",
    },
    # Учётка с привязанной почтой Google паролем не входит (аудит 12.10):
    # пароль идёт через фронт и прокси, вход Google — нет.
    "auth.use_google": {
        "ru": "К этой учётке привязана почта Google — входите кнопкой «Войти через Google». "
        "Пароль для неё не принимается.",
        "en": "This account has a Google address linked — use “Sign in with Google”. "
        "Password sign-in is turned off for it.",
    },
    # Две мелкие строки внизу экрана входа (D492): кто сюда допущен и что делать с
    # забытым паролем. Самостоятельной регистрации нет — об этом первая строка.
    "auth.invite": {"ru": "Только по приглашению · Dodo", "en": "Invite-only · Dodo"},
    "auth.forgot": {
        "ru": "Забыли пароль — напишите команде проекта",
        "en": "Forgot your password — message the project team",
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
    # --- реестр проверок ---------------------------------------------------
    # ── Карточка точки (экран «point» прототипа, T355) ──────────────────
    "unit.back": {"ru": "‹ Обзор", "en": "‹ Overview"},
    "unit.title": {"ru": "Карточка точки", "en": "Unit card"},
    "unit.partner": {"ru": "партнёр {partner}", "en": "partner {partner}"},
    "unit.audits": {"ru": "проверок: {n}", "en": "audits: {n}"},
    "unit.tile.score": {"ru": "Текущая оценка", "en": "Current score"},
    "unit.last": {"ru": "Последняя проверка", "en": "Last audit"},
    "unit.movement": {"ru": "Движение оценки", "en": "Score movement"},
    "unit.profile": {"ru": "Сведения", "en": "Details"},
    "country.register.hint": {
        "ru": "работают {open}, открываются {pipeline}, закрыты {closed}",
        "en": "open {open}, opening {pipeline}, closed {closed}",
    },
    "country.register.col.partner": {"ru": "Партнёр", "en": "Partner"},
    "country.register.col.opened": {"ru": "Открыта", "en": "Opened"},
    "country.register.col.status": {"ru": "Статус", "en": "Status"},
    "unit.profile.hint": {"ru": "из свода пиццерий", "en": "from the pizzeria register"},
    "unit.profile.empty": {
        "ru": "В своде пиццерий строки для этой точки нет.",
        "en": "The pizzeria register has no row for this unit.",
    },
    "unit.profile.status": {"ru": "Статус", "en": "Status"},
    "unit.profile.address": {"ru": "Адрес", "en": "Address"},
    "unit.profile.partner": {"ru": "Партнёр", "en": "Partner"},
    "unit.profile.email": {"ru": "Почта партнёра", "en": "Partner email"},
    "unit.profile.restaurant": {"ru": "Ресторан с", "en": "Restaurant since"},
    "unit.profile.delivery": {"ru": "Доставка с", "en": "Delivery since"},
    "unit.profile.closed": {"ru": "Закрыта", "en": "Closed on"},
    "unit.profile.area": {"ru": "Площадь", "en": "Area"},
    "unit.profile.seats": {"ru": "Посадочных мест", "en": "Seats"},
    "unit.stage.open": {"ru": "Работает", "en": "Open"},
    "unit.stage.paused": {"ru": "Временно закрыта", "en": "Temporarily closed"},
    "unit.stage.pipeline": {"ru": "Открывается", "en": "Opening"},
    "unit.stage.closed": {"ru": "Закрыта", "en": "Closed"},
    "unit.movement.hint": {
        "ru": "клик по столбику — открыть отчёт",
        "en": "click a bar to open the report",
    },
    # Обрезанная ось преувеличивает разницу, поэтому граница названа вслух:
    # столбики 89 и 99 на шкале от нуля выглядят одинаковыми, а на шкале от
    # 85 — вдвое разными, и читатель обязан знать, какую картинку он видит.
    "unit.movement.scale": {"ru": "шкала от {floor}%", "en": "scale starts at {floor}%"},
    "unit.movement.empty": {
        "ru": "Проверок по этой точке ещё не было",
        "en": "This unit has not been audited yet",
    },
    "unit.weak": {
        "ru": "Где потеряны проценты в последней проверке",
        "en": "Where the last audit lost points",
    },
    "unit.weak.empty": {
        "ru": "В последней проверке потерь по направлениям не записано",
        "en": "The last audit recorded no losses by direction",
    },
    "unit.findings": {"ru": "Записи последней проверки", "en": "Records of the last audit"},
    "unit.findings.empty": {"ru": "Записей нет", "en": "No records"},
    "unit.repeats": {"ru": "Повторяющиеся нарушения", "en": "Repeating violations"},
    # Подпись утверждает правило методики, и после D191 оно настоящее: повтор
    # вычитает удвоенную ставку. Удвоение применяется по пометке аудитора в
    # конкретной проверке, а этот блок показывает наблюдение по истории кодов
    # — пометка до базы ещё не доведена (#359), поэтому «столько-то раз» здесь
    # означает «встречалось», а не «посчитано вдвое».
    "unit.repeats.note": {
        "ru": "{n} последних проверок, слева старая. Повтор стоит вдвое дороже",
        "en": "last {n} audits, oldest on the left. A repeat costs twice as much",
    },
    "unit.repeats.times": {"ru": "раз: {n}", "en": "times: {n}"},
    # Два разных утверждения, и путать их нельзя: «встречалось» — наблюдение по
    # истории кодов, «засчитано вдвое» — решение аудитора, записанное в
    # проверке и повлиявшее на цену (#359).
    "unit.repeats.doubled": {"ru": "из них вдвое: {n}", "en": "charged double: {n}"},
    "unit.finding.doubled": {"ru": "вычет удвоен", "en": "deduction doubled"},
    "unit.repeats.empty": {
        "ru": "Ни одно нарушение не повторялось",
        "en": "No violation repeated",
    },
    "unit.not_found": {"ru": "Такой точки нет", "en": "No such unit"},
    "registry.kicker": {"ru": "Реестр", "en": "Registry"},
    "registry.all_kinds": {"ru": "Все виды", "en": "All kinds"},
    "registry.filtered_out.title": {
        "ru": "Под этот отбор не подошла ни одна проверка",
        "en": "No inspection matches this filter",
    },
    "registry.filtered_out.text": {
        "ru": "В реестре проверки есть — их отсёк отбор выше. Снимите часть условий.",
        "en": (
            "The registry does have inspections — the filter above cut them out. "
            "Clear some conditions."
        ),
    },
    "registry.count": {"ru": "Принятых: {count}", "en": "Accepted: {count}"},
    "registry.retracted_count": {"ru": "отклонённых: {count}", "en": "rejected: {count}"},
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
    # «Завершена» и только. Слово «заморожена» стояло здесь за свойство, которое
    # в силе и никуда не уходит: записанная проверка не пересчитывается правкой
    # чек-листа задним числом. Но на карточке оно читается непонятным
    # техническим статусом: владелец назвал его непонятным и для себя, и для
    # пользователя (D172). Свойство объясняется
    # там, где человек правит методику, а не рядом с оценкой.
    # «Принята», а не «Завершена» (D199): с этапом приёмки завершённый обход
    # и принятая проверка — разные состояния.
    "state.sealed": {"ru": "Принята", "en": "Accepted"},
    "state.retracted": {"ru": "Отклонена", "en": "Rejected"},
    "state.review": {"ru": "На приёмке", "en": "Awaiting review"},
    # --- этап приёмки (D199) -------------------------------------------------
    "registry.review.title": {"ru": "На приёмке", "en": "Awaiting review"},
    "registry.review.empty": {"ru": "Ничего не ждёт приёмки", "en": "Nothing is awaiting review"},
    "registry.review.wait": {"ru": "ждёт {days} дн.", "en": "waiting {days} d"},
    "registry.review.wait_new": {"ru": "ждёт меньше суток", "en": "waiting under a day"},
    "registry.review.hint": {
        "ru": (
            "Обход закончен, но проверка ещё не вычитана. В историю сети, обзор и "
            "карточки точек она попадёт после подтверждения. Страна и город "
            "отбирают и здесь, период — нет: приёмка не ждёт конца месяца."
        ),
        "en": (
            "The visit is over, but nobody has reviewed the inspection yet. It joins the "
            "network history, the overview and unit cards once it is accepted. Country "
            "and city filter this list too; the period does not: review never waits "
            "for the month to end."
        ),
    },
    "accept.banner.title": {"ru": "Проверка на приёмке", "en": "Inspection awaiting review"},
    "accept.banner.text": {
        "ru": (
            "Вычитайте записи и подтвердите проверку. До подтверждения она не входит в "
            "историю сети, а её записи можно исправить."
        ),
        "en": (
            "Review the records and accept the inspection. Until then it is not part of "
            "the network history, and its records can still be corrected."
        ),
    },
    "accept.foreign": {
        "ru": (
            "Проверка другого пространства: вычитывает и подтверждает её то пространство, "
            "чья она. Здесь она только для чтения."
        ),
        "en": (
            "This inspection belongs to another space: that space reviews and accepts it. "
            "Here it is read-only."
        ),
    },
    "accept.title": {"ru": "Принять проверку", "en": "Accept inspection"},
    "accept.hint": {
        "ru": (
            "После подтверждения проверка входит в историю сети, а её записи больше не "
            "правятся. Вернуть на приёмку нельзя."
        ),
        "en": (
            "Once accepted, the inspection joins the network history and its records can no "
            "longer be edited. It cannot be sent back for review."
        ),
    },
    "accept.submit": {"ru": "Принять", "en": "Accept"},
    "accept.done": {"ru": "Проверка принята.", "en": "The inspection is accepted."},
    "accept.failed": {
        "ru": "Проверку не подтвердили: {reason}",
        "en": "The inspection was not accepted: {reason}",
    },
    "accept.meta": {"ru": "Принята {at} · {by}", "en": "Accepted {at} · {by}"},
    "accept.legacy_hint": {
        "ru": "Принята — в истории сети",
        "en": "Accepted — in the network history",
    },
    # Откуда проверка и как принята — словами в шапке карточки, а не только меткой.
    "card.origin.field": {"ru": "Через бота", "en": "Via the bot"},
    "card.origin.import": {"ru": "Через Claude", "en": "Via Claude"},
    "card.origin.legacy": {
        "ru": "Историческая из старого отчёта",
        "en": "Historical, from an old report",
    },
    "card.accepted.by": {"ru": "Принята: {by} · {at}", "en": "Accepted: {by} · {at}"},
    "card.accepted.at": {"ru": "Принята · {at}", "en": "Accepted · {at}"},
    "card.accepted.old": {
        "ru": "Принята до появления приёмки",
        "en": "Accepted before the review step existed",
    },
    "card.accepted.waiting": {"ru": "Ждёт приёмки", "en": "Awaiting acceptance"},
    "review.photo.alt": {"ru": "Кадр к записи {n}", "en": "Photo for record {n}"},
    # --- правка записи на приёмке (D200) ---------------------------------------
    "revise.level": {"ru": "Класс", "en": "Class"},
    "revise.zone": {"ru": "Зона", "en": "Zone"},
    "revise.text": {"ru": "Формулировка", "en": "Wording"},
    "revise.reading": {"ru": "Температура, °C", "en": "Temperature, °C"},
    "revise.hint": {
        "ru": "После сохранения оценка пересчитывается движком по методике этой проверки.",
        "en": "Saving recalculates the score with the engine, using this inspection's checklist.",
    },
    "revise.done": {
        "ru": "Запись исправлена, оценка пересчитана.",
        "en": "The record is corrected and the score recalculated.",
    },
    "revise.legacy": {
        "ru": (
            "это историческая проверка: оценка поставлена по методике того времени и "
            "движком не пересчитывается, сверять запись с нынешним чек-листом не с чем. "
            "Записи исторической правятся только через MCP"
        ),
        "en": (
            "this is a historical inspection: its score was given under the methodology "
            "of that time and is never recalculated by the engine, so there is no checklist "
            "to check the record against. Records of a historical inspection are edited "
            "only through MCP"
        ),
    },
    "revise.same": {"ru": "В записи ничего не изменилось.", "en": "Nothing changed in the record."},
    "revise.photos_done": {
        "ru": "Кадры записи изменены.",
        "en": "The record's photos are changed.",
    },
    "revise.photo_failed": {
        "ru": "кадры записи изменены не полностью: {reason}",
        "en": "the record's photos were not fully changed: {reason}",
    },
    "revise.failed": {
        "ru": "Запись не исправлена: {reason}",
        "en": "The record was not corrected: {reason}",
    },
    # --- новая запись и кадры на приёмке (D465) --------------------------------
    "add.submit": {"ru": "Добавить и пересчитать", "en": "Add and recalculate"},
    "add.done": {
        "ru": "Запись добавлена, оценка пересчитана.",
        "en": "The record is added and the score recalculated.",
    },
    "add.failed": {
        "ru": "Запись не добавлена: {reason}",
        "en": "The record was not added: {reason}",
    },
    "delete.done": {
        "ru": "Запись снята, оценка пересчитана.",
        "en": "The record is removed and the score recalculated.",
    },
    "delete.failed": {
        "ru": "Запись не снята: {reason}",
        "en": "The record was not removed: {reason}",
    },
    "add.photo_failed": {
        "ru": "запись добавлена и оценка пересчитана, но кадр не приложен: {reason}",
        "en": (
            "the record is added and the score recalculated, "
            "but the photo was not attached: {reason}"
        ),
    },
    "photo.none": {"ru": "кадр не выбран", "en": "no photo chosen"},
    "photo.unreadable": {
        "ru": "кадр не читается как изображение (нужен JPEG, PNG или WebP)",
        "en": "the photo cannot be read as an image (JPEG, PNG or WebP expected)",
    },
    "photo.too_many": {
        "ru": "у записи не больше {max} кадров",
        "en": "a record takes at most {max} photos",
    },
    "photo.too_big": {"ru": "кадр больше {mb} МБ", "en": "the photo is larger than {mb} MB"},
    "photo.added": {"ru": "Кадр приложен.", "en": "The photo is attached."},
    "photo.replaced": {"ru": "Кадр заменён.", "en": "The photo is replaced."},
    "photo.deleted": {"ru": "Кадр убран.", "en": "The photo is removed."},
    "photo.failed": {
        "ru": "Кадр не изменён: {reason}",
        "en": "The photo was not changed: {reason}",
    },
    # --- правка прямо в записях и «Добавить нарушение» на вычитке (D535) ------
    "proofread.edit": {"ru": "Изменить запись {n}", "en": "Edit record {n}"},
    "proofread.save": {"ru": "Сохранить", "en": "Save"},
    "proofread.cancel": {"ru": "Отмена", "en": "Cancel"},
    "proofread.delete": {"ru": "Удалить запись {n}", "en": "Delete record {n}"},
    "proofread.delete.text": {
        "ru": "Запись уйдёт из проверки вместе с кадрами, оценка пересчитается. Номера "
        "остальных записей не изменятся. Действие остаётся в журнале правок.",
        "en": "The record leaves the inspection together with its photos and the score is "
        "recalculated. Other records keep their numbers. The deletion stays in the edit log.",
    },
    "proofread.delete.yes": {"ru": "Да, удалить запись", "en": "Yes, delete the record"},
    "proofread.delete.no": {"ru": "Не удалять", "en": "Keep it"},
    "proofread.saving": {"ru": "Сохраняю…", "en": "Saving…"},
    "proofread.add": {"ru": "Добавить нарушение", "en": "Add a violation"},
    "proofread.add.title": {"ru": "Новое нарушение", "en": "New violation"},
    "proofread.add.submit": {"ru": "Добавить", "en": "Add"},
    "proofread.what": {"ru": "Что не так", "en": "What is wrong"},
    "proofread.what.hint": {
        "ru": "Своими словами, как сказал бы аудитор. Пункт, класс и зону подберёт система.",
        "en": (
            "In your own words, as the auditor would say it. "
            "The system picks the item, class and zone."
        ),
    },
    "proofread.photos": {"ru": "Фото", "en": "Photos"},
    "proofread.photos.drop": {
        "ru": "Перетащите фото сюда или выберите",
        "en": "Drop photos here or choose them",
    },
    "proofread.photos.choose": {"ru": "Выбрать фото", "en": "Choose photos"},
    "proofread.photos.remove": {"ru": "Убрать фото", "en": "Remove photo"},
    "proofread.photos.undo": {"ru": "Вернуть фото", "en": "Keep photo"},
    "proofread.suggest": {"ru": "Подобрать пункт", "en": "Find the item"},
    "proofread.suggest.busy_label": {"ru": "Подбираю…", "en": "Looking…"},
    "proofread.suggest.title": {"ru": "Подходящие пункты", "en": "Matching items"},
    "proofread.suggest.none": {
        "ru": "Подходящего пункта не нашлось — найдите его поиском ниже.",
        "en": "No matching item found — look for it with the search below.",
    },
    "proofread.suggest.question": {
        "ru": "Система спрашивает: {question}",
        "en": "The system asks: {question}",
    },
    "proofread.suggest.confidence": {"ru": "уверенность {pct}%", "en": "{pct}% sure"},
    "proofread.suggest.empty": {
        "ru": "Впишите, что не так, или приложите фото.",
        "en": "Write what is wrong, or attach a photo.",
    },
    "proofread.suggest.busy": {
        "ru": "Подбор уже идёт — подождите ответа.",
        "en": "A search is already running — wait for its answer.",
    },
    "proofread.suggest.failed": {
        "ru": (
            "Подобрать пункт не получилось. Найдите его поиском ниже — запись можно добавить и так."
        ),
        "en": (
            "Could not find the item automatically. Look for it with the search below — "
            "you can still add the record."
        ),
    },
    "proofread.suggest.no_checklist": {
        "ru": "Чек-лист этой проверки не прочитан, подобрать не с чем.",
        "en": (
            "This inspection's checklist could not be read, so there is nothing to match against."
        ),
    },
    "proofread.suggest.net": {
        "ru": "Не удалось связаться с сервером. Попробуйте ещё раз.",
        "en": "Could not reach the server. Try again.",
    },
    "proofread.item": {"ru": "Пункт", "en": "Item"},
    "proofread.item.none": {"ru": "Пункт не выбран", "en": "No item chosen"},
    "proofread.item.change": {"ru": "Сменить", "en": "Change"},
    "proofread.item.find": {"ru": "Найти пункт", "en": "Find an item"},
    "proofread.item.search": {
        "ru": "Код или слова из названия пункта",
        "en": "Item code or words from its title",
    },
    "proofread.item.nothing": {"ru": "Ничего не найдено", "en": "Nothing found"},
    "proofread.item.pick": {"ru": "Выбрать", "en": "Choose"},
    "proofread.add.need_item": {
        "ru": "Выберите пункт, чтобы добавить.",
        "en": "Choose an item to add.",
    },
    # --- карточка проверки -------------------------------------------------
    "card.back": {"ru": "К проверкам", "en": "Back to inspections"},
    "card.build.title": {"ru": "Версия чек-листа", "en": "Checklist version"},
    "card.build.checklist": {"ru": "Чек-лист", "en": "Checklist"},
    "card.build.since": {"ru": "Действует с", "en": "In use since"},
    "card.build.since_unknown": {"ru": "дата неизвестна", "en": "date unknown"},
    "card.meta": {
        "ru": "{date} · {kind} · {checklist}",
        "en": "{date} · {kind} · {checklist}",
    },
    # Месяц в дате для человека (`dates.human_day`, #963): «6 сен 2026».
    "date.mon.1": {"ru": "янв", "en": "Jan"},
    "date.mon.2": {"ru": "фев", "en": "Feb"},
    "date.mon.3": {"ru": "мар", "en": "Mar"},
    "date.mon.4": {"ru": "апр", "en": "Apr"},
    "date.mon.5": {"ru": "мая", "en": "May"},
    "date.mon.6": {"ru": "июн", "en": "Jun"},
    "date.mon.7": {"ru": "июл", "en": "Jul"},
    "date.mon.8": {"ru": "авг", "en": "Aug"},
    "date.mon.9": {"ru": "сен", "en": "Sep"},
    "date.mon.10": {"ru": "окт", "en": "Oct"},
    "date.mon.11": {"ru": "ноя", "en": "Nov"},
    "date.mon.12": {"ru": "дек", "en": "Dec"},
    "card.fact.auditor": {"ru": "Аудитор", "en": "Auditor"},
    "card.fact.city": {"ru": "Город", "en": "City"},
    "card.fact.partner": {"ru": "Партнёр", "en": "Partner"},
    "card.fact.report_lang": {"ru": "Язык отчёта", "en": "Report language"},
    "card.score.unit": {"ru": "%", "en": "%"},
    "card.score.note": {
        "ru": "Вычтено {deductions} %",
        "en": "Deducted {deductions} %",
    },
    "card.zones.title": {"ru": "Потери по зонам", "en": "Loss by zone"},
    "card.zones.none": {"ru": "Потерь по зонам нет", "en": "No loss in any zone"},
    "card.actions.label": {"ru": "Действия с проверкой", "en": "Inspection actions"},
    "card.act.move": {"ru": "Исправить", "en": "Correct"},
    "card.act.rx": {"ru": "Сформировать предписание", "en": "Create compliance notice"},
    "card.act.rx_short": {"ru": "Предписание", "en": "Notice"},
    "card.act.letter": {"ru": "Письмо", "en": "Letter"},
    "card.act.plan": {"ru": "План", "en": "Plan"},
    "card.zones.total": {"ru": "итого потеряно: {loss}", "en": "total lost: {loss}"},
    "card.zones.zeroed": {"ru": "обнулена", "en": "zeroed"},
    "card.findings.title": {"ru": "Записи проверки", "en": "Inspection findings"},
    "card.findings.col.n": {"ru": "№", "en": "No."},
    "card.findings.col.code": {"ru": "Пункт", "en": "Item"},
    "card.findings.col.level": {"ru": "Класс", "en": "Class"},
    "card.findings.col.zone": {"ru": "Зона", "en": "Zone"},
    "card.findings.col.text": {"ru": "Формулировка", "en": "Wording"},
    "card.findings.zone_unusual": {"ru": "зона нетипична", "en": "unusual zone"},
    "card.findings.reading": {"ru": "{value} °C", "en": "{value} °C"},
    "card.findings.advice": {"ru": "Рекомендация", "en": "Recommendation"},
    "card.findings.note": {"ru": "Общая заметка", "en": "General note"},
    # Историческая проверка (D332): записи старого отчёта без пункта, класса, зоны.
    "card.findings.no_class": {"ru": "без класса", "en": "no class"},
    "card.findings.no_item": {"ru": "пункт не назван", "en": "item not given"},
    "card.findings.no_zone": {"ru": "зона не названа", "en": "zone not given"},
    "card.legacy.title": {
        "ru": "Историческая проверка, оценка по методике того времени",
        "en": "Historical inspection, scored under the methodology of that time",
    },
    "card.legacy.text": {
        "ru": (
            "Оценка перенесена из старого отчёта как есть и не пересчитывается по "
            "нынешнему чек-листу. Методика: {method}. Статус в отчёте: {status}."
        ),
        "en": (
            "The score is transferred from the old report as is and is not recomputed "
            "under today's checklist. Methodology: {method}. Status in the report: {status}."
        ),
    },
    "card.legacy.method": {"ru": "Методика того времени", "en": "Methodology of that time"},
    "card.legacy.unlabelled": {"ru": "не названа", "en": "not named"},
    "letter.uploaded": {
        "ru": (
            "Проверка заведена задним числом через загрузку — письма партнёру по ней нет, "
            "и никому ничего не отправляется."
        ),
        "en": (
            "This inspection was entered after the fact through import — there is no "
            "partner letter for it, and nothing is sent to anyone."
        ),
    },
    "card.findings.speech_lang": {"ru": "язык речи: {lang}", "en": "speech language: {lang}"},
    "card.findings.empty": {
        "ru": "Записей у проверки нет.",
        "en": "This inspection has no findings.",
    },
    "card.info.title": {"ru": "Информационная часть", "en": "Information part"},
    "card.findings.photos": {"ru": "Фото: {n}", "en": "Photos: {n}"},
    "card.findings.photos_lost": {"ru": "Фото недоступно: {n}", "en": "Photos unavailable: {n}"},
    "card.findings.photos_partial": {
        "ru": "Фото: {n} · недоступно: {lost}",
        "en": "Photos: {n} · unavailable: {lost}",
    },
    "card.findings.photos_unknown": {
        "ru": "Фото к записям сейчас не показать: база не ответила.",
        "en": "Photos for the findings cannot be shown right now: the database did not answer.",
    },
    "card.info.no_question": {
        "ru": "Формулировка вопроса не найдена в методике этой проверки",
        "en": "The question wording is not in this inspection's methodology",
    },
    "card.info.no_methodology": {
        "ru": (
            "Методики той версии, по которой прошла проверка, на сервере нет — вопросы "
            "показаны кодами. Формулировку из другой версии не подставляем: это был бы "
            "другой вопрос."
        ),
        "en": (
            "The methodology version this inspection was scored by is not on the server, "
            "so questions are shown by code. Wording from another version is not "
            "substituted: it would be a different question."
        ),
    },
    "card.report.download": {"ru": "Скачать PDF", "en": "Download PDF"},
    "card.report.none": {
        "ru": (
            "PDF этой проверки не сохранён: проверка проведена до того, как отчёты начали "
            "храниться на сервере, или отчёт не доехал до хранилища."
        ),
        "en": (
            "This inspection's PDF is not stored: the inspection predates server-side "
            "report storage, or the report did not reach the storage."
        ),
    },
    "card.report.none.import": {
        "ru": (
            "PDF собирается при приёмке через Claude. Если его нет — попросите Claude "
            "собрать отчёт заново (inspection_letter / приёмка)."
        ),
        "en": (
            "The PDF is built when the inspection is accepted via Claude. If it is "
            "missing, ask Claude to build the report again (inspection_letter / acceptance)."
        ),
    },
    "card.report.none.legacy": {
        "ru": "Для исторической проверки PDF нет.",
        "en": "A historical inspection has no PDF.",
    },
    "card.report.unknown": {
        "ru": "Есть ли PDF этой проверки, сейчас неизвестно: база не ответила.",
        "en": "Whether this inspection has a PDF is unknown: the database did not answer.",
    },
    "card.report.failed": {
        "ru": "PDF не выдан: хранилище или база не ответили. Попробуйте позже.",
        "en": "The PDF could not be served: storage or database did not answer. Try again later.",
    },
    "card.not_found.title": {"ru": "Проверка не найдена", "en": "Inspection not found"},
    "card.not_found.text": {
        "ru": (
            "Такой проверки у тенанта нет. Тот же ответ приходит на проверку другого тенанта "
            "и на отклонённую, когда отклонённые не видны, — и это намеренно."
        ),
        "en": (
            "There is no such inspection for this tenant. The same answer comes for another "
            "tenant's inspection and for a rejected one when rejected are invisible — "
            "deliberately so."
        ),
    },
    # --- исправление даты и пиццерии (D195; в коде — move) --------------------------
    "move.title": {"ru": "Исправить дату или пиццерию", "en": "Correct the date or pizzeria"},
    "move.hint": {
        "ru": (
            "Если при заведении проверки ошиблись датой или пиццерией — исправьте здесь. "
            "Записи, оценка и буква не меняются. Каждое исправление остаётся в истории "
            "вместе с причиной."
        ),
        "en": (
            "If the inspection was filed with the wrong date or pizzeria, correct it here. "
            "Findings, score and grade do not change. Every correction is kept in the "
            "history with its reason."
        ),
    },
    # Карандаш у названия пиццерии на вычитке (D628).
    "unit_edit.title": {"ru": "Сменить пиццерию", "en": "Change the pizzeria"},
    "unit_edit.submit": {"ru": "Сменить", "en": "Change"},
    "unit_edit.reason_hint": {
        "ru": "Например: завели не на ту точку",
        "en": "For example: started on the wrong pizzeria",
    },
    "move.date_label": {"ru": "Дата проверки", "en": "Inspection date"},
    "move.unit_label": {"ru": "Пиццерия", "en": "Pizzeria"},
    "move.reason_label": {"ru": "Что было не так", "en": "What was wrong"},
    "move.submit": {"ru": "Исправить", "en": "Correct"},
    "move.done": {"ru": "Исправлено.", "en": "Corrected."},
    "move.same": {
        "ru": "Дата и пиццерия уже такие — исправлять нечего.",
        "en": "The date and pizzeria are already set — nothing to correct.",
    },
    "move.failed": {"ru": "Исправить не удалось: {reason}", "en": "Correction failed: {reason}"},
    "move.history.title": {"ru": "История исправлений", "en": "Correction history"},
    "move.history.line": {
        "ru": "{unit_from}, {date_from} → {unit_to}, {date_to}",
        "en": "{unit_from}, {date_from} → {unit_to}, {date_to}",
    },
    "move.history.meta": {
        "ru": "{at} · {who} · {reason}",
        "en": "{at} · {who} · {reason}",
    },
    "move.history.unknown": {
        "ru": "История исправлений сейчас недоступна — исправлять до её возвращения нельзя.",
        "en": "The correction history is unavailable — corrections are disabled until it is back.",
    },
    # --- отклонение проверки (код остаётся retract, D194) ------------------
    "retract.title": {"ru": "Отклонить проверку", "en": "Reject inspection"},
    "retract.hint": {
        "ru": (
            "Отклонение — пометка, а не удаление: строка остаётся в истории вместе с причиной, "
            "обычной роли не видна, кадры убираются из хранилища. Причина обязательна."
        ),
        "en": (
            "Rejection marks, it does not delete: the row stays in history with its reason, "
            "is invisible to the ordinary role, and the photos are purged from storage. "
            "A reason is required."
        ),
    },
    "retract.reason_label": {"ru": "Причина отклонения", "en": "Reason for rejection"},
    "retract.submit": {"ru": "Отклонить проверку", "en": "Reject inspection"},
    "retract.done": {
        "ru": "Проверка отклонена. Кадров убрано: {photos}.",
        "en": "The inspection is rejected. Photos purged: {photos}.",
    },
    "retract.failed": {"ru": "Отклонить не удалось: {reason}", "en": "Rejection failed: {reason}"},
    "retract.banner.title": {"ru": "Проверка отклонена", "en": "This inspection is rejected"},
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
    "letter.save.submit": {"ru": "Сохранить изменения", "en": "Save changes"},
    "letter.on_review": {
        "ru": (
            "Проверка ещё не подтверждена — письмо можно смотреть, но не сохранить "
            "и не отправить в Gmail, пока проверку не примут"
        ),
        "en": (
            "The inspection is not accepted yet — the letter can be viewed, but not "
            "saved or sent to Gmail until the inspection is accepted"
        ),
    },
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
    # Что экран ДЕЛАЕТ, а не чего он не делает. До T333 письмо действительно не
    # хранилось, и текст об этом остался после фиксации писем — экран обещал
    # «не хранится» кнопкой «Сохранить письмо» в том же кадре. Владелец прочёл
    # ровно это: «сохранить письмо — это что, у нас нет редактора?»
    "letter.lead": {
        "ru": (
            "Письмо собирается заново по этой проверке и по методике той версии, "
            "которой она помечена. Отправляет его человек из почты — отправки из "
            "системы нет; здесь письмо правят и сохраняют тот текст, который ушёл "
            "партнёру."
        ),
        "en": (
            "The letter is rebuilt from this inspection on the methodology version it "
            "was scored by. A human sends it from mail — the system never sends; here "
            "you edit it and save the text that went to the partner."
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
    "letter.template.label": {"ru": "Шаблон", "en": "Template"},
    "letter.template.pick": {"ru": "Шаблон письма", "en": "Letter template"},
    "letter.template.option": {"ru": "Шаблон {n}", "en": "Template {n}"},
    "letter.template.note": {
        "ru": (
            "Шаблон 1: сильные стороны после оценки, зоны роста после нарушений. "
            "Шаблон 2: нарушения как обычно, обе части обратной связи в конце письма. "
            "Выбор пересобирает текст в поле; сохранённое письмо остаётся, пока вы не "
            "нажмёте «Сохранить»."
        ),
        "en": (
            "Template 1: the store's strengths right after the grade, growth areas after the "
            "violations. Template 2: violations as usual, both feedback parts at the end of "
            "the letter. Choosing rebuilds the text in the field; the saved letter stays "
            "until you press Save."
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
    "letter.caveat.feedback_lang": {
        "ru": (
            "обратная связь аудитора («сильные стороны» и «зоны роста») записана не на языке "
            "письма — в письмо она не вставлена: её слова не переводит никто. Добавьте "
            "перевод вручную или соберите письмо на языке записи"
        ),
        "en": (
            "the auditor's feedback (strengths and growth areas) is recorded in a language "
            "other than the letter's — it was not inserted: nobody translates the auditor's "
            "words. Add a translation by hand or build the letter in the language it was "
            "written in"
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
            "Правка живёт, только если нажать «Сохранить изменения»: уход со страницы без "
            "сохранения её теряет. Сохранённый текст и есть ответ на вопрос, что именно "
            "мы отправили партнёру."
        ),
        "en": (
            "An edit survives only if you press \u201cSave changes\u201d: leaving the "
            "page without saving loses it. The saved text is the answer to what exactly "
            "we sent the partner."
        ),
    },
    # Форматирование письма (D169, #332): ровно четыре вида, больше ничего.
    # Буква на кнопке — та, что принята в редакторах этого языка.
    "letter.format.toolbar": {"ru": "Форматирование письма", "en": "Letter formatting"},
    "letter.format.bold": {"ru": "Жирный (Ctrl+B)", "en": "Bold (Ctrl+B)"},
    "letter.format.bold.glyph": {"ru": "Ж", "en": "B"},
    "letter.format.italic": {"ru": "Курсив (Ctrl+I)", "en": "Italic (Ctrl+I)"},
    "letter.format.italic.glyph": {"ru": "К", "en": "I"},
    "letter.format.strike": {"ru": "Зачёркнутый", "en": "Strikethrough"},
    "letter.format.strike.glyph": {"ru": "З", "en": "S"},
    "letter.format.link": {"ru": "Ссылка", "en": "Link"},
    "letter.format.link.address": {"ru": "Адрес ссылки", "en": "Link address"},
    "letter.format.link.apply": {"ru": "Поставить", "en": "Apply"},
    "letter.format.link.cancel": {"ru": "Отмена", "en": "Cancel"},
    "letter.format.link.select": {
        "ru": "Выделите слова, на которые поставить ссылку.",
        "en": "Select the words to put the link on.",
    },
    "letter.format.link.bad": {
        "ru": "Ссылка не поставлена: адрес должен начинаться с https://, http:// или mailto:.",
        "en": "Link not added: the address must start with https://, http:// or mailto:.",
    },
    # Черновик в почте вошедшего (T352, D174, D176, #332). «В черновики», а не
    # «Отправить»: отправки из системы нет, и кнопка не обещает того, чего не
    # делает, — иначе человек закроет экран, считая письмо ушедшим.
    "letter.gmail.submit": {"ru": "Сохранить черновик на почте", "en": "Save draft to mail"},
    "letter.gmail.ok": {
        "ru": "Черновик лежит в вашей почте — отправьте его оттуда.",
        "en": "The draft is in your mailbox — send it from there.",
    },
    "letter.gmail.failed": {
        "ru": "Черновик не создан. Письмо сохранено — попробуйте ещё раз.",
        "en": "The draft was not created. The letter is saved — please try again.",
    },
    "letter.gmail.denied": {
        "ru": "Доступ к почте не выдан — черновика нет. Письмо сохранено.",
        "en": "Mail access was not granted — no draft was created. The letter is saved.",
    },
    "letter.gmail.unavailable": {
        "ru": "Почта на этом стенде не настроена — черновик создать некуда. Письмо сохранено.",
        "en": (
            "Mail is not configured on this stand — there is nowhere to put a draft. "
            "The letter is saved."
        ),
    },
    "letter.gmail.wrong_account": {
        "ru": "Черновик не создан: доступ к почте выдал не тот аккаунт Google. Черновик кладётся "
        "только в почту, которой вы входите через Google, — выберите в окне Google её. Письмо "
        "сохранено.",
        "en": "The draft was not created: mail access came from a different Google account. "
        "Drafts go only to the mailbox you sign in with through Google — pick that one in the "
        "Google window. The letter is saved.",
    },
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
    "error.schema.title": {
        "ru": "Схема базы отстала от кода",
        "en": "The database schema is behind the code",
    },
    "error.schema.text": {
        "ru": (
            "База отвечает, но в ней нет столбца или таблицы, к которым "
            "обращается эта версия админки: миграции накатаны не все. "
            "Накатите оставшиеся (make migrate) — в коде их {total}."
        ),
        "en": (
            "The database is up, but it lacks a column or table this version "
            "of the admin relies on: not every migration has been applied. "
            "Apply the rest (make migrate) — the code has {total}."
        ),
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
    # --- чек-листы как сущности (T347) ---------------------------------------
    #
    # Продукт несёт не один эталон, а много: девелоперский аудит, аудит РНД,
    # любой другой. Тексты разводят две вещи, которые смешать легче всего:
    # СОСТОЯНИЕ чек-листа («годен к употреблению») и ПРИМЕНЕНИЕ к проду («по
    # нему идут проверки»). Первых может быть несколько, второй ровно один.
    "checklists.title": {"ru": "Чек-листы", "en": "Checklists"},
    "checklists.empty": {
        "ru": "Ни одного чек-листа ещё не заведено.",
        "en": "No checklist has been created yet.",
    },
    "checklists.col.state": {"ru": "Состояние", "en": "State"},
    "checklists.state.draft": {"ru": "черновик", "en": "draft"},
    "checklists.state.active": {"ru": "в работе", "en": "active"},
    "checklists.state.retired": {"ru": "снят", "en": "retired"},
    "checklists.state.submit": {"ru": "Сохранить", "en": "Save"},
    "checklists.state.set": {
        "ru": "Чек-лист {checklist}: состояние теперь «{state}»",
        "en": "Checklist {checklist} is now {state}",
    },
    "checklists.in_production": {"ru": "в проде", "en": "in production"},
    "checklists.new.title": {"ru": "Завести чек-лист", "en": "Create a checklist"},
    "checklists.new.text": {
        "ru": "Рождается пустым черновиком; к проду — когда появятся вопросы",
        "en": "Starts as an empty draft; goes to production once it has questions",
    },
    "checklists.new.code": {"ru": "Код", "en": "Code"},
    "checklists.new.code.hint": {
        "ru": (
            "Строчные латинские буквы, цифры, дефис и подчёркивание. Код не меняется "
            "никогда: им чек-лист связан с уже проведёнными проверками."
        ),
        "en": (
            "Lowercase Latin letters, digits, hyphen and underscore. The code never "
            "changes: it ties the checklist to inspections already scored by it."
        ),
    },
    "checklists.new.name_ru": {"ru": "Название по-русски", "en": "Russian name"},
    "checklists.new.name_en": {"ru": "Название по-английски", "en": "English name"},
    "checklists.new.submit": {"ru": "Завести", "en": "Create"},
    "checklists.created": {
        "ru": "Чек-лист {checklist} заведён черновиком. Вопросов в нём пока нет.",
        "en": "Checklist {checklist} created as a draft. It holds no questions yet.",
    },
    "checklists.apply.open": {"ru": "Применить к проду…", "en": "Apply to production…"},
    "checklists.apply.title": {"ru": "Применение к проду", "en": "Applying to production"},
    "checklists.apply.lead": {
        "ru": "Новые проверки пойдут по нему. Уже проведённые не пересчитываются.",
        "en": "New inspections will follow it. Past inspections are not rescored.",
    },
    "checklists.apply.now": {"ru": "Сейчас в проде", "en": "In production now"},
    "checklists.apply.will": {"ru": "Будет в проде", "en": "Will be in production"},
    "checklists.apply.version": {"ru": "Издание", "en": "Edition"},
    "checklists.apply.items": {"ru": "Вопросов с нарушениями", "en": "Items that hold violations"},
    "checklists.apply.zones": {"ru": "Зоны и доли", "en": "Zones and shares"},
    "checklists.apply.rates": {"ru": "Ставки вычета", "en": "Deduction rates"},
    "checklists.apply.checklist": {"ru": "Чек-лист", "en": "Checklist"},
    "checklists.apply.same": {
        "ru": "Это издание уже в проде — применять нечего.",
        "en": "This edition is already in production — nothing to apply.",
    },
    "checklists.apply.start_row": {"ru": "Начальный процент", "en": "Starting percentage"},
    "checklists.apply.nothing": {
        "ru": "Показывать нечего: опубликованного издания нет.",
        "en": "Nothing to show: there is no published edition.",
    },
    "checklists.apply.warning": {
        "ru": "Отличия подсвечены. В журнале чек-листа останется ваш логин.",
        "en": "Differences are highlighted. Your login stays in the checklist log.",
    },
    "checklists.apply.submit": {"ru": "Применить к проду", "en": "Apply to production"},
    "checklists.apply.cancel": {"ru": "Отмена", "en": "Cancel"},
    "checklists.applied": {
        "ru": "Чек-лист {checklist} применён к проду: проверки считаются по нему.",
        "en": "Checklist {checklist} is applied to production: inspections are scored by it.",
    },
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
    "methodology.draft.text": {
        "ru": (
            "Новые проверки пойдут по правкам после публикации. Уже посчитанные "
            "проверки она не меняет."
        ),
        "en": (
            "New inspections follow the edits once published. Inspections already "
            "scored stay as they are."
        ),
    },
    "methodology.publish.submit": {"ru": "Опубликовать", "en": "Publish"},
    "methodology.published": {
        "ru": "Опубликована версия {version}. Проверки считаются по ней начиная с этой минуты.",
        "en": "Version {version} is published. Inspections are scored by it from now on.",
    },
    # Методика по пространству (волна 1, #340; D283). Чужой и несуществующий
    # чек-лист — один текст: иначе ответ подтверждал бы, что чужое есть.
    "methodology.not_found": {
        "ru": "Чек-листа «{code}» нет.",
        "en": "There is no checklist “{code}”.",
    },
    "methodology.etalon_readonly": {
        "ru": "Эталон правит только УК. Здесь его можно смотреть, но не менять.",
        "en": "Only HQ edits the reference checklist. You can view it here but not change it.",
    },
    "methodology.foreign_readonly": {
        "ru": "Чек-лист другого пространства открыт только для чтения.",
        "en": "A checklist of another space is read-only.",
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
    "methodology.item.missing": {
        "ru": "Пункта {code} в этой версии нет — открыт весь список.",
        "en": "Item {code} is not in this version — showing the full list.",
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
    "methodology.versions.col.day": {"ru": "Издана", "en": "Issued"},
    "methodology.versions.hint": {
        "ru": "Версии не удаляются никогда: по ним посчитаны отчёты. Откат — публикация прежней.",
        "en": (
            "Versions are never deleted: reports were scored by them. A rollback is "
            "publishing an earlier one."
        ),
    },
    "methodology.items.title": {"ru": "Пункты", "en": "Items"},
    # Экран чек-листа: список и панель справа (D197).
    "methodology.lists.title": {"ru": "Чек-листы", "en": "Checklists"},
    "methodology.lists.prod": {"ru": "в проде", "en": "in production"},
    "methodology.lists.manage": {
        "ru": "Завести чек-лист, сменить состояние, применить к проду",
        "en": "Create a checklist, change its state, apply to production",
    },
    "methodology.search.placeholder": {
        "ru": "Код или слово из формулировки",
        "en": "Code or a word from the wording",
    },
    "methodology.pick.level": {"ru": "Класс", "en": "Level"},
    "methodology.pick.level.all": {"ru": "все", "en": "all"},
    "methodology.pick.zone": {"ru": "Зона", "en": "Zone"},
    "methodology.pick.zone.all": {"ru": "все", "en": "all"},
    "methodology.pick.group": {"ru": "Группы", "en": "Groups"},
    "methodology.group.process": {"ru": "по процессу", "en": "by process"},
    "methodology.group.zone": {"ru": "по зоне", "en": "by zone"},
    "methodology.group.level": {"ru": "по классу", "en": "by level"},
    "methodology.off.toggle": {"ru": "Выключенные", "en": "Disabled"},
    "methodology.off.hide": {"ru": "скрыты", "en": "hidden"},
    "methodology.off.show": {"ru": "показаны", "en": "shown"},
    "methodology.off.badge": {"ru": "выключен", "en": "disabled"},
    "methodology.shown": {"ru": "Показано {shown} из {total}", "en": "{shown} of {total}"},
    "methodology.add.open": {"ru": "+ Пункт", "en": "+ Item"},
    "methodology.none.title": {
        "ru": "Под отбор не попал ни один пункт",
        "en": "No item matches the filter",
    },
    "methodology.none.reset": {"ru": "Снять отбор", "en": "Clear the filter"},
    "methodology.zone.all": {"ru": "Все зоны", "en": "All zones"},
    "methodology.zone.order": {"ru": "№", "en": "#"},
    "methodology.zone.typed": {"ru": "Набрано", "en": "Typed"},
    "methodology.zone.save_order": {"ru": "Записать порядок обхода", "en": "Record walk order"},
    "methodology.zone.items": {"ru": "Пункты", "en": "Items"},
    "methodology.zone.items.count": {
        "ru": "проверяется пунктов: {count} — показать",
        "en": "{count} items check it — show",
    },
    "methodology.rail.title": {"ru": "Чек-листы", "en": "Checklists"},
    "methodology.rail.bot": {"ru": "Доступ в боте", "en": "Bot access"},
    "methodology.rail.bot_manage": {"ru": "Настроить доступ", "en": "Manage access"},
    "methodology.rail.bot_mark": {"ru": "доступен в боте", "en": "available in the bot"},
    "methodology.bot.count": {"ru": "{on} из {total}", "en": "{on} of {total}"},
    "methodology.bot.lead": {
        "ru": "Аудиторы начинают проверку по:",
        "en": "Auditors start an inspection with:",
    },
    "methodology.bot.none": {
        "ru": "Бот сейчас не даст начать проверку: ни один чек-лист не открыт.",
        "en": "The bot won't start an inspection now: no checklist is open.",
    },
    "methodology.bot.explain": {
        "ru": "Здесь решается, по каким чек-листам аудиторы начинают проверку в боте. "
        "Открыт один — бот не спрашивает. Несколько — предложит выбрать кнопками. "
        "Ни одного — бот скажет, что начать не по чему.",
        "en": "This decides which checklists auditors can start an inspection with in the bot. "
        "One open — the bot doesn't ask. Several — it offers buttons. "
        "None — the bot says there is nothing to start with.",
    },
    "methodology.bot.running": {
        "ru": "Идущие проверки переключение не трогает: они досчитываются по чек-листу, "
        "с которым начаты.",
        "en": "Inspections in progress are not affected: they finish on the checklist "
        "they were started with.",
    },
    "methodology.bot.items": {"ru": "пунктов: {count}", "en": "items: {count}"},
    "methodology.bot.on": {"ru": "в боте", "en": "in bot"},
    "methodology.bot.off": {"ru": "выключен", "en": "off"},
    "methodology.bot.toggle": {"ru": "Доступ в боте: {name}", "en": "Bot access: {name}"},
    "methodology.bot.stuck": {
        "ru": "Открыт, но бот его не даёт: {why}",
        "en": "Open, but the bot doesn't offer it: {why}",
    },
    "methodology.bot.why.draft": {"ru": "черновик", "en": "draft"},
    "methodology.bot.why.draft.hint": {
        "ru": "Переведите в работу — черновик ещё правят",
        "en": "Set it to active — a draft is still being edited",
    },
    "methodology.bot.why.retired": {"ru": "снят", "en": "retired"},
    "methodology.bot.why.retired.hint": {
        "ru": "Снятый чек-лист в бот не открывается",
        "en": "A retired checklist can't be opened in the bot",
    },
    "methodology.bot.why.unpublished": {"ru": "не опубликован", "en": "not published"},
    "methodology.bot.why.unpublished.hint": {
        "ru": "Опубликуйте записанную версию — бот берёт только опубликованное",
        "en": "Publish the recorded version — the bot only uses published ones",
    },
    "methodology.bot.why.empty": {"ru": "нет пунктов", "en": "no items"},
    "methodology.bot.why.empty.hint": {
        "ru": "Нет ни одного пункта с нарушением — такой чек-лист дал бы 100%",
        "en": "No item can be violated — such a checklist would always give 100%",
    },
    "methodology.rail.new": {"ru": "+ Новый", "en": "+ New"},
    "methodology.rail.retired": {"ru": "Снятые ({count})", "en": "Retired ({count})"},
    "methodology.col.code": {"ru": "Код", "en": "Code"},
    "methodology.col.item": {"ru": "Пункт", "en": "Item"},
    "methodology.col.levels": {"ru": "Классы", "en": "Levels"},
    "methodology.col.days": {"ru": "Срок", "en": "Fix in"},
    "methodology.days.short": {"ru": "{days} дн.", "en": "{days} d"},
    "methodology.days.long": {"ru": "{days} дн. на устранение", "en": "{days} days to fix"},
    "methodology.days.now": {"ru": "немедленно", "en": "immediately"},
    "methodology.panel.title": {"ru": "Пункт", "en": "Item"},
    "methodology.panel.close": {"ru": "Закрыть", "en": "Close"},
    "methodology.panel.prev": {"ru": "Предыдущий пункт", "en": "Previous item"},
    "methodology.panel.next": {"ru": "Следующий пункт", "en": "Next item"},
    "methodology.bar.scoring": {"ru": "Настройка оценки", "en": "Scoring setup"},
    "methodology.bar.switch": {"ru": "Другой чек-лист", "en": "Another checklist"},
    "methodology.scoring.lead": {
        "ru": "Зоны в порядке обхода, их доли в оценке и ставки вычетов. "
        "Каждая запись — новая версия; считать по ней начнут после публикации.",
        "en": "Zones in walk order, their shares of the score and deduction rates. "
        "Every save is a new version; scoring switches to it after publishing.",
    },
    "methodology.version.in_effect": {"ru": "Действует", "en": "In effect"},
    "methodology.version.unnamed": {"ru": "набор без имени", "en": "unnamed set"},
    "methodology.kind.violation": {"ru": "нарушение", "en": "violation"},
    "methodology.kind.info": {"ru": "сведения", "en": "information"},
    "methodology.kind.aggregate": {"ru": "итоговая строка", "en": "summary row"},
    "methodology.drawer.wording": {"ru": "Формулировка", "en": "Wording"},
    "methodology.drawer.record_hint": {
        "ru": "Правка ляжет новой версией рядом с действующей. "
        "Считать по ней начнут после публикации.",
        "en": "The edit is recorded as a new version next to the one in effect. "
        "Scoring uses it after publishing.",
    },
    "methodology.drawer.dirty": {"ru": "Есть незаписанные правки", "en": "Unsaved edits"},
    "methodology.drawer.more": {"ru": "Ещё действия", "en": "More actions"},
    "methodology.drawer.leave": {
        "ru": "В панели есть незаписанные правки. Уйти без записи?",
        "en": "The panel has unsaved edits. Leave without recording them?",
    },
    "methodology.days.unit": {"ru": "дн. на устранение", "en": "days to fix"},
    "methodology.panel.keys": {
        "ru": "↑ ↓ — соседний пункт · Esc — закрыть · / — поиск",
        "en": "↑ ↓ — neighbour item · Esc — close · / — search",
    },
    "methodology.panel.empty": {
        "ru": "Выберите пункт в списке — здесь откроется всё, что нужно для правки.",
        "en": "Pick an item in the list — everything needed to edit it opens here.",
    },
    "methodology.prop.levels": {"ru": "Классы", "en": "Levels"},
    "methodology.prop.zones": {"ru": "Зоны", "en": "Zones"},
    "methodology.prop.days": {"ru": "Срок", "en": "Deadline"},
    "methodology.prop.process": {"ru": "Процесс", "en": "Process"},
    "methodology.prop.wording": {"ru": "Формулировка", "en": "Wording"},
    "methodology.prop.edit": {"ru": "Изменить", "en": "Change"},
    "methodology.diff.open": {"ru": "Что изменится", "en": "What will change"},
    "methodology.diff.title": {
        "ru": "Что изменится при публикации",
        "en": "What publishing changes",
    },
    "methodology.diff.lead": {
        "ru": "Действует {current}, записана {latest}. Ниже — всё, чем они различаются.",
        "en": "{current} is in force, {latest} is recorded. Below is everything that differs.",
    },
    "methodology.diff.none": {
        "ru": (
            "Пункты и зоны не различаются: версии отличаются только служебно — "
            "именем набора или датой издания."
        ),
        "en": (
            "Items and zones are the same: the versions differ only "
            "in the set name or edition date."
        ),
    },
    "methodology.diff.kind.added": {"ru": "новый", "en": "new"},
    "methodology.diff.kind.removed": {"ru": "убран", "en": "removed"},
    "methodology.diff.kind.disabled": {"ru": "выключен", "en": "disabled"},
    "methodology.diff.kind.restored": {"ru": "возвращён", "en": "restored"},
    "methodology.diff.kind.changed": {"ru": "изменён", "en": "changed"},
    "methodology.diff.kind.zone": {"ru": "зона", "en": "zone"},
    "methodology.usage.title": {"ru": "Как часто нарушают", "en": "How often it is breached"},
    "methodology.usage.summary": {
        "ru": "Записей: {records} · точек: {units} · проверок: {inspections}",
        "en": "Records: {records} · units: {units} · inspections: {inspections}",
    },
    "methodology.usage.last": {"ru": "последний раз {day}", "en": "last on {day}"},
    "methodology.usage.never": {
        "ru": "В сданных проверках этого чек-листа ни разу не нарушен.",
        "en": "Never breached in the finalised inspections of this checklist.",
    },
    "methodology.usage.unknown": {
        "ru": "Сводка недоступна: база проверок не отвечает. Правке пункта это не мешает.",
        "en": "No summary: the inspections database does not answer. Editing is not affected.",
    },
    "methodology.prop.save": {"ru": "Записать версию", "en": "Record a version"},
    "methodology.zones.title": {"ru": "Зоны", "en": "Zones"},
    "methodology.zones.col.name": {"ru": "Название", "en": "Name"},
    "methodology.zones.col.share": {"ru": "Доля, %", "en": "Share, %"},
    "methodology.zones.hint": {
        "ru": (
            "Доля — вес зоны в оценке. Доли задаются набором сразу, потому что обязаны "
            "сойтись к 100%: версию с несошедшейся суммой движок считать откажется. "
            "Каждая правка записывается новой версией и вступает в силу публикацией."
        ),
        "en": (
            "A share is the weight of a zone in the score. Shares are set as a whole "
            "because they must add up to 100%: the engine refuses an edition whose "
            "shares do not. Every edit is written as a new edition and takes effect "
            "only when published."
        ),
    },
    "methodology.rates.title": {"ru": "Ставки вычетов", "en": "Deduction rates"},
    "methodology.rates.hint": {
        "ru": (
            "Ставка — цена нарушения. Пустое поле означает «не трогать»: ноль здесь "
            "настоящая ставка, и спутать их нельзя. Пороги букв и режим D3 живут в том "
            "же файле, но отсюда не правятся — они заданы списком правил с порядком "
            "проверки, и поле на порог соврало бы про их устройство."
        ),
        "en": (
            "A rate is the price of a violation. An empty field means «leave as is»: "
            "zero here is a real rate, and the two must not be confused. Grade "
            "thresholds and the D3 mode live in the same file but are not edited here — "
            "they are a list of ordered rules, and a field per threshold would "
            "misrepresent them."
        ),
    },
    "methodology.rates.start": {"ru": "Начальный процент", "en": "Starting percentage"},
    "methodology.rates.d1": {"ru": "Ставка D1", "en": "D1 rate"},
    "methodology.rates.d2": {"ru": "Ставка D2", "en": "D2 rate"},
    "methodology.rates.repeat": {
        "ru": "Повтор дороже во столько раз",
        "en": "Repeat costs this many times more",
    },
    "methodology.rates.submit": {"ru": "Записать ставки", "en": "Save rates"},
    "methodology.zones.col.actions": {"ru": "Что можно", "en": "Actions"},
    "methodology.zones.shares.title": {"ru": "Доли зон", "en": "Zone shares"},
    "methodology.zones.shares.submit": {"ru": "Записать доли", "en": "Save shares"},
    "methodology.zones.rename.submit": {"ru": "Переименовать", "en": "Rename"},
    "methodology.zones.remove.submit": {"ru": "Убрать зону", "en": "Remove zone"},
    "methodology.zones.remove.equal": {
        "ru": "Уравнять доли оставшихся",
        "en": "Even out the remaining shares",
    },
    "methodology.zones.add.title": {"ru": "Завести зону", "en": "Add a zone"},
    "methodology.zones.add.code": {"ru": "Код зоны", "en": "Zone code"},
    "methodology.zones.add.name_ru": {"ru": "Название (ru)", "en": "Name (ru)"},
    "methodology.zones.add.name_en": {"ru": "Название (en)", "en": "Name (en)"},
    "methodology.zones.add.share": {"ru": "Доля, %", "en": "Share, %"},
    "methodology.zones.add.equal": {
        "ru": "Уравнять доли всех зон",
        "en": "Even out the shares of all zones",
    },
    "methodology.zones.add.submit": {"ru": "Завести", "en": "Add"},
    "methodology.zones.note": {"ru": "Зачем правим", "en": "Why this edit"},
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
        "ru": (
            "Какими классами пункт вообще бывает. D0 — информационная запись: на оценку не влияет."
        ),
        "en": (
            "The levels this item can be recorded at. "
            "D0 is an information record: it does not affect the score."
        ),
    },
    "methodology.field.zones": {"ru": "Зоны", "en": "Zones"},
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
    "methodology.field.version_name": {
        "ru": "Название версии методики",
        "en": "Methodology version name",
    },
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
    "methodology.item.criteria.title": {"ru": "Критерии", "en": "Criteria"},
    "methodology.item.criteria.empty": {
        "ru": "Критериев у пункта нет — класс нарушения выводить не из чего.",
        "en": "The item has no criteria — there is nothing to derive the level from.",
    },
    "error.not_found.title": {"ru": "Страницы нет", "en": "No such page"},
    "error.not_found.text": {
        "ru": "Такого адреса в админке нет. Разделы — в навигации слева.",
        "en": "There is no such address in the admin. The sections are in the navigation.",
    },
}

# Экшн-планы (волна 2) живут своим модулем; ключи не пересекаются — это
# сверяется здесь же, а не доверяется глазу.
# Предписания (волна 3), отказы «Методики» (#475), заведение пиццерии (#437) и
# рейтинги (спека 2026-10-08) — так же.
_ЧАСТИ = (
    TEXTS,
    DEMO_TEXTS,
    DODOIS_TEXTS,
    OAUTH_TEXTS,
    CONNECTIONS_TEXTS,
    COUNTRY_TEXTS,
    GRADE_TEXTS,
    JOURNAL_TEXTS,
    MASTER_TEXTS,
    SERVICE_KEYS_TEXTS,
    NOTIFICATION_TEXTS,
    PLAN_TEXTS,
    PLAN_FILE_TEXTS,
    PLAN_ROW_TEXTS,
    PRESCRIPTION_TEXTS,
    TRIP_TEXTS,
    RATINGS_TEXTS,
    REFUSAL_TEXTS,
    REGISTRY_TEXTS,
    SECOND_FACTOR_TEXTS,
    SETTINGS_TEXTS,
    TRAINING_TEXTS,
    UNIT_TEXTS,
    USAGE_TEXTS,
    USERS_TEXTS,
    WALK_TEXTS,
    ADMINISTRATION_TEXTS,
    MAILINGS_TEXTS,
)
_ПЕРЕСЕЧЕНИЕ = {
    ключ
    for номер, часть in enumerate(_ЧАСТИ)
    for другая in _ЧАСТИ[номер + 1 :]
    for ключ in часть.keys() & другая.keys()
}
if _ПЕРЕСЕЧЕНИЕ:
    raise WebTextError(f"Ключи текстов заведены дважды: {', '.join(sorted(_ПЕРЕСЕЧЕНИЕ))}")
TEXTS = {
    **TEXTS,
    **CONNECTIONS_TEXTS,
    **COUNTRY_TEXTS,
    **DEMO_TEXTS,
    **DODOIS_TEXTS,
    **GRADE_TEXTS,
    **HOME_TEXTS,
    **JOURNAL_TEXTS,
    **MASTER_TEXTS,
    **SERVICE_KEYS_TEXTS,
    **OAUTH_TEXTS,
    **NOTIFICATION_TEXTS,
    **PLAN_TEXTS,
    **PLAN_FILE_TEXTS,
    **PLAN_ROW_TEXTS,
    **PRESCRIPTION_TEXTS,
    **TRIP_TEXTS,
    **RATINGS_TEXTS,
    **REFUSAL_TEXTS,
    **REGISTRY_TEXTS,
    **SECOND_FACTOR_TEXTS,
    **SETTINGS_TEXTS,
    **TRAINING_TEXTS,
    **UNIT_TEXTS,
    **USAGE_TEXTS,
    **USERS_TEXTS,
    **WALK_TEXTS,
    **ADMINISTRATION_TEXTS,
    **MAILINGS_TEXTS,
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
