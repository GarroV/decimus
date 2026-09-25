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
    "nav.sections": {"ru": "Разделы", "en": "Sections"},
    # ── Обзор: отбор выборки, разбивка, точки (канон прототипа) ─────────
    # Названия окон периода — подписи; сами окна живут кодами в
    # `overview.PERIODS`, потому что «30 дней» переводится, а 30 нет.
    "overview.assign": {"ru": "Назначить проверку", "en": "Schedule an audit"},
    "overview.scope.all": {"ru": "Вся сеть", "en": "The whole network"},
    "overview.scope.sub": {
        "ru": "{units} точек · {inspections} проверок · {period}",
        "en": "{units} units · {inspections} inspections · {period}",
    },
    "overview.filter.title": {"ru": "Выборка", "en": "Selection"},
    "overview.filter.country": {"ru": "Страна", "en": "Country"},
    "overview.filter.city": {"ru": "Город", "en": "City"},
    "overview.filter.grade": {"ru": "Буква", "en": "Grade"},
    "overview.filter.period": {"ru": "Период", "en": "Period"},
    "overview.filter.reset": {"ru": "Сбросить", "en": "Reset"},
    # Подписи «все …» вместо «любая»: у русских названий отборов разный род
    # («страна» женский, «город» мужской), и одно слово на всех читается
    # как опечатка ровно в половине случаев.
    "overview.filter.all_countries": {"ru": "Все страны", "en": "All countries"},
    "overview.filter.all_cities": {"ru": "Все города", "en": "All cities"},
    "overview.filter.all_grades": {"ru": "Все буквы", "en": "All grades"},
    "overview.period.all": {"ru": "всё время", "en": "all time"},
    "overview.period.d30": {"ru": "30 дней", "en": "30 days"},
    "overview.period.d90": {"ru": "90 дней", "en": "90 days"},
    "overview.period.y1": {"ru": "год", "en": "a year"},
    "overview.breakdown.title": {"ru": "Разбивка по городам", "en": "Breakdown by city"},
    "overview.breakdown.hint": {
        "ru": "клик — проверки города",
        "en": "click — the city's inspections",
    },
    "overview.breakdown.city": {"ru": "Город", "en": "City"},
    "overview.breakdown.units": {"ru": "Точек", "en": "Units"},
    "overview.breakdown.average": {"ru": "Средняя", "en": "Average"},
    "overview.breakdown.grades": {"ru": "Буквы", "en": "Grades"},
    "overview.breakdown.critical": {"ru": "D3", "en": "D3"},
    "overview.breakdown.nocity": {"ru": "Без города", "en": "No city"},
    "overview.breakdown.empty": {
        "ru": "За выбранный период проверок нет — разбивать нечего.",
        "en": "No inspections in the selected period — nothing to break down.",
    },
    "overview.breakdown.incomparable": {
        "ru": "разные издания методики",
        "en": "different methodology editions",
    },
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
    "overview.points.grade": {"ru": "Буква", "en": "Grade"},
    "overview.points.score": {"ru": "Оценка", "en": "Score"},
    "overview.points.delta": {"ru": "Δ", "en": "Δ"},
    "overview.points.zone": {"ru": "Слабая зона", "en": "Weakest zone"},
    "overview.points.date": {"ru": "Проверена", "en": "Inspected"},
    "overview.points.empty": {
        "ru": "В этой выборке нет ни одной проверенной точки. Снимите часть отбора.",
        "en": "No inspected unit in this selection. Clear part of the filter.",
    },
    "overview.points.nodelta": {
        "ru": "первая сравнимая проверка",
        "en": "first comparable inspection",
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
    "overview.tile.note.unchecked": {
        "ru": "точек без проверки за период",
        "en": "units with no inspection in the period",
    },
    "overview.problem.critical": {
        "ru": "сожжена зона: критических {count}",
        "en": "a zone burned: {count} critical",
    },
    "overview.problem.dropped": {
        "ru": "просела против прошлой проверки на {delta}",
        "en": "dropped {delta} against the previous inspection",
    },
    "overview.problem.low_grade": {"ru": "оценка ниже порога", "en": "score below threshold"},
    "overview.units.hint2": {
        "ru": "Сожжённые зоны, падение оценки, слабая буква",
        "en": "Burned zones, dropped scores, weak grades",
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
    "overview.tile.note.critical": {"ru": "сожжена зона целиком", "en": "a whole zone burned"},
    "overview.incomparable.title": {
        "ru": "Средняя по этой выборке не считается",
        "en": "No average for this selection",
    },
    "overview.incomparable.text": {
        "ru": "Проверки посчитаны по разным ставкам или разным чек-листам: одно число по ним "
        "было бы средним по несравнимому. Разбивка ниже остаётся верной — она не усредняет.",
        "en": "These inspections were scored under different rates or checklists: a single number "
        "would average the incomparable. The breakdown below still holds — it averages nothing.",
    },
    "overview.attention.cta": {"ru": "Письмо партнёру", "en": "Letter to the partner"},
    "overview.attention.count": {"ru": "поводов: {count}", "en": "{count} pending"},
    "overview.attention.title": {"ru": "Требует решения сегодня", "en": "Needs a decision today"},
    "overview.attention.hint": {
        "ru": "Сожжённые зоны и просевшие оценки, самое срочное сверху",
        "en": "Burned zones and dropped scores, most urgent first",
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
    "overview.zones.title": {
        "ru": "Где сеть теряет проценты",
        "en": "Where the network loses points",
    },
    "overview.zones.hint": {
        "ru": "Сумма потерь по зонам — что лечить системно",
        "en": "Losses summed by zone — what to fix systemically",
    },
    "overview.zones.spread": {
        "ru": "точек: {units} · проверок: {inspections}",
        "en": "units: {units} · inspections: {inspections}",
    },
    "overview.zones.empty": {
        "ru": "Потерь не записано: в выборке нет проверок с разбивкой по зонам.",
        "en": "No losses recorded: no inspection in this selection carries a zone breakdown.",
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
    "overview.systemic.empty": {
        "ru": "Повторов нет: ни один пункт не нарушен больше чем на одной точке.",
        "en": "No repeats: no item was breached at more than one unit.",
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
    "section.overview.title": {"ru": "Обзор", "en": "Overview"},
    "section.registry.title": {"ru": "Проверки", "en": "Inspections"},
    "section.plans.title": {"ru": "Планы", "en": "Action plans"},
    "section.orders.title": {"ru": "Предписания", "en": "Orders"},
    "section.country.title": {"ru": "Страна", "en": "Country"},
    "section.calendar.title": {"ru": "Календарь", "en": "Calendar"},
    "section.admin.title": {"ru": "Методика", "en": "Methodology"},
    "section.tenants.title": {"ru": "Проект", "en": "Project"},
    "section.users.title": {"ru": "Люди", "en": "People"},
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
    # Вход через учётку Google (T332). Кнопка РЯДОМ с паролем, а не вместо:
    # у партнёра почта может оказаться не гугловой, и отнимать единственную
    # дверь ради красоты схемы нельзя.
    "auth.google": {"ru": "Войти через Google", "en": "Sign in with Google"},
    "auth.google.hint": {
        "ru": "Рабочей почтой, на которую вас завели. Незнакомая почта доступа не даёт.",
        "en": "Use the work email your account was created with. Unknown emails get no access.",
    },
    "auth.or": {"ru": "или", "en": "or"},
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
    # ── Карточка точки (экран «point» прототипа, T355) ──────────────────
    "unit.back": {"ru": "‹ Аналитика сети", "en": "‹ Network analytics"},
    "unit.title": {"ru": "Карточка точки", "en": "Unit card"},
    "unit.meta": {"ru": "{city} · партнёр {partner}", "en": "{city} · partner {partner}"},
    "unit.meta.no_partner": {
        "ru": "{city} · партнёр не назначен",
        "en": "{city} · no partner assigned",
    },
    "unit.audits": {"ru": "проверок: {n}", "en": "audits: {n}"},
    "unit.tile.score": {"ru": "Текущая оценка", "en": "Current score"},
    "unit.tile.orders": {"ru": "Открытых предписаний", "en": "Open orders"},
    "unit.tile.orders.wip": {
        "ru": "предписаний в системе пока нет — раздел в разработке",
        "en": "orders do not exist in the system yet — section in progress",
    },
    "unit.last": {"ru": "Последняя проверка", "en": "Last audit"},
    "unit.movement": {"ru": "Движение оценки", "en": "Score movement"},
    "unit.movement.hint": {
        "ru": "клик по столбику — открыть отчёт",
        "en": "click a bar to open the report",
    },
    # Обрезанная ось преувеличивает разницу, поэтому граница названа вслух:
    # столбики 89 и 99 на шкале от нуля выглядят одинаковыми, а на шкале от
    # 85 — вдвое разными, и читатель обязан знать, какую картинку он видит.
    "unit.movement.scale": {"ru": "шкала от {floor}%", "en": "scale starts at {floor}%"},
    "unit.movement.mixed": {
        "ru": "Проверки разных изданий методики — высоту столбиков сравнивать нельзя",
        "en": "Audits from different methodology editions — bar heights are not comparable",
    },
    "unit.movement.empty": {
        "ru": "Проверок по этой точке ещё не было",
        "en": "This unit has not been audited yet",
    },
    "unit.weak": {"ru": "Слабые блоки последней проверки", "en": "Weak zones of the last audit"},
    "unit.weak.open": {"ru": "Открыть отчёт целиком", "en": "Open the full report"},
    "unit.weak.empty": {
        "ru": "В последней проверке потерь по зонам не записано",
        "en": "The last audit recorded no zone losses",
    },
    "unit.weak.zeroed": {"ru": "зона обнулена", "en": "zone zeroed"},
    "unit.weak.share": {"ru": "доля {share}%", "en": "share {share}%"},
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
    "unit.plan": {"ru": "План проверок точки", "en": "Audit plan for the unit"},
    "unit.plan.wip": {
        "ru": "Планов проверок в системе пока нет — раздел в разработке",
        "en": "Audit plans do not exist in the system yet — section in progress",
    },
    "unit.not_found": {"ru": "Такой точки нет", "en": "No such unit"},
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
    "registry.count": {"ru": "Проверок: {count}", "en": "Inspections: {count}"},
    "registry.retracted_count": {"ru": "отклонённых: {count}", "en": "rejected: {count}"},
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
    # «Завершена» и только. Слово «заморожена» стояло здесь за свойство, которое
    # в силе и никуда не уходит: записанная проверка не пересчитывается правкой
    # чек-листа задним числом. Но на карточке оно читается непонятным
    # техническим статусом: владелец назвал его непонятным и для себя, и для
    # пользователя (D172). Свойство объясняется
    # там, где человек правит методику, а не рядом с оценкой.
    "state.sealed": {"ru": "Завершена", "en": "Completed"},
    "state.retracted": {"ru": "Отклонена", "en": "Rejected"},
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
    "card.zones.total": {"ru": "итого потеряно: {loss}", "en": "total lost: {loss}"},
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
            "Правка живёт, только если нажать «Сохранить изменения»: уход со страницы без "
            "сохранения её теряет. Сохранённый текст и есть ответ на вопрос, что именно "
            "мы отправили партнёру."
        ),
        "en": (
            "An edit survives only if you press \u201cSave the letter\u201d: leaving the "
            "page without saving loses it. The saved text is the answer to what exactly "
            "we sent the partner."
        ),
    },
    "letter.export.submit": {"ru": "Выгрузить файлом", "en": "Download as a file"},
    # Черновик в почте вошедшего (T352, D174, D176, #332). «В черновики», а не
    # «Отправить»: отправки из системы нет, и кнопка не обещает того, чего не
    # делает, — иначе человек закроет экран, считая письмо ушедшим.
    "letter.gmail.submit": {"ru": "В черновики Google", "en": "Save to Google drafts"},
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
    "letter.draft.restore": {"ru": "Вернуть заготовку", "en": "Restore the draft"},
    # --- люди проекта (T338, #322) -----------------------------------------
    "users.lead": {
        "ru": (
            "Кто заведён в админке этого арендатора. Отключённые остаются в "
            "списке: вопрос «у кого был доступ» задают после инцидента."
        ),
        "en": (
            "Who has an account in this tenant's admin. Disabled people stay "
            "on the list: «who had access» is a question asked after an incident."
        ),
    },
    "users.count": {"ru": "{count} чел.", "en": "{count} people"},
    "users.unknown": {
        "ru": "Список сейчас недоступен — это не значит, что людей нет.",
        "en": "The list is unavailable right now — that does not mean there is nobody.",
    },
    "users.add.title": {"ru": "Завести человека", "en": "Add a person"},
    "users.add.login": {"ru": "Логин", "en": "Login"},
    "users.add.role": {"ru": "Что можно", "en": "Access"},
    "users.add.submit": {"ru": "Завести", "en": "Add"},
    "users.add.hint": {
        "ru": (
            "Пароль придумает система и покажет один раз — записать его "
            "нужно сразу. В базе от него остаётся только свёртка."
        ),
        "en": (
            "The system makes the password and shows it once — write it down "
            "right away. Only a hash of it is kept."
        ),
    },
    "users.add.failed": {
        "ru": "Завести не вышло. Логин уже занят или не годится по форме.",
        "en": "Could not add. The login is taken or malformed.",
    },
    "users.added.title": {"ru": "Учётка «{login}» заведена", "en": "Account «{login}» created"},
    "users.added.text": {
        "ru": "Пароль показан один раз — передайте его человеку и закройте страницу.",
        "en": "The password is shown once — pass it on and close this page.",
    },
    "users.role.auditor": {"ru": "Работа с проверками", "en": "Inspections only"},
    "users.role.admin": {"ru": "И управление людьми", "en": "Also manages people"},
    "users.col.login": {"ru": "Логин", "en": "Login"},
    "users.col.role": {"ru": "Что можно", "en": "Access"},
    "users.col.state": {"ru": "Состояние", "en": "State"},
    "users.col.created": {"ru": "Заведён", "en": "Added"},
    "users.state.active": {"ru": "работает", "en": "active"},
    "users.state.disabled": {"ru": "отключён {date}", "en": "disabled {date}"},
    "users.disable.submit": {"ru": "Отключить", "en": "Disable"},
    "users.disable.ok": {
        "ru": "Учётка отключена. Открытые по ней сессии перестали действовать.",
        "en": "The account is disabled. Sessions opened with it stopped working.",
    },
    "users.disable.missing": {
        "ru": "Такой живой учётки нет — возможно, её уже отключили.",
        "en": "No such active account — it may already be disabled.",
    },
    "users.disable.self": {
        "ru": (
            "Себя отключить нельзя: это выход без возврата, а на стенде с "
            "одним администратором — ещё и закрытый навсегда экран людей."
        ),
        "en": (
            "You cannot disable yourself: that is a one-way exit, and on a "
            "stand with a single admin it closes this screen for good."
        ),
    },
    "users.disable.failed": {
        "ru": "Отключить не вышло — база не ответила.",
        "en": "Could not disable — the database did not answer.",
    },
    "users.forbidden.title": {"ru": "Этот раздел не для всех", "en": "This section is restricted"},
    "users.forbidden.note": {
        "ru": (
            "Людей заводит администратор. Если он нужен вам — попросите того, "
            "кто уже им является: роль назначается изнутри админки."
        ),
        "en": (
            "Only an administrator manages people. If you need that, ask "
            "someone who already is one — the role is granted from inside."
        ),
    },
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
    # --- чек-листы как сущности (T347) ---------------------------------------
    #
    # Продукт несёт не один эталон, а много: девелоперский аудит, аудит РНД,
    # любой другой. Тексты разводят две вещи, которые смешать легче всего:
    # СОСТОЯНИЕ чек-листа («годен к употреблению») и ПРИМЕНЕНИЕ к проду («по
    # нему идут проверки»). Первых может быть несколько, второй ровно один.
    "checklists.title": {"ru": "Чек-листы", "en": "Checklists"},
    "checklists.lead": {
        "ru": (
            "Виды проверок, заведённые в системе. По одному из них идут проверки — он "
            "помечен «в проде»; остальные живут рядом и не мешают ему. Новый заводится с "
            "нуля: пустой список вопросов, одна зона, бланк ставок — и дальше наполняется "
            "как обычная методика."
        ),
        "en": (
            "The kinds of audit this system holds. Inspections are scored against one of "
            "them — the one marked 'in production'; the others live alongside and do not "
            "affect it. A new one starts from scratch: no questions, one zone, blank "
            "rates — and is then filled in like any methodology."
        ),
    },
    "checklists.count": {"ru": "Чек-листов: {count}", "en": "{count} checklists"},
    "checklists.empty": {
        "ru": "Ни одного чек-листа ещё не заведено.",
        "en": "No checklist has been created yet.",
    },
    "checklists.col.code": {"ru": "Код", "en": "Code"},
    "checklists.col.name": {"ru": "Название", "en": "Name"},
    "checklists.col.state": {"ru": "Состояние", "en": "State"},
    "checklists.col.version": {"ru": "Издание", "en": "Edition"},
    "checklists.col.actions": {"ru": "Действия", "en": "Actions"},
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
        "ru": (
            "Новый чек-лист рождается пустым черновиком, а не копией существующего: копия "
            "разошлась бы с оригиналом с первой правки, оставаясь на него похожей. Пока в "
            "нём нет ни одного вопроса, к проду он не применяется."
        ),
        "en": (
            "A new checklist is born an empty draft, not a copy of an existing one: a copy "
            "drifts from its original on the first edit while still looking like it. While "
            "it holds no questions it cannot be applied to production."
        ),
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
        "ru": (
            "После применения проверки считаются по этому чек-листу. Уже проведённые "
            "остаются на своём и не пересчитываются: отчёт, отправленный партнёру, задним "
            "числом не меняется."
        ),
        "en": (
            "Once applied, inspections are scored against this checklist. Those already "
            "scored stay on their own and are not recalculated: a report already sent to a "
            "partner does not change retroactively."
        ),
    },
    "checklists.apply.now": {"ru": "Сейчас в проде", "en": "In production now"},
    "checklists.apply.will": {"ru": "Будет в проде", "en": "Will be in production"},
    "checklists.apply.version": {"ru": "Издание", "en": "Edition"},
    "checklists.apply.items": {"ru": "Вопросов с нарушениями", "en": "Items that hold violations"},
    "checklists.apply.zones": {"ru": "Зоны и доли", "en": "Zones and shares"},
    "checklists.apply.rates": {"ru": "Ставки вычета", "en": "Deduction rates"},
    "checklists.apply.start": {"ru": "Старт: {pct}%", "en": "Start: {pct}%"},
    "checklists.apply.nothing": {
        "ru": "Показывать нечего: опубликованного издания нет.",
        "en": "Nothing to show: there is no published edition.",
    },
    "checklists.apply.warning": {
        "ru": (
            "Сверьте цифры выше. Ролей у учёток нет: применить может всякий вошедший, и "
            "поймать ошибку можно только здесь — правом её не остановить. След применения "
            "с вашим логином остаётся в журнале чек-листа."
        ),
        "en": (
            "Check the figures above. Accounts have no roles: anyone signed in can apply, "
            "and this screen is the only place an error can be caught — no permission "
            "stops it. The change is recorded in the checklist journal under your login."
        ),
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
    "methodology.versions.col.day": {"ru": "Издана", "en": "Issued"},
    "methodology.versions.hint": {
        "ru": "Версии не удаляются никогда: по ним посчитаны отчёты. Откат — публикация прежней.",
        "en": (
            "Versions are never deleted: reports were scored by them. A rollback is "
            "publishing an earlier one."
        ),
    },
    "methodology.items.title": {"ru": "Пункты", "en": "Items"},
    # Экран чек-листа в три колонки (D197).
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
    "methodology.off.badge": {"ru": "выключен", "en": "disabled"},
    "methodology.shown": {"ru": "Показано {shown} из {total}", "en": "{shown} of {total}"},
    "methodology.add.open": {"ru": "+ Пункт", "en": "+ Item"},
    "methodology.none.title": {
        "ru": "Под отбор не попал ни один пункт",
        "en": "No item matches the filter",
    },
    "methodology.none.reset": {"ru": "Снять отбор", "en": "Clear the filter"},
    "methodology.zone.all": {"ru": "Все зоны", "en": "All zones"},
    "methodology.days.short": {"ru": "{days} дн.", "en": "{days} d"},
    "methodology.days.long": {"ru": "{days} дн. на устранение", "en": "{days} days to fix"},
    "methodology.days.now": {"ru": "немедленно", "en": "immediately"},
    "methodology.panel.title": {"ru": "Пункт", "en": "Item"},
    "methodology.panel.close": {"ru": "Закрыть", "en": "Close"},
    "methodology.panel.prev": {"ru": "Предыдущий пункт", "en": "Previous item"},
    "methodology.panel.next": {"ru": "Следующий пункт", "en": "Next item"},
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
    "methodology.zones.note": {"ru": "Зачем правка", "en": "Why this edit"},
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
