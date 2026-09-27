"""Кадры для вычитки (D199): только выгруженные, не убранные и своего арендатора."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.photo_reads import photos_by_finding, read_photo  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.domain import add_finding, attach_photo, start_inspection  # noqa: E402

pytestmark = requires_db


class Хранилище:
    def __init__(self) -> None:
        self.прочитано: list[str] = []

    def get(self, key: str) -> bytes:
        self.прочитано.append(key)
        return b"jpeg:" + key.encode()


def _проверка_с_кадрами(db_env: str) -> tuple[str, list[str]]:
    start_inspection(501, unit="Белград-1", kind="planned", report_lang="ru", tenant="default")
    add_finding(501, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    attach_photo(501, 1, "file-a")
    attach_photo(501, 1, "file-b")
    ident = push_inspection(501)
    with psycopg.connect(db_env) as conn:
        ids = [
            str(r[0])
            for r in conn.execute(
                "select id from photos where inspection_id = %s order by id", (ident,)
            ).fetchall()
        ]
        # Первый кадр выгружен, второй — ещё нет.
        conn.execute(
            "update photos set storage_path = %s, uploaded_at = now() where id = %s",
            (f"s3://корзина/inspections/{ident}/{ids[0]}.jpg", ids[0]),
        )
        conn.commit()
    return ident, ids


def test_видны_только_выгруженные_кадры(domain_env: Path, db_env: str) -> None:
    # Arrange
    ident, (выгружен, не_выгружен) = _проверка_с_кадрами(db_env)
    хранилище = Хранилище()

    # Act
    по_записям = photos_by_finding(ident, tenant="default")
    байты = read_photo(ident, выгружен, tenant="default", storage=хранилище)
    пусто = read_photo(ident, не_выгружен, tenant="default", storage=хранилище)

    # Assert
    assert list(по_записям.values()) == [(выгружен,)]
    assert байты == f"jpeg:inspections/{ident}/{выгружен}.jpg".encode()
    assert пусто is None
    assert хранилище.прочитано == [f"inspections/{ident}/{выгружен}.jpg"]


def test_чужой_арендатор_кадра_не_получает(domain_env: Path, db_env: str) -> None:
    ident, (выгружен, _) = _проверка_с_кадрами(db_env)
    хранилище = Хранилище()
    assert photos_by_finding(ident, tenant="other") == {}
    assert read_photo(ident, выгружен, tenant="other", storage=хранилище) is None
    assert хранилище.прочитано == []


def test_убранный_кадр_не_отдаётся(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    # Arrange — отметку ставит владелец базы: у живой проверки уборку кадров
    # политики пока не пускают никому (это работа D202, #376), а чтение обязано
    # уважать отметку уже сейчас — её ставит и отклонение.
    ident, (выгружен, _) = _проверка_с_кадрами(db_env)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("update photos set purged_at = now() where id = %s", (выгружен,))
        conn.commit()

    # Act / Assert
    assert photos_by_finding(ident, tenant="default") == {}
    assert read_photo(ident, выгружен, tenant="default", storage=Хранилище()) is None
