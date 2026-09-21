"""T336 (#317): готовый отчёт проверки уезжает в хранилище.

PDF собирается при завершении и уходит аудитору в чат. Дальше он не живёт
нигде: показать его в админке нечем, ответить «что именно получил партнёр»
нечем, а через год не будет и самого чата. Кадры эту дорогу уже прошли
(`photos.py`, T094) — отчёт идёт той же и теми же дверями.

Байты сюда приносит вызывающий, а не берёт этот модуль сам, и причина та же,
что у кадров: собранный отчёт лежит рядом с ботом, а границы модулей
запрещают блоку `db` знать про блок `bot`.

Повторная выгрузка одного и того же отчёта не заводит вторую строку: у файла
считается отпечаток, и отчёт с тем же отпечатком признаётся уже записанным.
Иначе кнопка «прислать ещё раз» плодила бы копии одного документа, а вопрос
«что получил партнёр» получал бы несколько одинаковых ответов.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import psycopg

from .config import check_environment, load_storage_settings
from .errors import PushError
from .storage import PhotoStorage, S3PhotoStorage

#: Чем отдаётся отчёт. Записывается в базу, а не угадывается при выдаче:
#: документ партнёру, открытый браузером как текст, — это ровно то, что
#: получается из типа, угаданного по расширению.
REPORT_CONTENT_TYPE = "application/pdf"

_SELECT_EXISTING_SQL = """
select id, storage_path
from reports
where inspection_id = %s and storage_path = %s
limit 1
"""

_INSERT_REPORT_SQL = """
insert into reports (inspection_id, storage_path, content_type, size_bytes)
values (%(inspection_id)s, %(storage_path)s, %(content_type)s, %(size_bytes)s)
returning id
"""

_SELECT_INSPECTION_SQL = "select 1 from inspections where id = %s"


@dataclass(frozen=True)
class StoredReport:
    """Куда лёг отчёт и был ли он там уже."""

    storage_path: str
    size_bytes: int
    #: Отчёт с таким же содержимым уже лежал: ничего не записано и не потрачено.
    already: bool


def report_object_key(inspection_id: str, digest: str) -> str:
    """Ключ отчёта в хранилище — только из идентификаторов.

    Ни названия точки, ни даты, ни имени аудитора: сущности связываются кодами
    (конституция, принцип 5), а названия точек партнёров коммерчески
    чувствительны и в имени файла им не место.

    Отпечаток в имени, а не порядковый номер: он делает ключ повторяемым, и
    повторная выгрузка того же файла попадает в тот же объект, а не в новый.
    """
    return f"inspections/{inspection_id}/reports/{digest}.pdf"


def upload_report(
    inspection_id: str,
    *,
    data: bytes,
    storage: PhotoStorage | None = None,
    content_type: str = REPORT_CONTENT_TYPE,
) -> StoredReport:
    """Положить готовый отчёт в хранилище и записать ссылку на него.

    Пустые байты — отказ, а не пустой объект: отчёт нулевого размера выглядит
    в истории как сохранённый документ и обнаруживается ровно тогда, когда его
    открывает человек.

    `storage` подменяется только проверками; в работе драйвер собирается из
    окружения (`S3_*`), как и у кадров.
    """
    if not data:
        raise PushError("Отчёт не сохранён: пришли пустые байты, а не документ")

    settings = check_environment()
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())

    digest = hashlib.sha256(data).hexdigest()[:32]
    key = report_object_key(inspection_id, digest)

    with psycopg.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_INSPECTION_SQL, (inspection_id,))
            if cur.fetchone() is None:
                raise PushError(f"Проверки {inspection_id} нет в истории — отчёту не к чему лечь")

        # Сначала СКЛАДЫВАЕМ файл, потом пишем строку. Обратный порядок оставил
        # бы в базе ссылку на объект, которого нет, — и админка отвечала бы
        # отказом на документ, который история считает сохранённым.
        uri = store.put(key, data, content_type=content_type)

        with conn.cursor() as cur:
            cur.execute(_SELECT_EXISTING_SQL, (inspection_id, uri))
            if cur.fetchone() is not None:
                # Тот же файл уже записан. Объект перезаписан теми же байтами —
                # это не потеря: ключ считается от содержимого, значит там ровно
                # то же самое.
                return StoredReport(storage_path=uri, size_bytes=len(data), already=True)

            cur.execute(
                _INSERT_REPORT_SQL,
                {
                    "inspection_id": inspection_id,
                    "storage_path": uri,
                    "content_type": content_type,
                    "size_bytes": len(data),
                },
            )
        conn.commit()

    return StoredReport(storage_path=uri, size_bytes=len(data), already=False)
