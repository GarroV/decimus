"""T094: выгрузка кадров проверки в хранилище.

`telegram_file_id` живёт ровно столько, сколько живёт бот с этим токеном, и
снаружи не открывается вовсе: в базе он становится мёртвой ссылкой на
доказательство, ради которого проверка и делалась. Поэтому при завершении
кадры уезжают в S3-совместимое хранилище (D054), а в строке кадра появляется
ссылка, которая работает независимо от телеграма.

Байты сюда приносит вызывающий, а не берёт этот модуль сам, и это не мелочь
устройства: токен телеграма есть только у бота (`src/bot/photos.py`), а
границы модулей запрещают блоку `db` знать про блок `bot` — импорт наверх
роняет прогон. Тот же приём уже применён в сборке отчёта: `report.build_pdf`
принимает готовую карту «ссылка → файл», а не угадывает её сам.

Оригинал кадра не хранится (D250, D253): в хранилище лежит только сжатая
копия, чёткая настолько, чтобы по кадру было видно, что где и какие проблемы.

Пропавший кадр не проходит молча. Выгрузка, вернувшая «успех» с половиной
кадров, оставила бы в базе часть ссылок мёртвыми навсегда и никому об этом не
сказала — а именно от этого задача и заводилась.

Хранилище может лежать в момент сдачи (D259: оно на MUSPELHEIM, а тот
засыпает). Тогда кадр не теряется: строка остаётся с пустым `storage_path`,
вызывающий получает `PhotosDeferredError`, а потом кадр доливает дозагрузка —
`pending_photo_uploads` называет, что ждёт, бот качает байты у телеграма и
зовёт ту же `upload_photos` (#459).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment, load_storage_settings
from .errors import PhotosDeferredError, PushError, StorageError
from .previews import PREVIEW_CONTENT_TYPE, make_preview
from .storage import PHOTO_CONTENT_TYPE, PhotoStorage, S3PhotoStorage, object_key

logger = logging.getLogger(__name__)

#: Кто умеет достать байты кадра по его идентификатору в телеграме. `None` —
#: кадра больше нет; это не исключение, а обычный исход (файл протух, телеграм
#: не отдал), и решение о нём принимается на уровне выше.
FetchPhoto = Callable[[str], bytes | None]

_SELECT_PENDING_SQL = """
select id, telegram_file_id
from photos
where inspection_id = %s and storage_path is null
order by created_at, id
"""

#: `storage_path is null` в условии — не перестраховка. Сдача и дозагрузка могут
#: взять один кадр одновременно; объект ляжет дважды по тому же ключу (ключ из
#: идентификаторов, байты те же), а ссылку запишет тот, кто успел первым.
#: Второй получит ноль строк и не посчитает кадр своим (#459).
_MARK_UPLOADED_SQL = """
update photos set storage_path = %s, preview_path = %s, uploaded_at = now()
where id = %s and storage_path is null
"""

#: Невыгруженные кадры всех видимых проверок. Убранные (`purged_at`) не берутся:
#: их объект снят намеренно. Снятые проверки роль приложения не видит вовсе
#: (`photos_follow_visible_inspection`), значит и их кадры сюда не попадут.
#: Свежие — не раньше `min_age_sec`: их, скорее всего, прямо сейчас выгружает
#: сама сдача с байтами на руках, и качать их у телеграма второй раз незачем.
#: Застарелые — старше `max_age_sec`, если он задан, — в обычный проход не
#: идут: кадр, который телеграм не отдаёт неделями, иначе вечно занимал бы
#: место в выборке (ревью #514).
_SELECT_ALL_PENDING_SQL = """
select inspection_id, telegram_file_id, created_at
from photos
where storage_path is null and purged_at is null
  and created_at < now() - make_interval(secs => %(min_age)s)
  and (%(max_age)s::float8 is null or created_at >= now() - make_interval(secs => %(max_age)s))
order by created_at, id
limit %(limit)s
"""

_INSPECTION_EXISTS_SQL = "select 1 from inspections where id = %s"


@dataclass(frozen=True)
class PendingUpload:
    """Проверка, у которой есть кадры без ссылки в хранилище (#459)."""

    inspection_id: str
    #: Идентификаторы телеграма без повторов, в порядке поступления.
    file_ids: tuple[str, ...]
    #: С какого момента ждёт самый старый из этих кадров.
    waiting_since: datetime


#: Сколько кадров брать за один проход дозагрузки. Остаток возьмёт следующий.
PENDING_BATCH = 1000


def pending_photo_uploads(
    *, min_age_sec: int, max_age_sec: int | None = None, limit: int = PENDING_BATCH
) -> list[PendingUpload]:
    """Какие кадры ещё не легли в хранилище — по проверкам (#459).

    Читает только базу: хранилище здесь не трогается, поэтому ответ есть и
    тогда, когда оно лежит, — и это ровно тот момент, когда он нужен.
    `max_age_sec` отрезает застарелые кадры (у них свой, редкий проход).
    """
    settings = check_environment()
    params = {"min_age": min_age_sec, "max_age": max_age_sec, "limit": limit}
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_SELECT_ALL_PENDING_SQL, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise PushError(
            f"Список невыгруженных кадров не прочитан ({type(exc).__name__}): {exc}"
        ) from exc
    by_inspection: dict[str, dict[str, None]] = {}
    since: dict[str, datetime] = {}
    for inspection_id, file_id, created_at in rows:
        key = str(inspection_id)
        by_inspection.setdefault(key, {})[str(file_id)] = None
        since.setdefault(key, created_at)  # строки идут по возрастанию времени
    return [PendingUpload(key, tuple(ids), since[key]) for key, ids in by_inspection.items()]


def _require_inspection(conn: psycopg.Connection[Any], inspection_id: str) -> None:
    """Проверки нет — это отказ, а не «выгружено ноль кадров».

    Ноль здесь неотличим от честного нуля у проверки без единого кадра, и
    вызывающий записал бы себе успех там, где ошибся идентификатором.
    """
    with conn.cursor() as cur:
        cur.execute(_INSPECTION_EXISTS_SQL, (inspection_id,))
        if cur.fetchone() is None:
            raise PushError(
                f"В базе нет проверки {inspection_id} — выгружать кадры некуда и незачем"
            )


def _put_photo(
    store: PhotoStorage, inspection_id: str, photo_id: str, data: bytes
) -> tuple[str, str | None]:
    """Положить кадр в хранилище одним объектом и вернуть `(storage_path, preview_path)`.

    Оригинал не хранится (D250, D253): в хранилище уходит только сжатая копия
    (D219), и обе ссылки в строке кадра указывают на этот один объект, поэтому
    любой читатель — показ в админке, снятие проверки — находит его по своей
    колонке и ничего не знает про изменение.

    Кадр, который не читается как изображение, копии не получает, а оригинала
    больше нет как страховки: выбросить его значило бы потерять доказательство.
    Поэтому он уезжает как есть, `preview_path` остаётся пустым (показывать
    нечего, как и раньше), и это сказано в лог, а не проглочено молча.
    Отказ самого хранилища — отказ выгрузки.

    Кладётся ДО записи строки: после неё строка заморожена
    (`photos_uploaded_only_once`), и дописать ссылку было бы уже нельзя.
    """
    key = object_key(inspection_id, photo_id)
    try:
        копия = make_preview(data)
    except StorageError as exc:
        logger.warning(
            "кадр %s проверки %s не читается как изображение, лёг как есть: %s",
            photo_id,
            inspection_id,
            exc,
        )
        return store.put(key, data, content_type=PHOTO_CONTENT_TYPE), None
    uri = store.put(key, копия, content_type=PREVIEW_CONTENT_TYPE)
    return uri, uri


def upload_photos(
    inspection_id: str,
    *,
    fetch: FetchPhoto,
    storage: PhotoStorage | None = None,
    allow_missing: bool = False,
) -> int:
    """Выгрузить кадры проверки в хранилище и вернуть, сколько выгружено.

    Повторяемо и доливаемо: берутся только те кадры, у которых ссылки в
    хранилище ещё нет (`storage_path is null`), и каждая ссылка фиксируется
    своей транзакцией. Поэтому обрыв на середине не откатывает уже выгруженное,
    а повторный вызов доделывает остаток и не платит за то же дважды.

    `fetch` возвращает байты кадра по его идентификатору в телеграме или
    `None`, если кадра больше нет. Хотя бы один такой кадр — отказ `PushError`
    с перечислением потерянных: часть ссылок иначе осталась бы мёртвой, и никто
    бы об этом не узнал. Залить остальное намеренно — `allow_missing=True`,
    и тогда это осознанное решение вызывающего, а не случайность.

    `storage` подменяется только проверками; в работе драйвер собирается из
    окружения (`S3_*`), и площадка хранилища живёт там же, где площадка базы —
    в переменных, а не в коде.
    """
    settings = check_environment()
    store = (
        storage if storage is not None else S3PhotoStorage(load_storage_settings(), fail_fast=True)
    )

    uploaded = 0
    missing: list[str] = []
    try:
        with psycopg.connect(settings.dsn) as conn:
            _require_inspection(conn, inspection_id)
            with conn.cursor() as cur:
                cur.execute(_SELECT_PENDING_SQL, (inspection_id,))
                pending = cur.fetchall()

            for photo_id, file_id in pending:
                data = fetch(file_id)
                if data is None:
                    missing.append(str(file_id))
                    continue
                uri, preview_uri = _put_photo(store, inspection_id, str(photo_id), data)
                with conn.cursor() as cur:
                    cur.execute(_MARK_UPLOADED_SQL, (uri, preview_uri, photo_id))
                    marked = cur.rowcount
                conn.commit()
                # Ноль строк — кадр уже записал другой выгрузчик (сдача или
                # дозагрузка): объект тот же, ссылка его, считать его своим нельзя.
                uploaded += marked
    except PushError:
        raise
    except psycopg.Error as exc:
        raise PushError(
            f"Выгрузка кадров проверки {inspection_id} не удалась "
            f"({type(exc).__name__}): {exc} Уже выгруженные кадры остались "
            f"выгруженными — повторный вызов доделает остаток"
        ) from exc
    except StorageError as exc:
        # Наружу у блока один тип отказа записи (`PushError`), иначе вызывающему
        # пришлось бы знать про хранилище то, что знать он не должен. Ловится
        # именно `StorageError`, а не `Exception`: широкий перехват подменял бы
        # собой и ошибку в коде вызывающего — настоящая поломка выглядела бы
        # отказом хранилища и молча уходила в «повторим позже».
        raise PhotosDeferredError(
            f"Хранилище не приняло кадр проверки {inspection_id} "
            f"({type(exc).__name__}): {exc} Выгруженные до отказа кадры остались "
            f"выгруженными, остальные ждут дозагрузки"
        ) from exc

    if missing and not allow_missing:
        raise PushError(
            f"Кадры проверки {inspection_id} не удалось получить из телеграма: "
            f"{', '.join(missing)}. Выгружено {uploaded}, остальные ссылки в базе "
            f"остались мёртвыми. Залить проверку без них намеренно — "
            f"upload_photos(..., allow_missing=True)"
        )
    return uploaded
