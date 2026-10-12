"""Тексты вкладки «Подключения» экрана «Пользователи» (D425, #568).

Отдельным модулем по образцу `texts_users.py`: сливаются в общий каталог
(`texts.TEXTS`). Права называются человеческими словами и одной строкой, что
сервис с этим правом получает: ключи `connections.scope.*` строятся из кода
права (`api_access.SCOPES`), и тест `tests/test_web_connections_form.py` следит,
чтобы у каждого права были все три подписи.
"""

from __future__ import annotations

# Короткая метка (список), название и «что открывает» (форма и карточка).
_SCOPES: dict[str, tuple[tuple[str, str], tuple[str, str], tuple[str, str]]] = {
    "ratings:scores": (
        ("Баллы РС/РКО", "RS/RKO scores"),
        ("Баллы пиццерий по периодам РС и РКО", "Pizzeria scores by RS and RKO period"),
        (
            "Рейтинги РС и РКО: балл каждой пиццерии по периодам.",
            "RS and RKO ratings: each pizzeria's score by period.",
        ),
    ),
    "ratings:checkups": (
        ("Собираемость", "Checkup counts"),
        ("Собираемость проверок", "Checkup counts"),
        (
            "Сколько проверок пришло в период по каналам: ресторан, доставка, выезд, онлайн.",
            (
                "How many checkups arrived in a period by channel: "
                "restaurant, delivery, onsite, online."
            ),
        ),
    ),
    "ratings:violations": (
        ("Топ нарушений", "Top violations"),
        ("Топ нарушений по странам", "Top violations by country"),
        (
            "Какие нарушения встречаются чаще всего в каждой стране, по периодам.",
            "Which violations are most frequent in each country, by period.",
        ),
    ),
    "maps:ratings": (
        ("Карты", "Maps"),
        ("Оценки на картах", "Map ratings"),
        (
            "Оценки и число отзывов пиццерий на картах.",
            "Pizzeria ratings and review counts on maps.",
        ),
    ),
    "aggregators:ratings": (
        ("Агрегаторы", "Aggregators"),
        ("Оценки в агрегаторах доставки", "Delivery aggregator ratings"),
        (
            "Оценки пиццерий в приложениях доставки: тот же блок, что на «Рейтингах».",
            "Pizzeria ratings in delivery apps: the same block as on Ratings.",
        ),
    ),
    "inspections:list": (
        ("Проверки", "Inspections"),
        ("Список выездных проверок", "Onsite inspection list"),
        (
            "Принятые выездные проверки сети: пиццерия, дата, балл, буква, прошлая проверка.",
            "Accepted onsite inspections: pizzeria, date, score, grade, previous inspection.",
        ),
    ),
    "inspections:detail": (
        ("Детали проверки", "Inspection details"),
        ("Детали выездной проверки", "Onsite inspection details"),
        (
            "Разбивка оценки проверки и её записи, без персональных данных.",
            "The score breakdown and findings of one inspection, without personal data.",
        ),
    ),
    "inspections:violations": (
        ("Нарушения проверок", "Inspection violations"),
        ("Нарушения по выездным проверкам", "Onsite inspection violations"),
        (
            "Топ пунктов методики по принятым проверкам: только коды и подписи, без пиццерий.",
            (
                "Top methodology items across accepted inspections: "
                "codes and titles only, no pizzerias."
            ),
        ),
    ),
}


def _scope_texts() -> dict[str, dict[str, str]]:
    texts: dict[str, dict[str, str]] = {}
    for code, (short, name, hint) in _SCOPES.items():
        texts[f"connections.scope.short.{code}"] = {"ru": short[0], "en": short[1]}
        texts[f"connections.scope.name.{code}"] = {"ru": name[0], "en": name[1]}
        texts[f"connections.scope.hint.{code}"] = {"ru": hint[0], "en": hint[1]}
    return texts


_SCREEN: dict[str, dict[str, str]] = {
    "connections.tab": {"ru": "Подключения", "en": "Connections"},
    "connections.sub": {
        "ru": "Сервисы, которым выдан ключ к API данных: что им открыто и как они ходят.",
        "en": "Services holding a data API key: what they may read and how they call.",
    },
    "connections.count": {"ru": "Сервисов: {count}", "en": "Services: {count}"},
    "connections.add.open": {"ru": "Подключить сервис", "en": "Connect a service"},
    "connections.drawer.add": {"ru": "Подключить сервис", "en": "Connect a service"},
    "connections.drawer.card": {"ru": "Сервис", "en": "Service"},
    "connections.drawer.key": {"ru": "Ключ сервиса", "en": "Service key"},
    "connections.unknown.title": {
        "ru": "Не удалось прочитать список",
        "en": "Could not read the list",
    },
    "connections.unknown": {
        "ru": "База не ответила. Это не значит, что сервисов нет: обновите страницу чуть позже.",
        "en": (
            "The database did not answer. That does not mean there are no services: reload shortly."
        ),
    },
    "connections.empty.title": {"ru": "Сервисов пока нет", "en": "No services yet"},
    "connections.empty.text": {
        "ru": (
            "Подключите сервис, например Swarm: он получит ключ и только те права, что вы отметите."
        ),
        "en": "Connect a service, for example Swarm: it gets a key and only the rights you tick.",
    },
    "connections.col.service": {"ru": "Сервис", "en": "Service"},
    "connections.col.rights": {"ru": "Права", "en": "Rights"},
    "connections.col.countries": {"ru": "Страны", "en": "Countries"},
    "connections.col.expires": {"ru": "Срок", "en": "Expires"},
    "connections.col.last": {"ru": "Последний вызов", "en": "Last call"},
    "connections.col.week": {"ru": "За 7 дней", "en": "Last 7 days"},
    "connections.col.status": {"ru": "Статус", "en": "Status"},
    "connections.week": {
        "ru": "{calls} обращ. / {errors} ошиб.",
        "en": "{calls} calls / {errors} errors",
    },
    "connections.status.live": {"ru": "Работает", "en": "Active"},
    "connections.status.revoked": {"ru": "Отозван", "en": "Revoked"},
    "connections.status.expired": {"ru": "Истёк", "en": "Expired"},
    "connections.older": {"ru": "Отозванные и истёкшие", "en": "Revoked and expired"},
    "connections.all_network": {"ru": "вся сеть", "en": "whole network"},
    "connections.never": {"ru": "не вызывался", "en": "never called"},
    "connections.no_expiry": {"ru": "бессрочно", "en": "no expiry"},
    "connections.rights_count": {"ru": "{count} из {total}", "en": "{count} of {total}"},
    # --- форма ---------------------------------------------------------------
    "connections.form.name": {"ru": "Название", "en": "Name"},
    "connections.form.name_hint": {
        "ru": "Как вы называете сервис. До {max} знаков.",
        "en": "What you call the service. Up to {max} characters.",
    },
    "connections.form.code": {"ru": "Код", "en": "Code"},
    "connections.form.code_hint": {
        "ru": "Латиница, цифры и дефис, 2–32 знака: swarm, bi-dashboard. Потом не меняется.",
        "en": (
            "Latin letters, digits, hyphens, 2-32 characters: "
            "swarm, bi-dashboard. Cannot change later."
        ),
    },
    "connections.form.contact": {"ru": "Контакт", "en": "Contact"},
    "connections.form.contact_hint": {
        "ru": "Кому писать, если с сервисом что-то не так. Необязательно.",
        "en": "Whom to write if something is wrong with the service. Optional.",
    },
    "connections.form.scopes": {"ru": "Что сервис может читать", "en": "What the service may read"},
    "connections.form.countries": {"ru": "Страны", "en": "Countries"},
    "connections.form.countries_hint": {
        "ru": "Коды через пробел или запятую: GE AM. Пусто — вся сеть.",
        "en": "Codes separated by spaces or commas: GE AM. Empty means the whole network.",
    },
    "connections.form.expires": {"ru": "Действует до", "en": "Valid until"},
    "connections.form.expires_hint": {
        "ru": "Включительно, не раньше завтрашнего дня. Пусто — бессрочно.",
        "en": "Inclusive, tomorrow at the earliest. Empty means no expiry.",
    },
    "connections.form.submit": {"ru": "Выдать ключ", "en": "Issue a key"},
    "connections.form.save": {"ru": "Сохранить", "en": "Save"},
    # --- карточка ------------------------------------------------------------
    "connections.card.about": {"ru": "Кто это", "en": "About"},
    "connections.card.issued": {"ru": "Выдан", "en": "Issued"},
    "connections.card.issued_by": {"ru": "{by}, {date}", "en": "{by}, {date}"},
    "connections.card.revoked": {"ru": "Отозван", "en": "Revoked"},
    "connections.card.contact_none": {"ru": "контакт не указан", "en": "no contact given"},
    "connections.card.edit": {"ru": "Права и условия", "en": "Rights and terms"},
    "connections.card.edit_off": {
        "ru": "Отозванному ключу права не правятся: выдайте новый.",
        "en": "A revoked key cannot be edited: issue a new one.",
    },
    "connections.usage.title": {"ru": "Обращения за 14 дней", "en": "Calls over 14 days"},
    "connections.usage.day": {"ru": "День", "en": "Day"},
    "connections.usage.calls": {"ru": "Обращений", "en": "Calls"},
    "connections.usage.errors": {"ru": "Ошибок", "en": "Errors"},
    "connections.usage.none": {"ru": "За 14 дней обращений не было.", "en": "No calls in 14 days."},
    "connections.usage.unknown": {
        "ru": "Не удалось прочитать обращения: база не ответила.",
        "en": "Could not read the calls: the database did not answer.",
    },
    "connections.log.title": {"ru": "Последние запросы", "en": "Latest requests"},
    "connections.log.time": {"ru": "Время (UTC)", "en": "Time (UTC)"},
    "connections.log.path": {"ru": "Адрес", "en": "Path"},
    "connections.log.status": {"ru": "Ответ", "en": "Status"},
    "connections.log.none": {"ru": "Запросов пока не было.", "en": "No requests yet."},
    "connections.danger.title": {"ru": "Ключ", "en": "Key"},
    "connections.reissue.open": {"ru": "Перевыпустить ключ", "en": "Reissue the key"},
    "connections.reissue.confirm": {
        "ru": "Выдать новый ключ: старый перестанет пускать сразу. Сервис придётся перенастроить.",
        "en": (
            "Issue a new key: the old one stops working at once. The service must be reconfigured."
        ),
    },
    "connections.reissue.yes": {"ru": "Да, перевыпустить", "en": "Yes, reissue"},
    "connections.revoke.open": {"ru": "Отозвать ключ", "en": "Revoke the key"},
    "connections.revoke.confirm": {
        "ru": "Ключ перестанет пускать сразу, вернуть его нельзя: только выдать новый.",
        "en": (
            "The key stops working at once and cannot be brought "
            "back: only a new one can be issued."
        ),
    },
    "connections.revoke.yes": {"ru": "Да, отозвать", "en": "Yes, revoke"},
    # --- страница ключа ------------------------------------------------------
    "connections.key.issued": {"ru": "Ключ выдан: {name}", "en": "Key issued: {name}"},
    "connections.key.reissued": {"ru": "Новый ключ: {name}", "en": "New key: {name}"},
    "connections.key.warn": {
        "ru": (
            "Больше мы его не покажем. Скопируйте сейчас и передайте сервису: "
            "потерянный ключ не восстановить, только перевыпустить."
        ),
        "en": (
            "We will not show it again. Copy it now and hand it to the "
            "service: a lost key cannot be recovered, only reissued."
        ),
    },
    "connections.key.reissued_note": {
        "ru": "Прежний ключ уже не работает.",
        "en": "The previous key no longer works.",
    },
    "connections.key.copy": {"ru": "Скопировать", "en": "Copy"},
    "connections.key.copied": {"ru": "Скопировано", "en": "Copied"},
    "connections.key.done": {"ru": "Готово", "en": "Done"},
    # --- исходы ---------------------------------------------------------------
    "connections.ok.saved": {"ru": "Сохранено.", "en": "Saved."},
    "connections.ok.revoked": {
        "ru": "Ключ «{name}» отозван: он больше не пускает.",
        "en": "The key of “{name}” is revoked: it no longer lets anyone in.",
    },
    "connections.err.code": {
        "ru": (
            "Код: латиница в нижнем регистре, цифры и дефис, 2–32 "
            "знака, начинается с буквы или цифры."
        ),
        "en": (
            "Code: lowercase Latin letters, digits and hyphens, 2-32 "
            "characters, starting with a letter or digit."
        ),
    },
    "connections.err.name_required": {"ru": "Назовите сервис.", "en": "Give the service a name."},
    "connections.err.name_long": {
        "ru": "Название длиннее {max} знаков.",
        "en": "The name is longer than {max} characters.",
    },
    "connections.err.contact_long": {
        "ru": "Контакт длиннее {max} знаков.",
        "en": "The contact is longer than {max} characters.",
    },
    "connections.err.scopes_none": {
        "ru": "Отметьте хотя бы одно право: ключ без прав ничего не откроет.",
        "en": "Tick at least one right: a key without rights opens nothing.",
    },
    "connections.err.scopes_unknown": {
        "ru": "Такого права нет. Выберите из списка на экране.",
        "en": "No such right. Choose from the list on the screen.",
    },
    "connections.err.country_unknown": {
        "ru": "Неизвестная страна: {codes}. Допустимы коды из справочника стран «Рейтингов».",
        "en": "Unknown country: {codes}. Use codes from the Ratings country list.",
    },
    "connections.err.expires_bad": {
        "ru": "Срок — дата вида 2026-12-31.",
        "en": "The expiry is a date like 2026-12-31.",
    },
    "connections.err.expires_past": {
        "ru": "Срок не раньше завтрашнего дня.",
        "en": "The expiry cannot be earlier than tomorrow.",
    },
    "connections.err.gone": {
        "ru": "Такого действующего ключа нет: его уже отозвали или он не существует.",
        "en": "There is no such active key: it was already revoked or never existed.",
    },
    "connections.err.db": {
        "ru": "База не ответила, ничего не записано. Повторите чуть позже.",
        "en": "The database did not answer, nothing was saved. Try again shortly.",
    },
    "connections.err.countries_db": {
        "ru": (
            "Не удалось сверить страны со справочником: ничего не записано. Повторите чуть позже."
        ),
        "en": "Could not check countries against the list: nothing was saved. Try again shortly.",
    },
}

CONNECTIONS_TEXTS: dict[str, dict[str, str]] = {**_SCREEN, **_scope_texts()}
