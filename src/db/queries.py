"""Чтение уже слитых проверок. Только `select` — решений и расчётов здесь нет.

Дополняет `push_inspection` (T093) собственным способом проверить слив, не
трогая psql руками; читает отсюда же MCP-сервер (T095, блок `mcp`), и своих
запросов к базе он не пишет — никто, кроме этого блока, в Postgres не ходит.

**Охват — обязательный параметр, а не фильтр** (T110, волна 1 #340). Читает
отсюда MCP-сервер, который мы сами даём в руки агенту партнёра, и
необязательный фильтр там однажды не передадут. Поэтому у охвата (`Reach`,
`src/db/reach.py`) нет значения по умолчанию: вызов без него не проходит
вовсе, вместо того чтобы молча отдать чужую историю. УК читает всю сеть,
партнёр — пиццерии своих стран (D283, D289). То же правило и у чтения по
идентификатору (T114): угадать идентификатор нельзя, но неугадываемость — это
надежда, а не защита. Исключение одно — `previous_inspection`: повтор ×2
(D255) считается по проверкам своего пространства и идёт по тенанту.

**Период отбирает база, а не вызывающий поверх прочитанной страницы** (T114).
Историю за три года зальют одним заходом программно (D035), и `pushed_at` у
всей истории окажется одной датой. Отбор поверх страницы, прочитанной «по дате
слива», после этого начнёт систематически терять проверки, а выглядеть будет
обычным списком. По той же причине и порядок выдачи — по дате ОБХОДА точки:
одинаковый `pushed_at` не упорядочивает ничего.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from src.domain.tenants import canonical_tenant

from .errors import DbError, StorageError
from .models import (
    FindingRow,
    InfoRow,
    InspectionDetail,
    InspectionRow,
    ItemUsage,
    PreviousInspection,
)
from .reach import Reach
from .reach import require_reach as _require_reach
from .reading import reading as _reading
from .units import normalize_unit_name

#: Сколько строк отдаётся, если предел не назвали. Сотня — это и есть
#: «история точки глазами человека»: больше за один запрос не читают ни в
#: отчёте, ни через агента, а безграничная выдача на сети из сотен пиццерий
#: означает вычитать всю таблицу по случайному вопросу.
DEFAULT_LIMIT = 100

#: Потолок, выше которого предел перестаёт быть пределом. Без него
#: `limit=10_000_000` — тот же полный проход, только записанный так, будто
#: ограничение есть.
MAX_LIMIT = 1000

# Запросы печатают свой список колонок целиком (не собирают его из общего куска
# строкой): динамическая сборка текста SQL — ровно то, что ловит S608, и здесь
# ей взяться неоткуда не по обещанию, а по устройству кода.
#
# Точка присоединяется по одному `id` (волна 1, #340, D284): справочник один, и
# проверка партнёра ссылается на точку справочника УК. Граница чтения — условие
# охвата `REACH_SQL` (`src/db/reach.py`), вписанное в каждый запрос литералом;
# что оно есть везде, сверяет `tests/test_db_reach_static.py`. Партнёр видит
# пиццерии своих стран, кто бы их ни проверял (D289), УК — всю сеть (D283).
#
# Границы периода стоят в запросе ВСЕГДА, а не дописываются в текст по
# необходимости: незаданная граница — это `-infinity`/`infinity`, то есть
# отсутствие ограничения, записанное данными. Так текст запроса остаётся одним
# и тем же независимо от аргументов, а его план — проверяемым.
_LIST_ALL_TEMPLATE = """
select
    i.id, i.tenant_code, u.name, i.chat_id, i.kind, i.inspection_date,
    i.report_lang, i.checklist_version, i.pct, i.grade,
    (select count(*) from findings f where f.inspection_id = i.id),
    -- Город: записанный в проверке, а пустой — город пиццерии из справочника
    -- кодом (#460): мастер бота города больше не спрашивает (D233).
    i.pushed_at, i.auditor, coalesce(nullif(i.city, ''), u.city, ''), i.partner, i.contact,
    i.retracted_at, i.retraction_reason,
    -- В КОНЕЦ, а не в середину (T345): разбор строки позиционный, и вставка
    -- между колонками сдвинула бы всё правее неё молча.
    i.checklist_code,
    -- Этап приёмки (D199, 0034) — тоже в конец и по той же причине.
    i.status, i.accepted_at, i.accepted_by
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
  and __STAGE__
order by i.inspection_date desc, i.pushed_at desc
limit %(limit)s
"""

# Фильтр по точке — по нормализованному названию в пределах охвата. Справочник
# один (D284), поэтому одноимённых точек у двух пространств больше не заводится;
# прежние собственные точки партнёров, если такие есть, охват УК видит рядом с
# точками справочника — и одноимённые склеились бы в одну историю.
_LIST_BY_UNIT_TEMPLATE = """
select
    i.id, i.tenant_code, u.name, i.chat_id, i.kind, i.inspection_date,
    i.report_lang, i.checklist_version, i.pct, i.grade,
    (select count(*) from findings f where f.inspection_id = i.id),
    -- Город: записанный в проверке, а пустой — город пиццерии из справочника
    -- кодом (#460): мастер бота города больше не спрашивает (D233).
    i.pushed_at, i.auditor, coalesce(nullif(i.city, ''), u.city, ''), i.partner, i.contact,
    i.retracted_at, i.retraction_reason,
    -- В КОНЕЦ, а не в середину (T345): разбор строки позиционный, и вставка
    -- между колонками сдвинула бы всё правее неё молча.
    i.checklist_code,
    -- Этап приёмки (D199, 0034) — тоже в конец и по той же причине.
    i.status, i.accepted_at, i.accepted_by
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and u.name_normalized = %(unit)s
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
  and __STAGE__
order by i.inspection_date desc, i.pushed_at desc
limit %(limit)s
"""

# Этап — ОТДЕЛЬНЫМ текстом запроса, а не параметром (`(status = 'draft') =
# %(on_review)s`): условие с параметром планировщик не сопоставит с частичным
# индексом очереди `inspections_on_review_queue` (0034), и очередь из единиц
# строк читалась бы через всю историю. История — принятые, очередь — ждущие.
_HISTORY_STAGE = "i.status = 'finalized'"
_QUEUE_STAGE = "i.status = 'draft'"
_LIST_ALL_SQL = _LIST_ALL_TEMPLATE.replace("__STAGE__", _HISTORY_STAGE)
_QUEUE_ALL_SQL = _LIST_ALL_TEMPLATE.replace("__STAGE__", _QUEUE_STAGE)
_LIST_BY_UNIT_SQL = _LIST_BY_UNIT_TEMPLATE.replace("__STAGE__", _HISTORY_STAGE)
_QUEUE_BY_UNIT_SQL = _LIST_BY_UNIT_TEMPLATE.replace("__STAGE__", _QUEUE_STAGE)

# Проверка целиком: та же шапка плюс разбивка оценки, которой в списке нет.
# Числа отдаются как лежат — ни одного действия над ними.
_GET_INSPECTION_SQL = """
select
    i.id, i.tenant_code, u.name, i.chat_id, i.kind, i.inspection_date,
    i.report_lang, i.checklist_version, i.pct, i.grade,
    (select count(*) from findings f where f.inspection_id = i.id),
    -- Город: записанный в проверке, а пустой — город пиццерии из справочника
    -- кодом (#460): мастер бота города больше не спрашивает (D233).
    i.pushed_at, i.auditor, coalesce(nullif(i.city, ''), u.city, ''), i.partner, i.contact,
    i.retracted_at, i.retraction_reason,
    -- В КОНЕЦ, а не в середину (T345): разбор строки позиционный, и вставка
    -- между колонками сдвинула бы всё правее неё молча.
    i.checklist_code,
    i.status, i.accepted_at, i.accepted_by,
    i.deductions, i.counts, i.by_zone
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.id = %(id)s
  and (%(include_on_review)s or i.status = 'finalized')
"""

# Формулировки лежат строками `(entity_type, entity_id, field, lang)` (D025) и
# берутся на языке речи ТОЙ проверки, в которой находка записана, а не на
# языке, выбранном этим слоем. Подзапросы идут по первичному ключу таблицы
# переводов, поэтому это точечное чтение, а не N+1.
#
# Арендатор здесь не проверяется намеренно: находки берутся у проверки, которую
# `get_inspection` уже сверил с охватом, а принадлежать другой проверке
# находка не может — это внешний ключ. Второй заслон поверх первого нельзя было
# бы снять и увидеть красное, то есть проверить его работу стало бы нечем.
_FINDINGS_OF_INSPECTION_SQL = """
select
    f.id, f.inspection_id, u.name, i.inspection_date, f.n, f.code, f.level,
    f.zone, f.zone_unusual, f.source, f.words, i.speech_lang,
    f.suggested_code, f.suggested_level, f.suggested_zone, f.suggested_confidence,
    (select t.text from translations t
      where t.entity_type = 'finding' and t.entity_id = f.id
        and t.field = 'text' and t.lang = i.speech_lang),
    (select t.text from translations t
      where t.entity_type = 'finding' and t.entity_id = f.id
        and t.field = 'comment' and t.lang = i.speech_lang),
    f.repeat
from findings f
join inspections i on i.id = f.inspection_id
join units u on u.id = i.unit_id
where f.inspection_id = %(id)s
order by f.n
"""

# Находки одной точки через все её проверки, свежие проверки впереди. Здесь
# охват — единственный заслон, и он проверяется снятием (тест на утечку).
_FINDINGS_BY_UNIT_SQL = """
select
    f.id, f.inspection_id, u.name, i.inspection_date, f.n, f.code, f.level,
    f.zone, f.zone_unusual, f.source, f.words, i.speech_lang,
    f.suggested_code, f.suggested_level, f.suggested_zone, f.suggested_confidence,
    (select t.text from translations t
      where t.entity_type = 'finding' and t.entity_id = f.id
        and t.field = 'text' and t.lang = i.speech_lang),
    (select t.text from translations t
      where t.entity_type = 'finding' and t.entity_id = f.id
        and t.field = 'comment' and t.lang = i.speech_lang),
    f.repeat
from findings f
join inspections i on i.id = f.inspection_id
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and u.name_normalized = %(unit)s
  and i.status = 'finalized'
order by i.inspection_date desc, i.pushed_at desc, f.n
limit %(limit)s
"""

# Информационная часть проверки (T200) — в ЗАПИСАННОМ порядке, а не по коду.
# Движок печатает поля в том порядке, в каком их записали, и это порядок
# разделов документа партнёру: `order by code` переставил бы их при первой же
# правке порядка вопросов, а заметить это можно было бы только сличением двух
# бумаг. Арендатор здесь не проверяется по той же причине, что у находок: поля
# берутся у проверки, которую `get_inspection` уже сверил с охватом.
_INFO_OF_INSPECTION_SQL = """
select code, text
from inspection_info
where inspection_id = %(id)s
order by position
"""


def _detail_parts(
    колонки: dict[str, int], row: Any
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    """Разбивка оценки из строки карточки — по именам колонок, а не по их номерам.

    Позиционный разбор здесь уже ломался молча: колонка, приписанная в конец
    списка (`checklist_code`, T345), сдвинула разбивку на единицу, и карточка
    проверки перестала читаться вовсе — разбором, а не понятным отказом. Номер
    колонки знает только тот, кто держит в голове весь `select`; имя знает
    драйвер.

    Отсутствие колонки — отказ, а не ноль: разбивка уезжает в документ
    партнёру, и нулевые вычеты в нём выглядят как безупречная проверка.
    """
    недостающие = [имя for имя in ("deductions", "counts", "by_zone") if имя not in колонки]
    if недостающие:
        raise StorageError(
            f"В ответе базы нет колонок разбивки оценки: {', '.join(недостающие)}. "
            f"Карточка проверки без них — это документ партнёру с пустыми вычетами"
        )
    return (
        float(row[колонки["deductions"]]),
        dict(row[колонки["counts"]]),
        dict(row[колонки["by_zone"]]),
    )


def _row_to_inspection(row: Any) -> InspectionRow:
    """Строка курсора → `InspectionRow`.

    Тип строки психкопг не даёт статически по позиции колонки — `row: Any`
    здесь ровно на этой границе, а не расползается по модулю: дальше в коде
    типы снова конкретные.
    """
    return InspectionRow(
        id=str(row[0]),
        tenant_code=str(row[1]),
        unit_name=str(row[2]),
        chat_id=int(row[3]),
        kind=str(row[4]),
        inspection_date=row[5],
        report_lang=str(row[6]),
        checklist_version=str(row[7]),
        pct=float(row[8]),
        grade=str(row[9]),
        findings_count=int(row[10]),
        pushed_at=row[11].isoformat(),
        # Шапка письма (T176). Колонки объявлены `not null default ''`, но
        # `or ""` здесь не украшение: историю за прошлые годы зальют программно
        # из чужой выгрузки (D035), и `None` в подписи письма партнёру
        # напечатался бы словом «None».
        auditor=str(row[12] or ""),
        city=str(row[13] or ""),
        partner=str(row[14] or ""),
        contact=str(row[15] or ""),
        # Пометка снятия (T210, T233). Обычной роли снятая проверка не видна
        # вовсе — её прячет построчная политика, а не эти строки, — поэтому у
        # обычного чтения оба поля всегда пусты. Заполненными они приходят
        # только администратору истории (`include_retracted=True`), и он видит
        # проверку ИМЕННО как снятую, а не как обычную.
        retracted=row[16] is not None,
        retraction_reason=str(row[17] or ""),
        # Код чек-листа приезжает последним и потому не двигает ничего выше
        # (T345). `or "bizdev"` — для строк, залитых до миграции программно:
        # пустой код у записанной проверки означал бы «не знаем, по чему
        # проверяли», а такого состояния у неё не бывает.
        checklist_code=str(row[18] or "bizdev"),
        # Этап приёмки (D199): `draft` теперь не миг внутри транзакции слива, а
        # проверка, ждущая вычитки. Принятые до появления этапа отметки о
        # приёмке не имеют — пустая строка, а не выдуманное время.
        on_review=row[19] == "draft",
        accepted_at=row[20].isoformat() if row[20] is not None else "",
        accepted_by=str(row[21] or ""),
    )


def _row_to_finding(row: Any) -> FindingRow:
    """Строка курсора → `FindingRow`. Порядок колонок — как в запросах выше.

    `source` склеивает NULL и пустую строку: и то, и другое означает «источник
    не записан», и двух разных видов у этого не бывает. Так же склеены и слова
    аудитора (T185): «слов не записано» тоже не бывает двух видов, а «их не было
    вовсе» от «запись сделана до T183» отличает как раз `source`. Формулировка и
    комментарий, наоборот, остаются `None`, когда строки перевода нет вовсе:
    подменённые пустой строкой, они стали бы неотличимы от «аудитор ничего не
    написал».
    """
    return FindingRow(
        id=str(row[0]),
        inspection_id=str(row[1]),
        unit_name=str(row[2]),
        inspection_date=row[3],
        n=int(row[4]),
        code=str(row[5]),
        level=str(row[6]),
        zone=str(row[7]),
        zone_unusual=bool(row[8]),
        source=str(row[9] or ""),
        # Сырые слова аудитора (T185) отдаются дословно — обрезка здесь меняла
        # бы показание о моменте, по которому управляющая компания сверяет
        # промах модели. На языке `lang` ниже: своего языка у них нет, они
        # сказаны на языке речи той проверки, в которой записаны.
        words=str(row[10] or ""),
        lang=str(row[11]),
        # Предложение модели (T164). `None` во всех четырёх — модель не
        # предлагала ничего; пустая строка сюда не доезжает, её склеивает с
        # `None` ещё слив. Уверенность приходит из `numeric` десятичной дробью
        # (`Decimal`), и `float` здесь — не округление, а приведение к тому же
        # типу, которым её отдал распознаватель.
        suggested_code=row[12],
        suggested_level=row[13],
        suggested_zone=row[14],
        suggested_confidence=None if row[15] is None else float(row[15]),
        text=row[16],
        comment=row[17],
        # Пометка повтора (#359). Умолчание колонки — `false`, то есть «не
        # отмечено»: у записанной проверки состояния «неизвестно, был ли
        # повтор» не бывает.
        repeat=bool(row[18]),
    )


def _require_tenant(tenant: str) -> str:
    """Непустой код арендатора — или явный отказ.

    Пустая строка не совпала бы ни с одним `tenant_code` и вернула бы пустой
    список: ошибка вызывающего выглядела бы как «проверок нет». Это худший из
    исходов — он не чинится, потому что его никто не замечает.
    """
    code = canonical_tenant(tenant or "")
    if not code:
        raise DbError(
            "Не задан арендатор, чьи проверки читаем. Выборка без него отдала бы "
            "либо чужие проверки, либо пустоту вместо ошибки — оба исхода тихие"
        )
    return code


def _require_limit(limit: int) -> int:
    """Предел выдачи в осмысленных границах — или явный отказ."""
    if limit < 1 or limit > MAX_LIMIT:
        raise DbError(
            f"Предел выдачи {limit} вне допустимого: ожидается от 1 до {MAX_LIMIT}. "
            f"Ноль вернул бы пустоту вместо отказа, а число сверху — тот же полный "
            f"проход по таблице под видом ограничения"
        )
    return limit


def _require_unit(unit: str) -> str:
    """Непустое название точки — или явный отказ.

    Пустое название вернуло бы пустой список нарушений, то есть «у этой точки
    всё хорошо» вместо «вы не назвали точку».
    """
    name = (unit or "").strip()
    if not name:
        raise DbError(
            "Не названа точка, чьи находки читаем. Пустое название вернуло бы пустой "
            "список нарушений вместо отказа — а такой ответ никто не перепроверит"
        )
    return name


def _require_window(date_from: date | None, date_to: date | None) -> None:
    """Границы периода в правильном порядке — или явный отказ.

    Перевёрнутый период не совпадёт ни с одной проверкой и вернёт пустой
    список: перепутанные местами границы выглядели бы как «за этот период
    проверок не было».
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise DbError(
            f"Перевёрнутый период: начало {date_from.isoformat()} позже конца "
            f"{date_to.isoformat()}. Такой период вернул бы пустоту вместо ошибки"
        )


def _require_inspection_id(inspection_id: str) -> str:
    """Идентификатор проверки — или явный отказ, а не «не найдено».

    Кривой идентификатор и несуществующий — разные вещи: первое ошибка
    вызывающего, второе законный ответ. Слитые в одно «проверка не найдена»,
    они прячут опечатку в аргументе за правдоподобным ответом.
    """
    raw = (inspection_id or "").strip()
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise DbError(
            f"«{inspection_id}» не похоже на идентификатор проверки (ожидается UUID). "
            f"Ответ «такой проверки нет» здесь скрыл бы опечатку в запросе"
        ) from exc


def list_inspections(
    *,
    reach: Reach,
    unit: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = DEFAULT_LIMIT,
    include_retracted: bool = False,
    on_review: bool = False,
    city: str = "",
    country: str = "",
    grade: str = "",
) -> list[InspectionRow]:
    """Проверки в охвате читающего, свежие по дате обхода — первыми.

    `reach` обязателен и значения по умолчанию не имеет намеренно (T110):
    подстановка «вся сеть» выглядела бы работающей ровно до первого партнёра,
    а потом отдала бы агенту партнёра A историю партнёра B.

    `unit` фильтрует по точному названию точки в пределах того же охвата
    (по тому же правилу нормализации, что и слив). Карту синонимов (T092) эта
    выборка не спрашивает: «БГ2» здесь не найдёт проверок «Белград 2» — при
    появлении потребителя это отдельная работа, а не молчаливое расширение.

    `date_from`/`date_to` — период по дате ОБХОДА точки, обе границы
    включительно, любая может быть опущена. Отбор идёт в базе, а не поверх
    прочитанной страницы: после программной заливки истории (D035) дата слива
    у всей истории одна, и «первая страница по дате слива» перестаёт быть
    связана с периодом вовсе.

    `limit` ограничивает выдачу всегда: без предела один вопрос агента
    вычитывал бы всю историю сети.

    `include_retracted` — это не фильтр, а другая РОЛЬ: снятые проверки (T210,
    D089) прячет построчная политика, и обычному чтению их не видно вовсе.
    `True` уводит запрос на подключение администратора истории
    (`DATABASE_RETRACTION_URL`), и тогда в выдаче появляются снятые — помеченные
    как снятые, с причиной. Не задано подключение — отказ, а не тихая выдача
    без них: «снятых нет» и «вам их не видно» разные ответы.

    `on_review` выбирает ОДНУ из двух очередей, а не расширяет выдачу (D199):
    по умолчанию — только принятые, то есть история сети; `True` — только
    ждущие вычитки. Смешанной выдачи нет намеренно: проверка до подтверждения
    не часть истории, и реестр показывает её отдельным списком.

    `city`/`country`/`grade` — отбор по месту и букве В БАЗЕ, до предела (#470),
    по тем же правилам, что у агрегатов (`_narrowing`): пусто — «все». Отбор
    поверх прочитанной страницы терял бы проверки среза старше `limit`-й по
    всей сети, и экран показывал бы другое множество, чем соседние блоки.
    """
    охват = _require_reach(reach)
    rows_limit = _require_limit(limit)
    _require_window(date_from, date_to)
    params: dict[str, object] = {
        **охват.params(),
        "limit": rows_limit,
        "date_from": date_from,
        "date_to": date_to,
        **_narrowing(city, country, grade),
    }
    with (
        _reading("список проверок", as_admin=include_retracted) as conn,
        conn.cursor() as cur,
    ):
        if unit is None:
            cur.execute(_QUEUE_ALL_SQL if on_review else _LIST_ALL_SQL, params)
        else:
            cur.execute(
                _QUEUE_BY_UNIT_SQL if on_review else _LIST_BY_UNIT_SQL,
                {**params, "unit": normalize_unit_name(unit)},
            )
        rows = cur.fetchall()
    return [_row_to_inspection(row) for row in rows]


def get_inspection(
    inspection_id: str,
    *,
    reach: Reach,
    include_retracted: bool = False,
    include_on_review: bool = False,
) -> InspectionDetail | None:
    """Одна проверка из охвата читающего целиком: шапка, разбивка оценки и находки.

    `None` — проверки нет либо она вне охвата. Это один и
    тот же ответ намеренно: «такой проверки нет» и «такая проверка есть, но не
    ваша» — второе подтверждало бы существование чужого документа тому, кто
    перебирает идентификаторы.

    Оценка не пересчитывается: `pct`, `grade`, `deductions`, `counts` и
    `by_zone` отдаются ровно такими, какими их положил движок при завершении
    проверки (конституция, принцип 2).

    `include_retracted` работает так же, как у списка: это не фильтр, а
    подключение администратора истории. Без него снятая проверка отвечает
    `None` — тем же ответом, что несуществующая, и это не небрежность: тому,
    кто снятых не видит, они и не существуют.

    Проверка на приёмке (D199) по умолчанию отвечает `None` тем же ответом:
    до подтверждения она не документ сети, и агент или аналитика не должны
    выдать её за таковой. Экран приёмки просит её явно — `include_on_review`.
    """
    охват = _require_reach(reach)
    ident = _require_inspection_id(inspection_id)
    with (
        _reading("проверку по идентификатору", as_admin=include_retracted) as conn,
        conn.cursor() as cur,
    ):
        return _read_detail(cur, reach=охват, ident=ident, include_on_review=include_on_review)


def _read_detail(
    cur: Any, *, reach: Reach, ident: str, include_on_review: bool
) -> InspectionDetail | None:
    """Проверка целиком на ЧУЖОМ курсоре — внутри транзакции вызывающего.

    Нужна правке на приёмке (D200): она читает записи и пересчитывает оценку
    после того, как взяла замок проверки, в той же транзакции. Иначе две
    правки одной проверки считали бы каждая от своего снимка (`src/db/revise.py`).

    Внутренняя намеренно: записи и сведения читаются по идентификатору БЕЗ
    охвата — только после того, как карточка отобрана по охвату. Вызывающих
    ровно два, `get_inspection` и `revise._apply` (после замка своего
    пространства); список держит `tests/test_db_reach_static.py`.
    """
    cur.execute(
        _GET_INSPECTION_SQL,
        {**reach.params(), "id": ident, "include_on_review": include_on_review},
    )
    row = cur.fetchone()
    колонки = {опис.name: место for место, опис in enumerate(cur.description or ())}
    if row is None:
        return None
    # Находки читаются тем же соединением и в той же транзакции: между
    # двумя подключениями проверка могла бы измениться, и шапка разъехалась
    # бы с телом документа.
    cur.execute(_FINDINGS_OF_INSPECTION_SQL, {"id": ident})
    findings = cur.fetchall()
    # Информационная часть — тем же соединением и той же транзакцией, по
    # той же причине: собранный заново документ обязан быть одним
    # документом, а не шапкой одной проверки и сроком другой.
    cur.execute(_INFO_OF_INSPECTION_SQL, {"id": ident})
    info = cur.fetchall()
    # Разбивка берётся ПО ИМЕНИ колонки, а не по её номеру. Номер здесь уже
    # ломался молча: приписка `checklist_code` в конец списка колонок (T345)
    # сдвинула разбивку на единицу, и чтение карточки стало падать разбором
    # «could not convert string to float: 'bizdev'». Имена отдаёт сам драйвер
    # (`cur.description`), поэтому следующая приписка ничего не сдвинет.
    deductions, counts, by_zone = _detail_parts(колонки, row)
    return InspectionDetail(
        inspection=_row_to_inspection(row),
        deductions=deductions,
        counts=counts,
        by_zone=by_zone,
        findings=tuple(_row_to_finding(строка) for строка in findings),
        info=tuple(InfoRow(code=str(строка[0]), text=str(строка[1])) for строка in info),
    )


def findings_by_unit(*, reach: Reach, unit: str, limit: int = DEFAULT_LIMIT) -> list[FindingRow]:
    """Находки одной точки по всем её проверкам, свежие проверки — первыми.

    Отвечает на вопрос «что у этой пиццерии повторяется», но сам повтор здесь
    не считается: отдаётся ряд записанных находок, а обобщает спрашивающий.
    Выведенное тут число («нарушение повторилось четыре раза») никто не
    записывал, а в ответе агента оно немедленно пошло бы как факт проверки.

    Охват обязателен по той же причине, что и у списка проверок, и здесь
    он единственный заслон: находки достаются через проверки, своей ссылки на
    пространство у них нет.

    Находок СНЯТОЙ проверки эта выборка не отдаёт никому, и флага «показать
    снятые» у неё нет намеренно. Спрашивают её об одном — что у точки
    повторяется, — и снятая проверка это ровно то, чему в таком ответе не
    место: отозванный документ, посчитанный за повтор, превращается в
    требование к партнёру по основанию, которого больше нет.
    """
    охват = _require_reach(reach)
    name = _require_unit(unit)
    rows_limit = _require_limit(limit)
    with _reading("находки точки") as conn, conn.cursor() as cur:
        cur.execute(
            _FINDINGS_BY_UNIT_SQL,
            {**охват.params(), "unit": normalize_unit_name(name), "limit": rows_limit},
        )
        rows = cur.fetchall()
    return [_row_to_finding(row) for row in rows]


# ─── Сводка по сети: агрегаты, а не чтение карточек по одной ────────────────
#
# Экран «Обзор» (T354) показывает сеть целиком: где она теряет проценты, какие
# пункты нарушаются на многих точках, какие точки проблемные. Собирать это из
# карточек нельзя: на 390 точках это 390 запросов на один экран, а данные уже
# лежат в форме, пригодной для группировки.
#
# ОЦЕНКА ЗДЕСЬ НЕ СЧИТАЕТСЯ. Запросы складывают то, что движок УЖЕ записал:
# `by_zone` разложен им при завершении проверки, `pct` и `grade` взяты оттуда
# же. Ни процента, ни буквы, ни вычета эти запросы не выводят.


def _narrowing(city: str, country: str, grade: str) -> dict[str, str | None]:
    """Отбор для агрегатов: пустое значение становится NULL, то есть «все».

    Разница принципиальная. Пустая строка, доехав до запроса как значение,
    сравнивалась бы с городом и не совпала бы ни с одной строкой — экран
    показал бы пустоту и не сказал, почему. NULL в условии
    `%(city)s::text is null or u.city = %(city)s` отключает сужение целиком.
    """
    return {
        "city": city or None,
        "country": country or None,
        "grade": grade or None,
    }


_ZONE_LOSSES_SQL = """
select
    zone.key as code,
    max(zone.value ->> 'name_ru') as name_ru,
    max(zone.value ->> 'name_en') as name_en,
    sum((zone.value ->> 'loss')::numeric) as loss,
    count(distinct i.id) as inspections,
    count(distinct i.unit_id) as units
from inspections i
     join units u on u.id = i.unit_id
     cross join lateral jsonb_each(i.by_zone) as zone
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.status = 'finalized'
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
  and jsonb_typeof(zone.value) = 'object'
  and (zone.value ->> 'loss') is not null
group by zone.key
order by loss desc, zone.key
limit %(limit)s
"""

# Формулировка берётся из САМОЙ СВЕЖЕЙ записи этого пункта, а не из методики:
# экран сводит проверки разных изданий, и одной формулировки пункта у них нет,
# а перевод пункта живёт в хранилище методики, куда веб за этим не ходит. Текст
# при этом — на языке РЕЧИ той проверки, где он записан (конституция, принцип
# языков), поэтому язык возвращается рядом с ним и печатается у текста.
_SYSTEMIC_SQL = """
with записи as (
    select
        f.code,
        f.level,
        i.unit_id,
        i.inspection_date,
        i.speech_lang,
        (select t.text from translations t
          where t.entity_type = 'finding' and t.entity_id = f.id
            and t.field = 'text' and t.lang = i.speech_lang) as text
    from findings f
         join inspections i on i.id = f.inspection_id
         join units u on u.id = i.unit_id
    where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
      and (%(countries)s::text[] is null or u.country = any(%(countries)s))
      and i.status = 'finalized'
      and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
      and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
),
свежие as (
    select distinct on (code, level) code, level, text, speech_lang
    from записи
    where text is not null and text <> ''
    order by code, level, inspection_date desc
)
select
    записи.code,
    записи.level,
    count(*) as records,
    count(distinct записи.unit_id) as units,
    coalesce(max(свежие.text), '') as text,
    coalesce(max(свежие.speech_lang), '') as lang
from записи
     left join свежие on свежие.code = записи.code and свежие.level = записи.level
group by записи.code, записи.level
order by units desc, records desc, записи.code
limit %(limit)s
"""

# Сводка среза для плиток (#503): сколько проверок, сколько точек, буквы и
# сумма процентов — по ВСЕМУ срезу, а не по прочитанному ряду с пределом. Числа
# движка складываются, но не выводятся: процент и буква взяты такими, какими он
# их записал. Разбивка по изданию нужна, чтобы потребитель решил, законно ли
# усреднять срез (T349): разные цены не усредняются.
_SLICE_SUMMARY_SQL = """
with срез as (
    select i.unit_id, i.checklist_code, i.checklist_version, i.grade, i.pct
    from inspections i
         join units u on u.id = i.unit_id
    where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
      and (%(countries)s::text[] is null or u.country = any(%(countries)s))
      and i.status = 'finalized'
      and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
      and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
)
select
    coalesce(checklist_code, ''), checklist_version, grade, count(*), sum(pct),
    (select count(distinct unit_id) from срез)
from срез
group by 1, 2, 3
order by 1, 2, 3
"""

_UNITS_TOTAL_SQL = """
select count(*) from units u
where u.tenant_code = 'HQ'
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


def zone_losses(
    *,
    reach: Reach,
    date_from: date | None = None,
    date_to: date | None = None,
    city: str = "",
    country: str = "",
    grade: str = "",
    limit: int = DEFAULT_LIMIT,
) -> list[tuple[str, str, str, float, int, int]]:
    """Потери по зонам: `(код, имя ru, имя en, вычет, проверок, точек)`.

    Имя зоны берётся из того же снимка `by_zone`, а не из нынешней методики:
    проверка заморожена вместе с формулировками своей версии, и подпись из
    сегодняшнего справочника подменила бы название, под которым зону смотрели.

    Вычет берётся из `by_zone`, куда его положил движок, и только сложением.
    Зона, у которой в снимке нет числа вычета, в ответ не попадает: нулём её
    подменять нельзя — «зона без потерь» и «зона, про которую эта проверка
    ничего не записала» на экране читаются одинаково, а значат разное.
    """
    охват = _require_reach(reach)
    _require_window(date_from, date_to)
    with _reading("потери по зонам") as conn, conn.cursor() as cur:
        cur.execute(
            _ZONE_LOSSES_SQL,
            {
                **охват.params(),
                "date_from": date_from,
                "date_to": date_to,
                "limit": _require_limit(limit),
                # Пустая строка означает «не сужать» и приходит в запрос как
                # NULL: условие `%(city)s::text is null or ...` тогда истинно
                # для всех строк. Пустую строку сравнивать с городом нельзя —
                # она отсекла бы всё, молча и целиком.
                **_narrowing(city, country, grade),
            },
        )
        return [
            (str(code), str(ru or code), str(en or code), float(loss), int(insp), int(units))
            for code, ru, en, loss, insp, units in cur.fetchall()
        ]


def systemic_findings(
    *,
    reach: Reach,
    date_from: date | None = None,
    date_to: date | None = None,
    city: str = "",
    country: str = "",
    grade: str = "",
    limit: int = DEFAULT_LIMIT,
) -> list[tuple[str, str, int, int, str, str]]:
    """Нарушения по пунктам: `(код, класс, записей, точек, формулировка, язык)`.

    Порядок — по числу ТОЧЕК, а не записей: один пункт, нарушенный на двадцати
    точках, — это методика или обучение, а двадцать записей по одному пункту на
    одной точке — это одна точка. Сортировка по записям смешала бы эти случаи.
    """
    охват = _require_reach(reach)
    _require_window(date_from, date_to)
    with _reading("нарушения по пунктам") as conn, conn.cursor() as cur:
        cur.execute(
            _SYSTEMIC_SQL,
            {
                **охват.params(),
                "date_from": date_from,
                "date_to": date_to,
                "limit": _require_limit(limit),
                # Пустая строка означает «не сужать» и приходит в запрос как
                # NULL: условие `%(city)s::text is null or ...` тогда истинно
                # для всех строк. Пустую строку сравнивать с городом нельзя —
                # она отсекла бы всё, молча и целиком.
                **_narrowing(city, country, grade),
            },
        )
        return [
            (str(code), str(level), int(records), int(units), str(text or ""), str(lang or ""))
            for code, level, records, units, text, lang in cur.fetchall()
        ]


def slice_summary(
    *,
    reach: Reach,
    date_from: date | None = None,
    date_to: date | None = None,
    city: str = "",
    country: str = "",
    grade: str = "",
) -> tuple[int, list[tuple[str, str, str, int, float]]]:
    """Сводка среза без предела: `(точек, [(код чек-листа, издание, буква, проверок, сумма %)])`.

    Ряд проверок экрана ограничен пределом, а плитки (средняя, буквы, число
    проверок и точек) обязаны говорить о том же множестве, что потери по зонам
    и системные нарушения, — то есть обо всём срезе (#503). Отбор — тот же
    `_narrowing`, охват — тот же.
    """
    охват = _require_reach(reach)
    _require_window(date_from, date_to)
    with _reading("сводка среза") as conn, conn.cursor() as cur:
        cur.execute(
            _SLICE_SUMMARY_SQL,
            {
                **охват.params(),
                "date_from": date_from,
                "date_to": date_to,
                **_narrowing(city, country, grade),
            },
        )
        строки = cur.fetchall()
    точек = int(строки[0][5]) if строки else 0
    return точек, [
        (str(code), str(version), str(буква), int(n), float(сумма))
        for code, version, буква, n, сумма, _ in строки
    ]


def units_total(*, reach: Reach) -> int:
    """Сколько точек справочника в охвате — всего, а не «с проверками».

    Считается отдельно от проверок намеренно: «проверено 12 из 150» и
    «проверено 12» — разные утверждения, и первое возможно только если знать
    знаменатель.
    """
    охват = _require_reach(reach)
    with _reading("число точек") as conn, conn.cursor() as cur:
        cur.execute(_UNITS_TOTAL_SQL, охват.params())
        row = cur.fetchone()
        return int(row[0]) if row else 0


_CLASS_COUNTS_SQL = """
select
    f.inspection_id,
    f.level,
    count(*) as records
from findings f
     join inspections i on i.id = f.inspection_id
     join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.status = 'finalized'
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
group by f.inspection_id, f.level
"""


def class_counts(
    *,
    reach: Reach,
    date_from: date | None = None,
    date_to: date | None = None,
    city: str = "",
    country: str = "",
    grade: str = "",
) -> dict[str, dict[str, int]]:
    """Сколько находок каждого класса в каждой проверке периода.

    Одним запросом на весь период, а не по запросу на проверку: экран сети
    показывает десятки проверок сразу, и чтение по строке превратило бы один
    экран в десятки походов в базу.

    Ответ — словарь `{id проверки: {класс: число}}`. Проверка без находок в нём
    отсутствует, и это честнее нулей: «находок не заводили» и «находок нет»
    различаются, а ноль их бы склеил. Потребитель читает через `.get`.
    """
    охват = _require_reach(reach)
    _require_window(date_from, date_to)
    with _reading("счётчики классов") as conn, conn.cursor() as cur:
        cur.execute(
            _CLASS_COUNTS_SQL,
            {
                **охват.params(),
                "date_from": date_from,
                "date_to": date_to,
                **_narrowing(city, country, grade),
            },
        )
        счёт: dict[str, dict[str, int]] = {}
        for inspection_id, level, records in cur.fetchall():
            счёт.setdefault(str(inspection_id), {})[str(level)] = int(records)
        return счёт


_UNIT_GEOGRAPHY_SQL = """
select u.name, u.country, u.city
from units u
where u.tenant_code = 'HQ'
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


_UNIT_IDS_SQL = """
select u.name, u.id
from units u
where u.tenant_code = 'HQ'
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


_PREVIOUS_INSPECTION_SQL = """
with прошлая as (
    select i.id, i.inspection_date
    from inspections i
    join units u on u.id = i.unit_id
    where i.tenant_code = %(tenant)s
      and u.name = %(unit)s
      and i.retracted_at is null
    order by i.inspection_date desc, i.pushed_at desc
    limit 1
)
select прошлая.inspection_date, f.code
from прошлая
left join findings f on f.inspection_id = прошлая.id and f.level <> 'D0'
"""


def previous_inspection(*, tenant: str, unit: str) -> PreviousInspection | None:
    """Предыдущая проверка точки и её нарушения — основа вопроса о повторе.

    Отдаётся ровно факт: когда был прошлый обход и какие пункты тогда были
    записаны нарушениями. Вывод «значит это повтор» здесь не делается и сделан
    быть не может — тот же код мог относиться к другому объекту, а исправленное
    и снова сломавшееся отличается от неисправленного. Решение о цене принимает
    проверяющий (D191, D255: «конечное решение принимал проверяющий»).

    Предыдущая — одна, последняя по дате обхода: правило говорит про
    предыдущую проверку, а не «когда-нибудь за год». Снятые проверки в счёт не
    идут: снятая проверка не является показанием о точке. Информационные
    записи (`D0`) нарушениями не считаются и в коды не попадают.

    `None` — прошлых проверок нет либо точка чужая. Для вопроса это одно и то
    же: спрашивать не о чем.
    """
    tenant_code = _require_tenant(tenant)
    with _reading("предыдущая проверка точки") as conn, conn.cursor() as cur:
        cur.execute(_PREVIOUS_INSPECTION_SQL, {"tenant": tenant_code, "unit": _require_unit(unit)})
        rows = cur.fetchall()
    if not rows:
        return None
    return PreviousInspection(
        date=rows[0][0], codes=frozenset(str(код) for _, код in rows if код is not None)
    )


def unit_ids(*, reach: Reach) -> dict[str, str]:
    """Идентификаторы точек справочника: `{название: id}`.

    Нужны экранам, чтобы ссылаться на точку идентификатором, а не названием:
    название правят и переводят, и ссылка, собранная из него, ломается молча
    (CLAUDE.md, «сущности связывать кодами, никогда формулировками»).
    """
    охват = _require_reach(reach)
    with _reading("идентификаторы точек") as conn, conn.cursor() as cur:
        cur.execute(_UNIT_IDS_SQL, охват.params())
        return {str(name): str(ид) for name, ид in cur.fetchall()}


def unit_geography(*, reach: Reach) -> dict[str, tuple[str, str]]:
    """География точек справочника: `{название: (код страны, город)}`.

    География берётся у ТОЧКИ, а не у проверки. Город в проверке — то, что
    ввёл аудитор в поле шапки, и он пишется свободной строкой; город точки
    ведётся справочником и переживает опечатку в одной проверке. Срез сети по
    городу, собранный из шапок, разъехался бы на «Belgrade» и «Белград».

    Страна кодом, город строкой — как в базе (0017) и по той же причине:
    формулировки переводятся, коды нет.
    """
    охват = _require_reach(reach)
    with _reading("география точек") as conn, conn.cursor() as cur:
        cur.execute(_UNIT_GEOGRAPHY_SQL, охват.params())
        return {
            str(name): (str(country or ""), str(city or ""))
            for name, country, city in cur.fetchall()
        }


_WORST_ZONES_SQL = """
select distinct on (i.id)
    i.id,
    zone.key as code,
    zone.value ->> 'name_ru' as name_ru,
    zone.value ->> 'name_en' as name_en,
    (zone.value ->> 'loss')::numeric as loss
from inspections i
     join units u on u.id = i.unit_id
     cross join lateral jsonb_each(i.by_zone) as zone
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.status = 'finalized'
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and (%(city)s::text is null or u.city = %(city)s)
  and (%(country)s::text is null or u.country = %(country)s)
  and (%(grade)s::text is null or i.grade = %(grade)s)
  and jsonb_typeof(zone.value) = 'object'
  and (zone.value ->> 'loss') is not null
order by i.id, (zone.value ->> 'loss')::numeric desc, zone.key
"""


def worst_zones(
    *,
    reach: Reach,
    date_from: date | None = None,
    date_to: date | None = None,
    city: str = "",
    country: str = "",
    grade: str = "",
) -> dict[str, tuple[str, str, str, float]]:
    """Самая дорогая зона каждой проверки: `{id: (код, имя ru, имя en, вычет)}`.

    Имя зоны — из снимка самой проверки, а не из нынешней методики: проверка
    заморожена вместе со своими формулировками, и подпись из сегодняшнего
    справочника подменила бы название, под которым зону смотрели.

    Зона выбирается по НАИБОЛЬШЕМУ вычету, а не по числу находок: экран
    отвечает на вопрос «где потеряно больше всего процентов», и три мелких
    замечания в одной зоне не перевешивают одного дорогого в другой.
    """
    охват = _require_reach(reach)
    _require_window(date_from, date_to)
    with _reading("слабая зона проверки") as conn, conn.cursor() as cur:
        cur.execute(
            _WORST_ZONES_SQL,
            {
                **охват.params(),
                "date_from": date_from,
                "date_to": date_to,
                **_narrowing(city, country, grade),
            },
        )
        return {
            str(inspection_id): (str(code), str(ru or ""), str(en or ""), float(loss))
            for inspection_id, code, ru, en, loss in cur.fetchall()
        }


#: Сколько точек показывать в сводке пункта: больше — уже список, а не ответ.
ITEM_USAGE_TOP = 5

#: Записи пункта — только из СДАННЫХ и НЕОТКЛОНЁННЫХ проверок своего чек-листа.
#: Отклонённые роли приложения не видны и по политике (0010), но условие стоит
#: и здесь: запрос не должен становиться неверным оттого, под какой ролью его
#: однажды позовут. Код пункта принадлежит своему чек-листу: `CLN01` двух
#: чек-листов — разные пункты.
_ITEM_RECORDS = """
    from findings f
         join inspections i on i.id = f.inspection_id
         join units u on u.id = i.unit_id
    where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
      and (%(countries)s::text[] is null or u.country = any(%(countries)s))
      and f.code = %(code)s
      and i.checklist_code = %(checklist)s
      and i.status = 'finalized'
      and i.retracted_at is null
"""

_ITEM_SUMMARY_SQL = (
    "select count(*), count(distinct i.unit_id), count(distinct i.id), max(i.inspection_date)"
    + _ITEM_RECORDS
)
_ITEM_LEVELS_SQL = "select f.level, count(*)" + _ITEM_RECORDS + " group by f.level order by f.level"
_ITEM_TOP_SQL = (
    "select u.name, u.id, count(*) as records"
    + _ITEM_RECORDS
    + " group by u.name, u.id order by records desc, u.name limit %(limit)s"
)


#: С какого дня сборка чек-листа в работе — день первой проверки по ней (D218).
#: Неизданная сборка (`local-…`) своей даты не несёт нигде, и человеку номер
#: сборки ничего не говорит; день первой проверки — говорит. Снятые не в счёт:
#: для того, кто их не видит, их не было.
_EDITION_FIRST_USED_SQL = """
select min(i.inspection_date)
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.status = 'finalized'
  and i.checklist_version = %(version)s
  and i.retracted_at is null
"""


def edition_first_used(*, reach: Reach, version: str) -> date | None:
    """День первой проверки по этой сборке чек-листа; `None` — проверок нет."""
    охват = _require_reach(reach)
    with _reading("первую проверку по сборке") as conn, conn.cursor() as cur:
        cur.execute(_EDITION_FIRST_USED_SQL, {**охват.params(), "version": version.strip()})
        row = cur.fetchone()
    return row[0] if row else None


def item_usage(*, reach: Reach, code: str, checklist: str) -> ItemUsage:
    """Сколько раз пункт нарушен, на скольких точках и когда последний раз (D197)."""
    охват = _require_reach(reach)
    код = code.strip().upper()
    параметры: dict[str, object] = {
        **охват.params(),
        "code": код,
        "checklist": checklist.strip(),
        "limit": ITEM_USAGE_TOP,
    }
    with _reading("сводка пункта") as conn, conn.cursor() as cur:
        cur.execute(_ITEM_SUMMARY_SQL, параметры)
        записей, точек, проверок, последняя = cur.fetchone() or (0, 0, 0, None)
        cur.execute(_ITEM_LEVELS_SQL, параметры)
        по_классам = tuple((str(level), int(n)) for level, n in cur.fetchall())
        cur.execute(_ITEM_TOP_SQL, параметры)
        частые = tuple((str(name), str(ид), int(n)) for name, ид, n in cur.fetchall())
    return ItemUsage(
        code=код,
        records=int(записей),
        units=int(точек),
        inspections=int(проверок),
        last_date=последняя,
        by_level=по_классам,
        top_units=частые,
    )
