"""T336 (#317): готовый отчёт проверки уезжает в хранилище, в базе остаётся ссылка.

Проверяется не «функция отработала без исключения», а то, ради чего задача
заводилась: в хранилище лежат ТЕ ЖЕ байты, которые получил аудитор, и найти их
можно по тому, что записано в базе.

Формы ссылки здесь НЕТ намеренно, хотя именно на ней держится дешевизна
переезда (D054, D061, D166): ссылку собирает общий слой хранилища, один и тот
же для кадров и отчётов, и проверен он там, где подставлен настоящий
S3-совместимый сервер (`test_db_photos.py`). Проверка формы на двойнике,
который эту форму сам и возвращает, краснела бы только от правки двойника —
то есть не проверяла бы ничего, а выглядела бы проверкой.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import PushError  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.reports import REPORT_CONTENT_TYPE, report_object_key, upload_report  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Белград-1"
КОРЗИНА = "inspection-frames"

#: Не «x»: подменённый на пустышку файл должен отличаться от любого другого,
#: иначе тест «положили тот самый отчёт» прошёл бы и на чужих байтах.
ОТЧЁТ = b"%PDF-1.7\n\xd0\xa2\xd0\xb5\xd1\x81\xd1\x82 report bytes\n%%EOF\n"
ДРУГОЙ_ОТЧЁТ = b"%PDF-1.7\n\xd0\x94\xd1\x80\xd1\x83\xd0\xb3\xd0\xbe\xd0\xb9\n%%EOF\n"


class ЗаписнойСклад:
    """Хранилище-двойник: помнит, что клали и сколько раз."""

    def __init__(self) -> None:
        self.положено: dict[str, bytes] = {}
        self.типы: dict[str, str] = {}
        self.вызовов = 0

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.вызовов += 1
        self.положено[key] = data
        self.типы[key] = content_type
        return f"s3://{КОРЗИНА}/{key}"


def _проверка(chat_id: int) -> str:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(chat_id)


def _строки(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_отчёт_попадает_в_хранилище_а_в_базу_ложится_ссылка_на_него(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(910_001)
    склад = ЗаписнойСклад()

    сохранённый = upload_report(inspection_id, data=ОТЧЁТ, storage=склад)

    # В хранилище — те самые байты, а не «что-то размером с них».
    assert list(склад.положено.values()) == [ОТЧЁТ]
    assert склад.типы[next(iter(склад.положено))] == REPORT_CONTENT_TYPE

    строки = _строки(
        db_env,
        "select storage_path, content_type, size_bytes from reports where inspection_id = %s",
        (inspection_id,),
    )
    assert строки == [(сохранённый.storage_path, REPORT_CONTENT_TYPE, len(ОТЧЁТ))]
    # Записанная ссылка ведёт ровно к тому объекту, который положили.
    ключ = сохранённый.storage_path.removeprefix(f"s3://{КОРЗИНА}/")
    assert склад.положено[ключ] == ОТЧЁТ


def test_ключ_собран_из_идентификаторов_а_не_из_названия_точки(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(910_003)
    склад = ЗаписнойСклад()

    upload_report(inspection_id, data=ОТЧЁТ, storage=склад)

    ключ = next(iter(склад.положено))
    assert ключ.startswith(f"inspections/{inspection_id}/reports/")
    # Названия точек партнёров коммерчески чувствительны, и в имени файла им
    # не место — как и дате, по которой проверку можно опознать.
    assert ТОЧКА not in ключ
    assert ТОЧКА.lower() not in ключ.lower()


def test_повторная_выгрузка_того_же_отчёта_не_заводит_вторую_строку(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(910_004)
    склад = ЗаписнойСклад()

    первый = upload_report(inspection_id, data=ОТЧЁТ, storage=склад)
    второй = upload_report(inspection_id, data=ОТЧЁТ, storage=склад)

    assert первый.storage_path == второй.storage_path
    assert второй.already is True
    assert not первый.already
    # Одна строка, а не две: иначе «прислать ещё раз» плодило бы копии одного
    # документа, и вопрос «что получил партнёр» имел бы несколько ответов.
    assert (
        len(_строки(db_env, "select id from reports where inspection_id = %s", (inspection_id,)))
        == 1
    )


def test_другой_отчёт_той_же_проверки_ложится_отдельной_строкой(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(910_005)
    склад = ЗаписнойСклад()

    upload_report(inspection_id, data=ОТЧЁТ, storage=склад)
    upload_report(inspection_id, data=ДРУГОЙ_ОТЧЁТ, storage=склад)

    # Пересобранный без потерянного кадра отчёт — это ДРУГОЙ документ, и он не
    # затирает первый: обе строки видно, и видно, какая новее.
    строки = _строки(
        db_env,
        "select storage_path from reports where inspection_id = %s order by created_at",
        (inspection_id,),
    )
    assert len(строки) == 2
    assert строки[0] != строки[1]


def test_пустой_отчёт_не_сохраняется_вовсе(domain_env: Path, db_env: str) -> None:
    inspection_id = _проверка(910_006)
    склад = ЗаписнойСклад()

    # Пустой объект в хранилище выглядит как сохранённый документ и
    # обнаруживается ровно тогда, когда его открывает человек.
    with pytest.raises(PushError):
        upload_report(inspection_id, data=b"", storage=склад)

    assert склад.вызовов == 0
    assert (
        _строки(db_env, "select id from reports where inspection_id = %s", (inspection_id,)) == []
    )


def test_отчёт_несуществующей_проверки_не_ложится_никуда(domain_env: Path, db_env: str) -> None:
    склад = ЗаписнойСклад()
    чужой = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(PushError):
        upload_report(чужой, data=ОТЧЁТ, storage=склад)

    # Файл не положен тоже: объект без строки в истории — мусор, который никто
    # никогда не найдёт и не уберёт.
    assert склад.вызовов == 0


def test_ключ_объекта_повторяем_для_одних_и_тех_же_байтов() -> None:
    # Без базы: чистое правило имени, на котором держится вся повторяемость.
    один = report_object_key("insp-1", "abc123")
    другой = report_object_key("insp-1", "abc123")
    assert один == другой
    assert report_object_key("insp-1", "abc123") != report_object_key("insp-2", "abc123")
