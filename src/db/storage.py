"""Хранилище кадров за S3-совместимым интерфейсом (D004, D054).

Зачем прослойка, а не прямой вызов клиента из места записи: хранилище на этом
проекте заведомо переедет. Сегодня это локальный S3-совместимый сервер, завтра
Supabase Storage, послезавтра что-то ещё (D054: хранилище рано или поздно
сменится). Привязываться к конкретному поставщику нельзя (D061), а
S3-совместимый интерфейс есть у всех перечисленных — поэтому смена хранилища
обязана стоить правки переменных окружения, и ничего больше.

Клиент — `boto3`: он говорит с любым S3-совместимым сервером через
`endpoint_url` и сам переключается на path-style адресацию, когда адрес не
похож на AWS (иначе имя корзины уехало бы в поддомен, которого у локального
сервера нет). Проверено фактически, а не по документации: тесты блока гоняют
запись и чтение через выставленный `endpoint_url`.

Ключ объекта собирается **только из идентификаторов** — проверки и кадра.
Ни названия точки, ни даты, ни формулировки находки в нём нет: во-первых,
сущности связываются кодами (конституция, принцип 5), во-вторых, названия
точек партнёров коммерчески чувствительны и в имени файла им не место.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .errors import StorageError

if TYPE_CHECKING:  # pragma: no cover — только для проверки типов
    from mypy_boto3_s3.client import S3Client

#: Кадры приходят из телеграма фотографиями и уже лежат на диске джипегами
#: (`src/bot/photos.py` сохраняет их как `photo-NNN.jpg`). Отдельного разбора
#: формата здесь нет намеренно: угадывать тип по байтам ради поля, у которого
#: одно значение, — работа без потребителя.
PHOTO_CONTENT_TYPE = "image/jpeg"  # кадр, не читаемый Pillow, кладётся как пришёл

#: Сколько ждать соединения с хранилищем и сколько раз пробовать — ТОЛЬКО на
#: пути сдачи и дозагрузки (`S3PhotoStorage(..., fail_fast=True)`, #459).
#: Остальные читатели и писатели (админка, снятие, предписания, экшн-планы,
#: MCP, доливщик копий) идут с умолчаниями botocore и их повторами: там человек
#: сам нажал кнопку, отказ ему виден, а потерять запись из-за одной неудачной
#: попытки хуже, чем подождать.
#:
#: Умолчания `botocore` — 60 секунд на соединение и пять попыток — рассчитаны на
#: облако, а не на хранилище, которое спит (D259: MUSPELHEIM засыпает и сам не
#: просыпается). Спящий узел tailnet на соединение не отвечает вовсе, и каждая
#: попытка дожидается полного срока: на сдаче это минуты, а бот обрабатывает
#: сообщения по одному (`handle_as_tasks=False`) — стояли бы все аудиторы.
#: Короткий срок ничего не теряет: невыгруженный кадр остаётся в базе с пустой
#: ссылкой, и его доливает дозагрузка (`src/bot/photo_backfill.py`).
CONNECT_TIMEOUT_SEC = 5
#: Ожидание ответа уже соединившегося хранилища. Кадр — сотни килобайт, отчёт —
#: единицы мегабайт; полминуты тишины от живого сервера — уже отказ.
READ_TIMEOUT_SEC = 30
#: Всего попыток, включая первую (`total_max_attempts`, режим `standard`).
#: Одна, без повтора: мгновенный сбой покроет дозагрузка — кадр не потеряется.
#: Ключ именно `total_max_attempts`: `max_attempts` у botocore считает ПОВТОРЫ,
#: и `max_attempts=1` давал две попытки (поймано тестом на `meta.config`).
#: Замер 05.10.2026 на адресе, который не отвечает: одна попытка — 5,0 с,
#: две — 10,4 с; умолчания botocore — 309 с.
MAX_ATTEMPTS = 1


@dataclass(frozen=True)
class StorageSettings:
    """Куда складывать кадры. Всё — из окружения, ничего не зашито."""

    bucket: str
    access_key_id: str
    secret_access_key: str
    #: Пусто — значит настоящий AWS S3. Для любого другого поставщика адрес
    #: задаётся явно, и именно он делает переезд правкой конфига.
    endpoint_url: str | None = None
    region: str = "us-east-1"


class PhotoStorage(Protocol):
    """То немногое, что блоку нужно от хранилища.

    Узко намеренно: чем меньше поверхность, тем дешевле второй драйвер. Всё,
    что не реализуемо одинаково у всех поставщиков, сюда не попадает.
    """

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        """Положить объект и вернуть ссылку на него в хранилище.

        Отказ — `StorageError`: перевод исключений поставщика делает драйвер,
        а не тот, кто его зовёт.
        """

    def delete(self, key: str) -> None:
        """Убрать объект из хранилища.

        Нужен снятию проверки: кадры снятой проверки из хранилища убираются
        (D089). Отсутствующий объект — не отказ: уборка повторяема, и
        повторный проход по уже убранному кадру обязан быть тихим, иначе
        оборвавшаяся на середине уборка не доделывается вовсе.

        Отказ — `StorageError`, как и у `put`.
        """


def object_key(inspection_id: str, photo_id: str) -> str:
    """Путь объекта: только идентификаторы, ничего из формулировок и названий."""
    return f"inspections/{inspection_id}/{photo_id}.jpg"


#: Начало ссылки в хранилище (`S3PhotoStorage.put`).
_URI_PREFIX = "s3://"


def key_of_uri(storage_path: str) -> str:
    """Ключ объекта из ссылки `s3://корзина/ключ`. Не та форма — отказ, а не догадка.

    Корзина из ссылки не берётся: её называет конфигурация (`S3_BUCKET`), и
    переезд хранилища — правка окружения, а не каждой строки (D054).
    """
    хвост = storage_path[len(_URI_PREFIX) :] if storage_path.startswith(_URI_PREFIX) else ""
    if "/" not in хвост:
        raise StorageError(f"Ссылка не в форме s3://корзина/ключ: {storage_path}")
    return хвост.split("/", 1)[1]


def preview_key(inspection_id: str, photo_id: str) -> str:
    """Ключ отдельной сжатой копии кадра (D219), выгруженного ДО D253.

    Новые кадры отдельной копии не имеют: `photos.storage_path` и `preview_path`
    указывают на один объект по `object_key`. Этот ключ нужен только для кадров
    старой выгрузки (оригинал + копия) и для доливщика `tools/backfill_previews.py`.
    """
    return f"inspections/{inspection_id}/previews/{photo_id}.jpg"


class S3PhotoStorage:
    """Драйвер поверх S3-совместимого API.

    Клиент создаётся один раз на объект: `boto3.client` разбирает описание
    сервиса из JSON и на каждый кадр это платить незачем.
    """

    def __init__(self, settings: StorageSettings, *, fail_fast: bool = False) -> None:
        """`fail_fast=True` — короткий срок и одна попытка (путь сдачи и дозагрузки, #459)."""
        import boto3
        from botocore.config import Config

        self._bucket = settings.bucket
        config = (
            Config(
                connect_timeout=CONNECT_TIMEOUT_SEC,
                read_timeout=READ_TIMEOUT_SEC,
                retries={"total_max_attempts": MAX_ATTEMPTS, "mode": "standard"},
            )
            if fail_fast
            else None
        )
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url or None,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name=settings.region,
            config=config,
        )

    @property
    def endpoint_url(self) -> str:
        """Фактический адрес, с которым разговаривает клиент. Нужен проверкам."""
        return str(self._client.meta.endpoint_url)

    def put(self, key: str, data: bytes, *, content_type: str = PHOTO_CONTENT_TYPE) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            # Перевод на границе драйвера: наружу уходит отказ блока, а не
            # исключение конкретного поставщика. Иначе вызывающему пришлось бы
            # знать про boto3, и смена хранилища перестала бы быть правкой
            # конфига. Имя корзины в тексте есть, ключей доступа — нет.
            raise StorageError(
                f"Хранилище не приняло объект {key} в корзину {self._bucket} "
                f"({type(exc).__name__}): {exc}"
            ) from exc
        # Ссылка в каноничной форме `s3://корзина/ключ`, а не подписанный URL:
        # подписанный протухает через считанные часы, и в базе он снова стал бы
        # мёртвой ссылкой — ровно той бедой, ради которой затевалась задача.
        # Открытая ссылка для человека собирается по этой из конфигурации
        # хранилища в момент показа, а не хранится.
        return f"s3://{self._bucket}/{key}"

    def delete(self, key: str) -> None:
        """Убрать объект. Отсутствующего объекта достаточно, чтобы считать дело сделанным.

        `delete_object` у S3 идемпотентен по устройству протокола: удаление
        того, чего нет, отвечает успехом. Это здесь не мирятся с чужим
        поведением, а пользуются им — уборка кадров идёт по одному объекту за
        раз, и повторный проход после обрыва обязан доделать остаток, а не
        упереться в первый уже убранный кадр.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(
                f"Хранилище не убрало объект {key} из корзины {self._bucket} "
                f"({type(exc).__name__}): {exc}"
            ) from exc

    def get(self, key: str) -> bytes:
        """Прочитать объект целиком — для выдачи отчёта из админки (D204).

        Отсутствующий объект здесь — отказ, а не пустые байты: строка в
        `reports` пишется только после того, как файл лёг (`upload_report`),
        значит пропажа объекта — поломка хранилища, и человек должен узнать
        об этом словами, а не получить пустой документ.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            ответ = self._client.get_object(Bucket=self._bucket, Key=key)
            return ответ["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(
                f"Хранилище не отдало объект {key} из корзины {self._bucket} "
                f"({type(exc).__name__}): {exc}"
            ) from exc
