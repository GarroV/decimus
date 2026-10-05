"""Сверка хранилища файлов с таблицами: экшн-планы и ответы на предписания (#496).

Версия экшн-плана и файл ответа на предписание кладутся в хранилище ДО
транзакции (`action_plans.upload_version`, `prescriptions_write.reply`):
заливка до 25 МБ не держит ни соединение, ни замок. Строка не легла — объект
убирается тут же. Но если процесс умер между заливкой и коммитом или уборка
не прошла, объект остаётся без строки; при сетевом обрыве на самом коммите
возможно обратное — строка есть, а объекта нет. Эта сверка такие случаи
называет и НИЧЕГО не удаляет: что делать с найденным, решает человек.

Три вида расхождений:

* **объект без строки** — файл в хранилище, на который не ссылается ни одна
  строка таблицы. Партнёр его не видит, место он занимает;
* **строка без объекта** — версия видна в истории, а скачать её нельзя;
* **ссылка не разбирается** — строка ссылается не в форме `s3://корзина/ключ`
  или мимо своего префикса. Проверять такой объект нечем, и выдавать её за
  «строку без объекта» было бы неправдой.

Объект без строки моложе порога (`grace`) расхождением не считается: это
загрузка, идущая в эту минуту. Он показывается отдельно, чтобы не пропасть.

Строки читаются ДО списка объектов: строка коммитится только после того, как
её объект лёг, поэтому строка, прочитанная раньше списка, обязана найти свой
объект в списке. Обратный порядок давал бы ложную «строку без объекта» на
любой загрузке, совпавшей со сверкой.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import psycopg

from .action_plans import STORAGE_PREFIX as ACTION_PLANS_PREFIX
from .config import check_environment, load_storage_settings
from .errors import StorageError
from .prescriptions_write import STORAGE_PREFIX as PRESCRIPTIONS_PREFIX
from .storage import S3PhotoStorage, StoredObject, key_of_uri

#: Сколько ждать, прежде чем объект без строки считать расхождением. Загрузка
#: файла и коммит строки занимают секунды; 10 минут — тот же запас, что у
#: дозагрузки кадров (`src/bot/photo_backfill.py`).
DEFAULT_GRACE = timedelta(minutes=10)


@dataclass(frozen=True)
class Area:
    """Участок сверки: префикс в хранилище и строки, которые на него ссылаются."""

    name: str
    prefix: str
    #: Запрос отдаёт `(id, storage_path)` только строк с файлом.
    sql: str


AREAS: tuple[Area, ...] = (
    Area(
        name="action-plans",
        prefix=f"{ACTION_PLANS_PREFIX}/",
        sql="select id::text, storage_path from action_plan_files order by uploaded_at, id",
    ),
    Area(
        name="prescriptions",
        prefix=f"{PRESCRIPTIONS_PREFIX}/",
        # Ответ без файла — законный ответ, ему в хранилище быть нечему.
        sql=(
            "select id::text, storage_path from prescription_replies "
            "where storage_path is not null order by replied_at, id"
        ),
    ),
)


@dataclass(frozen=True)
class StoredRow:
    """Строка таблицы, ссылающаяся на файл."""

    id: str
    storage_path: str


@dataclass(frozen=True)
class AreaReport:
    """Итог сверки одного участка."""

    area: str
    prefix: str
    objects: int
    rows: int
    matched: int
    orphan_objects: tuple[StoredObject, ...]
    missing_objects: tuple[StoredRow, ...]
    bad_links: tuple[StoredRow, ...]
    fresh_skipped: tuple[StoredObject, ...]

    @property
    def discrepancies(self) -> int:
        return len(self.orphan_objects) + len(self.missing_objects) + len(self.bad_links)

    @property
    def clean(self) -> bool:
        return self.discrepancies == 0


def _key_in_area(row: StoredRow, prefix: str) -> str | None:
    """Ключ строки, если ссылка разбирается и лежит под префиксом участка."""
    try:
        key = key_of_uri(row.storage_path)
    except StorageError:
        return None
    return key if key.startswith(prefix) else None


def classify(
    prefix: str,
    *,
    objects: Iterable[StoredObject],
    rows: Iterable[StoredRow],
    now: datetime,
    grace: timedelta,
) -> AreaReport:
    """Разложить объекты и строки участка по видам расхождений. Ничего не трогает."""
    по_ключу = {obj.key: obj for obj in objects}
    строки = tuple(rows)
    ключи_строк: set[str] = set()
    missing: list[StoredRow] = []
    bad: list[StoredRow] = []
    for row in строки:
        key = _key_in_area(row, prefix)
        if key is None:
            bad.append(row)
            continue
        ключи_строк.add(key)
        if key not in по_ключу:
            missing.append(row)
    без_строки = [obj for key, obj in sorted(по_ключу.items()) if key not in ключи_строк]
    return AreaReport(
        area="",
        prefix=prefix,
        objects=len(по_ключу),
        rows=len(строки),
        matched=sum(1 for key in ключи_строк if key in по_ключу),
        orphan_objects=tuple(o for o in без_строки if now - o.modified >= grace),
        missing_objects=tuple(missing),
        bad_links=tuple(bad),
        fresh_skipped=tuple(o for o in без_строки if now - o.modified < grace),
    )


def reconcile(
    areas: Sequence[Area],
    *,
    read_rows: Callable[[Area], Sequence[StoredRow]],
    list_objects: Callable[[str], Sequence[StoredObject]],
    now: datetime,
    grace: timedelta = DEFAULT_GRACE,
) -> tuple[AreaReport, ...]:
    """Сверить участки по очереди. Отказ базы или хранилища летит наружу как есть."""
    итоги: list[AreaReport] = []
    for area in areas:
        rows = read_rows(area)  # строки — до списка, см. описание модуля
        objects = list_objects(area.prefix)
        итог = classify(area.prefix, objects=objects, rows=rows, now=now, grace=grace)
        итоги.append(replace(итог, area=area.name))
    return tuple(итоги)


def reconcile_live(
    areas: Sequence[Area] = AREAS, *, grace: timedelta = DEFAULT_GRACE
) -> tuple[AreaReport, ...]:
    """Сверка с настоящими базой и хранилищем из окружения — только чтение.

    База — под ролью приложения (`DATABASE_URL`): у неё есть `select` на обе
    таблицы, а политика строк открыта (`using (true)`), так что видно всё.
    Сессия объявлена только для чтения: записать что-либо сверка не может даже
    по ошибке. Хранилище — тем же доступом `S3_*`, что у продукта; из него
    сверка только читает список.
    """
    store = S3PhotoStorage(load_storage_settings())
    with psycopg.connect(check_environment().dsn) as conn:
        conn.set_read_only(True)

        def read_rows(area: Area) -> list[StoredRow]:
            with conn.cursor() as cur:
                cur.execute(area.sql)  # запрос из AREAS, без подстановок
                return [StoredRow(id=str(r[0]), storage_path=str(r[1])) for r in cur.fetchall()]

        return reconcile(
            areas,
            read_rows=read_rows,
            list_objects=store.list_prefix,
            now=datetime.now(UTC),
            grace=grace,
        )
