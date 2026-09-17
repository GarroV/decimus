"""Чтение методики: пункты чек-листа, зоны, допустимые классы, версия набора.

Файлы читаются из `AUDIT_DATA_DIR` при каждом обращении — методику подкладывают
томом снаружи, и кеш в памяти означал бы, что после её замены бот продолжает
работать по старой до перезапуска. Разбор строк повторяет разбор движка (обойти
это нельзя: движок вызывается подпроцессом и своих структур наружу не отдаёт),
но никаких решений о вычетах и классах здесь нет — они остаются в движке.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from . import edition, route, version
from .config import DATA_FILES, Settings, check_environment
from .errors import ConfigError, ValidationError
from .models import ChecklistItem, Zone


def _settings(chat_id: int | None) -> Settings:
    """Окружение чтения: методика ТОЙ проверки, если названа, иначе действующая.

    Проверка идёт по изданию, при котором её начали (T169), и список пунктов
    обязан быть тем же самым: предложи аудитору пункт, которого в его издании
    нет, — и запись по нему движок не примет, а починить это с точки нельзя.

    Чат не назван — действующая методика. Так читают там, где проверки нет
    вовсе: справочники до её начала, инструменты методики, замеры.
    """
    settings = check_environment()
    return settings if chat_id is None else edition.pin(chat_id, settings)


def _text(row: dict[str, str | None], key: str) -> str:
    return (row.get(key) or "").strip()


def _rows(path: Path) -> list[dict[str, str | None]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _days(row: dict[str, str | None], code: str, path: Path, line: int) -> int:
    """Срок устранения пункта. Нечитаемое значение — отказ, а не ноль (T302).

    Нулевой срок печатается партнёру как «устранить немедленно», поэтому движок
    на нечисловой клетке завершается с объяснением (T106). Пока здесь стояла
    молчаливая нормализация в ноль, блок и движок читали один файл и расходились
    в выводе: справочник показывал пункт со сроком «немедленно», а движок
    отказывался считать — и узнавал об этом аудитор на точке.

    Пустая клетка ноль и остаётся: `manage.py add` без `--days` пишет в CSV
    именно пустоту, и запрет сломал бы штатное заведение пункта. Граница
    проходит там же, где у движка.
    """
    raw = _text(row, "days")
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        raise ConfigError(
            f"Срок устранения не число: у пункта «{code}» в колонке days стоит "
            f"«{raw}». Файл: {path}, строка {line}. Поставьте целое число дней — "
            f"иначе срок в предписании партнёру превращается в «немедленно», и "
            f"рядовое нарушение выглядит критическим"
        ) from None


def _item(row: dict[str, str | None], path: Path, line: int) -> ChecklistItem:
    levels = [x.strip().upper() for x in re.split(r"[;,]", _text(row, "levels")) if x.strip()]
    zones = [z.strip() for z in _text(row, "zones").split(",") if z.strip()]
    code = _text(row, "id")
    days = _days(row, code, path, line)
    return ChecklistItem(
        code=code,
        kind=_text(row, "kind") or "violation",
        process_ru=_text(row, "process_ru"),
        process_en=_text(row, "process_en"),
        question_ru=_text(row, "question_ru"),
        question_en=_text(row, "question_en"),
        levels=levels,
        zones=zones,
        days=days,
    )


def _all_items(settings: Settings) -> list[ChecklistItem]:
    path = settings.data_dir / "checklist.csv"
    items: list[ChecklistItem] = []
    seen: dict[str, int] = {}
    # Строка 1 — шапка, поэтому данные начинаются со второй: номер должен
    # совпадать с тем, что покажет управляющей компании её редактор.
    for line, row in enumerate(_rows(path), start=2):
        code = _text(row, "id")
        if not code or code.startswith("#"):
            continue
        # Дубль кода — отказ, как у движка (T106, T302). Пункты связываются
        # кодами, а не формулировками: две строки с одним кодом означают, что в
        # отчёт попадёт не тот вопрос. Раньше здесь брали первую строку и
        # молчали — блок показывал аудитору пункт, по которому движок считать
        # отказывается.
        if code in seen:
            raise ConfigError(
                f"Дубль id в чек-листе: «{code}» встречается в строках "
                f"{seen[code]} и {line}. Файл: {path}. Пункты связываются кодами, "
                f"а не формулировками: две строки с одним кодом означают, что в "
                f"отчёт попадёт не тот вопрос. Оставьте одну строку или смените код"
            )
        seen[code] = line
        items.append(_item(row, path, line))
    # Порядок обхода (T061) — данные: пункты выстраиваются так, как аудитор идёт
    # по точке, а не как строки легли в CSV.
    return route.arrange(
        items, route.load(settings.data_dir).items, lambda i: i.code, what="пункты"
    )


def list_items(
    zone: str | None = None, kind: str | None = None, *, chat_id: int | None = None
) -> list[ChecklistItem]:
    """Пункты чек-листа. `zone` — только применимые к зоне, `kind` — только этого вида.

    Служебные пункты (`aggregate`, `info`) не отфильтрованы намеренно: отсеивать
    их — работа разбора (`docs/03-recording-rules.md`, правило 8), а блоку
    методики не положено решать, что аудитору показывать.

    `chat_id` — читать издание ТОЙ проверки (T169), а не действующую методику.
    """
    settings = _settings(chat_id)
    items = _all_items(settings)
    if zone is not None:
        known = {z.code for z in _zones(settings)}
        if zone not in known:
            raise ValidationError(f"Нет зоны «{zone}». Доступны: {', '.join(sorted(known))}")
        items = [i for i in items if i.applies_to(zone)]
    if kind is not None:
        items = [i for i in items if i.kind == kind]
    return items


def _zones(settings: Settings) -> list[Zone]:
    zones = [
        Zone(
            code=_text(row, "code"),
            title_ru=_text(row, "name_ru"),
            title_en=_text(row, "name_en"),
            share_pct=float(_text(row, "share_pct") or 0),
        )
        for row in _rows(settings.data_dir / "zones.csv")
        if _text(row, "code")
    ]
    return route.arrange(zones, route.load(settings.data_dir).zones, lambda z: z.code, what="зоны")


def list_zones(*, chat_id: int | None = None) -> list[Zone]:
    """Справочник зон с долями. Доли считает движок, здесь они справочно.

    `chat_id` — зоны ТОГО издания, по которому идёт проверка (T169).
    """
    return _zones(_settings(chat_id))


def get_item(code: str, *, chat_id: int | None = None) -> ChecklistItem:
    """Пункт по коду. Неизвестный код — отказ: подобрать похожий блок не вправе.

    `chat_id` — пункт ТОГО издания, по которому идёт проверка (T169).
    """
    settings = _settings(chat_id)
    wanted = code.strip().upper()
    for item in _all_items(settings):
        if item.code == wanted:
            return item
    raise ValidationError(f"Нет пункта «{code}» в чек-листе {settings.data_dir / 'checklist.csv'}")


def allowed_levels(code: str, *, chat_id: int | None = None) -> list[str]:
    """Классы, допустимые для пункта. Список берётся из методики, не из кода.

    `chat_id` — классы ТОГО издания, по которому идёт проверка (T169).
    """
    return list(get_item(code, chat_id=chat_id).levels)


def only_zone(code: str, *, chat_id: int | None = None) -> str | None:
    """Единственная зона, которую методика держит для пункта, — или ничего.

    Это ответ, а не догадка: 59 пунктов из 136 (замер 07.09.2026) живут ровно в
    одной зоне, и для них место находки известно из самого пункта. Задача #218
    оттуда и выросла — зону подставляли памятью о прошлой записи, и пункт про
    печь уезжал в холодный цех, хотя методика держит его только в горячем.

    `None` возвращается в трёх случаях, и все три законны: зон у пункта
    несколько (выводить нечего), зоны заданы как «во всех» (`*` или пусто), или
    такого пункта в методике нет вовсе. Последнее отдельно: неизвестный код —
    не повод падать посреди разговора с аудитором, а повод не выводить зону.

    `chat_id` — издание ТОЙ проверки (T169), как и у соседей по модулю.
    """
    try:
        item = get_item(code, chat_id=chat_id)
    except ValidationError:
        return None
    zones = [zone for zone in item.zones if zone and zone != "*"]
    return zones[0] if len(zones) == 1 else None


def checklist_version() -> str:
    """Версия методики, которая записывается в проверку.

    Составной идентификатор (решение D050): имя набора и дата публикации от
    управляющей компании плюс отпечаток данных. Отпечаток обязателен — без него
    правка методики проходит под прежним именем, и две проверки, посчитанные по
    разным данным, становятся неотличимы. Собирается в `version.compose`.
    """
    settings = check_environment()
    return version.compose(settings.data_dir, DATA_FILES)
