"""Раздел «Проверки»: что показать и чем это взято.

Ни одной цифры собственного производства. Процент, буква, вычеты, разбивка по
зонам и счётчики классов приезжают из базы такими, какими их положил движок при
завершении проверки, и отсюда идут прямо в шаблон. Арифметики в этом модуле нет
вовсе — это техническая гарантия принципа «оценка считается движком, и только
им», а не обещание: импорт `engine` из `src.web` роняет прогон (контракт
`engine-not-imported` в `lint-imports`).

Свой SQL поверх тех же таблиц здесь тоже не пишется: чтение — `src/db/queries`,
снятие — `src/db/retract` (D086/D089). Второго понятия «удаление» в админке не
заводится.

**«Снятых нет» и «вам их не видно» — разные ответы.** Снятые проверки видит
только администратор истории, и приходит он отдельным подключением
(`DATABASE_RETRACTION_URL`). Когда его нет, страница говорит об этом вслух, а
не показывает молча укороченный список.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.db import queries, retract
from src.db.config import DATABASE_RETRACTION_URL_VAR, load_retraction_settings
from src.db.errors import DbError
from src.db.models import InspectionDetail, InspectionRow


@dataclass(frozen=True)
class Registry:
    """Реестр проверок вместе с ответом на вопрос «а всё ли я вижу»."""

    rows: tuple[InspectionRow, ...]
    #: Видны ли снятые проверки. `False` — не «их нет», а «подключение
    #: администратора истории не задано»; страница обязана сказать это словами.
    retracted_visible: bool

    @property
    def retracted_count(self) -> int:
        return sum(1 for row in self.rows if row.retracted)


def retraction_available() -> bool:
    """Задано ли подключение администратора истории.

    Отдельной функцией, потому что ответ нужен двум местам сразу: реестру
    (показывать ли снятые) и карточке (предлагать ли снятие). Связь с базой
    здесь не проверяется — только наличие настройки; поломка подключения
    вылезет отказом на самом вызове, и переспрашивать её заранее значило бы
    ходить в сеть дважды.
    """
    try:
        load_retraction_settings()
    except DbError:
        return False
    return True


def load_registry(*, tenant: str, limit: int) -> Registry:
    """Проверки тенанта, свежие по дате обхода — первыми."""
    visible = retraction_available()
    rows = queries.list_inspections(tenant=tenant, limit=limit, include_retracted=visible)
    return Registry(rows=tuple(rows), retracted_visible=visible)


def load_card(inspection_id: str, *, tenant: str) -> InspectionDetail | None:
    """Проверка целиком: шапка, разбивка оценки, находки, информационная часть.

    `None` — проверки у тенанта нет. Тем же `None` отвечает снятая проверка,
    когда снятые не видны: «такой проверки нет» и «вам её не видно» снаружи
    неразличимы намеренно (`queries.get_inspection`).
    """
    return queries.get_inspection(
        inspection_id, tenant=tenant, include_retracted=retraction_available()
    )


def retract_card(inspection_id: str, *, tenant: str, reason: str) -> retract.Retraction:
    """Снять проверку из истории. Отказ — `RetractionError` блока `db`.

    Своей проверки причины здесь нет: обязательность причины — правило снятия
    (D089), и живёт оно в `src/db/retract.py`. Продублированное здесь, оно
    разошлось бы с оригиналом при первой же правке.
    """
    return retract.retract_inspection(inspection_id, tenant=tenant, reason=reason)


#: Имя переменной подключения администратора истории — для текста на странице.
#: Пересказывать её строкой в шаблоне нельзя: переименуют в `db`, а здесь
#: останется старое имя, и человек пойдёт заводить несуществующую переменную.
RETRACTION_URL_VAR = DATABASE_RETRACTION_URL_VAR
