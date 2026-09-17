"""Отпечаток миграции считается по SQL, а не по комментариям к нему (#258).

Поймано на живой раскатке 17.09.2026: накат схемы на площадке встал целиком,
потому что в применённой миграции `0007_model_suggestion.sql` переписали
**комментарий** — убрали дословную цитату владельца из публичного репозитория
(коммит 9a44a5f, D073). Схема при этом не менялась ни на символ, но отпечаток
файла поменялся, сторож отказал, и вместе с ним не доехали 0012 и 0013 —
функция второй волны осталась на площадке без таблиц.

Отказ был правильным по форме и неверным по существу. Сторож обязан ловить
правку **схемы**, а не правку слов о ней: комментарии в этом репозитории
правятся и будут править — публичность к тому обязывает.

Отсюда три свойства, которые здесь проверяются.

**Отпечаток берётся с нормализованного SQL.** Комментарии и лишние пробелы в
него не входят, а всё остальное входит: правка тела по-прежнему отказ.

**Комментарий внутри строкового литерала — не комментарий.** Тело функции в
`$$…$$` и текст в кавычках уходят в отпечаток как есть, иначе две разные
миграции получили бы один отпечаток, и сторож пропустил бы подмену.

**Переход со старого формата не требует ничего от того, кто не менял файлов.**
База, накатанная прежним раннером, помнит отпечаток полного текста. Файл с тех
пор не тронут — запись перепечатывается сама, молча. Тронут — отказ, но с
выходом: перепечатать поимённо, признав, что менялись только слова.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import empty_database

psycopg = pytest.importorskip("psycopg")

from src.db.checksum import checksum, legacy_checksum, normalize_sql  # noqa: E402
from src.db.errors import ConfigError  # noqa: E402
from src.db.migrate import apply_migrations, reseal_migration  # noqa: E402

ТЕЛО = "create table t (a int);\n"


def _написать(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


# --- нормализация: что входит в отпечаток, а что нет -------------------------


def test_комментарий_в_отпечаток_не_входит() -> None:
    без_слов = "-- было так\n" + ТЕЛО
    другими_словами = "-- стало иначе\n-- и ещё строка\n" + ТЕЛО

    assert checksum(без_слов) == checksum(другими_словами)


def test_блочный_комментарий_и_пустые_строки_тоже_не_входят() -> None:
    пышно = "/* заголовок\n   на две строки */\n\n\n" + ТЕЛО + "\n\n"

    assert checksum(пышно) == checksum(ТЕЛО)


def test_правка_тела_меняет_отпечаток() -> None:
    """Обратная сторона: сторож обязан остаться сторожем."""
    assert checksum(ТЕЛО) != checksum("create table t (a bigint);\n")


def test_двойное_тире_внутри_литерала_остаётся_данными() -> None:
    """Иначе `'a--b'` и `'a'` дали бы один отпечаток, и подмена прошла бы."""
    один = "insert into t values ('a--b');\n"
    другой = "insert into t values ('a');\n"

    assert checksum(один) != checksum(другой)


def test_тело_функции_в_долларах_входит_в_отпечаток_целиком() -> None:
    """В `0004` и `0010` тело правила живёт в `$$…$$` — там `--` данные, не слова."""
    шаблон = "create function f() returns trigger as $$ begin {} end; $$ language plpgsql;\n"

    assert checksum(шаблон.format("return new;")) != checksum(шаблон.format("return old;"))


def test_нормализация_не_склеивает_слова() -> None:
    """Перевод строки — разделитель: `select\\n1` не должно стать `select1`."""
    assert normalize_sql("select\n1;") != normalize_sql("select1;")


# --- накат: живая база -------------------------------------------------------


@requires_db
def test_правка_комментария_не_ломает_накат(tmp_path: Path) -> None:
    """Тот самый случай #258: слова переписали, схему — нет."""
    with empty_database() as dsn:
        _написать(tmp_path, "0001_first.sql", "-- дословная цитата\n" + ТЕЛО)
        assert apply_migrations(dsn, directory=tmp_path) == ["0001_first.sql"]

        _написать(tmp_path, "0001_first.sql", "-- ссылка на решение D077\n" + ТЕЛО)
        assert apply_migrations(dsn, directory=tmp_path) == []


@requires_db
def test_правка_тела_применённой_миграции_по_прежнему_отказ(tmp_path: Path) -> None:
    with empty_database() as dsn:
        _написать(tmp_path, "0001_first.sql", ТЕЛО)
        apply_migrations(dsn, directory=tmp_path)

        _написать(tmp_path, "0001_first.sql", "create table t (a bigint);\n")
        with pytest.raises(ConfigError, match=r"0001_first\.sql"):
            apply_migrations(dsn, directory=tmp_path)


# --- переход со старого формата отпечатка ------------------------------------


def _записать_старый_отпечаток(dsn: str, filename: str, sql: str) -> None:
    """База, накатанная прежним раннером: отпечаток снят с полного текста."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update schema_migrations set checksum = %s where filename = %s",
            (legacy_checksum(sql), filename),
        )
        conn.commit()


@requires_db
def test_старая_печать_нетронутого_файла_обновляется_молча(tmp_path: Path) -> None:
    """Кто файлов не трогал, о смене формата знать не обязан."""
    with empty_database() as dsn:
        текст = "-- пояснение\n" + ТЕЛО
        _написать(tmp_path, "0001_first.sql", текст)
        apply_migrations(dsn, directory=tmp_path)
        _записать_старый_отпечаток(dsn, "0001_first.sql", текст)

        assert apply_migrations(dsn, directory=tmp_path) == []

        # И печать действительно переведена, а не сверена «на лету»: следующий
        # накат не должен снова упираться в тот же старый формат.
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select checksum from schema_migrations where filename = %s", ("0001_first.sql",))
            row = cur.fetchone()
        assert row is not None and row[0] == checksum(текст)


@requires_db
def test_старая_печать_и_правленый_комментарий_отказ_с_выходом(tmp_path: Path) -> None:
    """Случай #258 на базе, накатанной до перехода: сказать, что делать."""
    with empty_database() as dsn:
        было = "-- дословная цитата\n" + ТЕЛО
        _написать(tmp_path, "0001_first.sql", было)
        apply_migrations(dsn, directory=tmp_path)
        _записать_старый_отпечаток(dsn, "0001_first.sql", было)
        _написать(tmp_path, "0001_first.sql", "-- ссылка на D077\n" + ТЕЛО)

        with pytest.raises(ConfigError, match=r"reseal"):
            apply_migrations(dsn, directory=tmp_path)


@requires_db
def test_перепечать_поимённо_чинит_и_не_трогает_соседей(tmp_path: Path) -> None:
    """Перепечать — осознанное действие человека: один файл, названный вслух."""
    with empty_database() as dsn:
        было = "-- дословная цитата\n" + ТЕЛО
        _написать(tmp_path, "0001_first.sql", было)
        _написать(tmp_path, "0002_second.sql", "create table u (b int);\n")
        apply_migrations(dsn, directory=tmp_path)
        _записать_старый_отпечаток(dsn, "0001_first.sql", было)
        соседняя_печать = _печать(dsn, "0002_second.sql")
        _написать(tmp_path, "0001_first.sql", "-- ссылка на D077\n" + ТЕЛО)

        reseal_migration(dsn, "0001_first.sql", directory=tmp_path)

        assert apply_migrations(dsn, directory=tmp_path) == []
        assert _печать(dsn, "0002_second.sql") == соседняя_печать, "перепечать задела соседа"


@requires_db
def test_перепечать_неизвестного_файла_отказ(tmp_path: Path) -> None:
    """Опечатка в имени не должна выглядеть как успешная починка."""
    with empty_database() as dsn:
        _написать(tmp_path, "0001_first.sql", ТЕЛО)
        apply_migrations(dsn, directory=tmp_path)

        with pytest.raises(ConfigError, match=r"0009_нет\.sql"):
            reseal_migration(dsn, "0009_нет.sql", directory=tmp_path)


def _печать(dsn: str, filename: str) -> str:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select checksum from schema_migrations where filename = %s", (filename,))
        row = cur.fetchone()
    assert row is not None, f"записи о {filename} нет"
    return str(row[0])
