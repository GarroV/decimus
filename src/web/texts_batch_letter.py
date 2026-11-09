# ruff: noqa: E501
"""Тексты общего письма по нескольким проверкам (D739): кнопка, выбор, окно, отказы правила.

Отдельным модулем: `texts.py` длиннее предела файла. Сливаются в общий каталог
(`texts.TEXTS`). Окно письма переиспользует подписи одиночного (`letter.*`): язык, шаблон,
сохранение, черновик, форматирование — те же слова на тех же кнопках.
"""

from __future__ import annotations

BATCH_LETTER_TEXTS: dict[str, dict[str, str]] = {
    "batch.open": {"ru": "Сформировать общее письмо", "en": "Compose a joint letter"},
    "batch.title": {"ru": "Общее письмо по проверкам", "en": "Joint letter for inspections"},
    "batch.pick.lead": {
        "ru": (
            "Отметьте принятые проверки этой страны, которые войдут в одно письмо партнёру. "
            "Между самой ранней и самой поздней — не больше {n} дней. Свежие сверху."
        ),
        "en": (
            "Tick the accepted inspections of this country that go into one letter to the "
            "partner. No more than {n} days between the earliest and the latest. Newest first."
        ),
    },
    "batch.pick.submit": {"ru": "Собрать письмо", "en": "Build the letter"},
    "batch.pick.empty": {
        "ru": "В этой стране нет принятых проверок вашего пространства.",
        "en": "This country has no accepted inspections in your space.",
    },
    "batch.letter.title": {"ru": "Общее письмо", "en": "Joint letter"},
    "batch.letter.units": {"ru": "Пиццерий: {n}", "en": "Pizzerias: {n}"},
    "batch.letter.due": {"ru": "Устранить до", "en": "Fix by"},
    "batch.letter.change": {"ru": "Изменить выбор", "en": "Change selection"},
    "batch.letter.attach_note": {
        "ru": (
            "В черновик почты уйдут PDF всех {n} проверок и общий список адресатов без повторов. "
            "Отправка — руками из почты."
        ),
        "en": (
            "The mail draft gets the PDFs of all {n} inspections and one combined recipient "
            "list without repeats. You send it yourself from the mail."
        ),
    },
    "batch.save.refused": {
        "ru": "Письмо не сохранено: выбор проверок не проходит правило общего письма.",
        "en": "The letter was not saved: the selection breaks the joint-letter rule.",
    },
    "batch.partners.differ": {
        "ru": "В выбранных пиццериях разные партнёры: {names}. Проверьте адресатов перед отправкой.",
        "en": "The selected pizzerias have different partners: {names}. Check the recipients before sending.",
    },
    "batch.caveat.plan_due_differs": {
        "ru": "у проверок записаны разные сроки плана действий — в письме срок самой поздней",
        "en": "the inspections record different action plan deadlines — the letter uses the latest",
    },
    "batch.refused.title": {
        "ru": "Общее письмо не собрано",
        "en": "The joint letter was not built",
    },
    "batch.failed.title": {"ru": "Письмо не собралось", "en": "The letter could not be built"},
    "batch.failed.read": {
        "ru": "Проверки страны сейчас не читаются. Это сбой чтения, а не отсутствие проверок.",
        "en": "The country's inspections cannot be read right now. This is a read failure, not an absence of inspections.",
    },
    "batch.refuse.missing": {
        "ru": "Одной из выбранных проверок нет среди доступных вам.",
        "en": "One of the selected inspections is not among those available to you.",
    },
    "batch.refuse.too_few": {
        "ru": "Для общего письма нужно не меньше {minimum} проверок, выбрано {n}. Одну проверку отправляют одиночным письмом.",
        "en": "A joint letter needs at least {minimum} inspections, {n} selected. A single inspection goes in its own letter.",
    },
    "batch.refuse.duplicate": {
        "ru": "Одна и та же проверка выбрана дважды.",
        "en": "The same inspection is selected twice.",
    },
    "batch.refuse.not_accepted": {
        "ru": "Проверка {unit} ещё не принята (идёт вычитка): в общее письмо входят только принятые.",
        "en": "The inspection of {unit} is not accepted yet (under review): only accepted ones go into a joint letter.",
    },
    "batch.refuse.uploaded": {
        "ru": "Проверка {unit} загружена задним числом — письма по ней нет.",
        "en": "The inspection of {unit} was uploaded after the fact — there is no letter for it.",
    },
    "batch.refuse.retracted": {
        "ru": "Проверка {unit} снята из истории и в письмо не входит.",
        "en": "The inspection of {unit} was retracted from the history and is not included.",
    },
    "batch.refuse.other_space": {
        "ru": "Проверка {unit} относится к другому пространству: в общее письмо входят только свои.",
        "en": "The inspection of {unit} belongs to another space: only your own go into a joint letter.",
    },
    "batch.refuse.other_country": {
        "ru": "Проверки относятся к разным странам или страна пиццерии не указана: общее письмо собирается по одной стране.",
        "en": "The inspections belong to different countries, or a pizzeria has no country: a joint letter covers one country.",
    },
    "batch.refuse.spread": {
        "ru": (
            "Между самой ранней ({first}) и самой поздней ({last}) проверкой {days} дн., "
            "а общее письмо — не больше {maximum}: так в него не попадает прошлый выезд. "
            "Уберите лишние проверки."
        ),
        "en": (
            "Between the earliest ({first}) and the latest ({last}) inspection there are {days} "
            "days, while a joint letter allows at most {maximum}, so an earlier trip does not "
            "slip in. Remove the extra inspections."
        ),
    },
    "batch.refuse.unit_failed": {
        "ru": "Общее письмо не собрано: проверка {unit} ({date}) — {reason}",
        "en": "The joint letter was not built: the inspection of {unit} ({date}) — {reason}",
    },
    "batch.card.line": {
        "ru": "Вошла в общее письмо от {date}",
        "en": "Included in the joint letter of {date}",
    },
}
