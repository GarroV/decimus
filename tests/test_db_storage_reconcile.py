"""Сверка хранилища с таблицами на настоящей базе под ролью приложения (#496).

Хранилище — `moto` (S3 внутри процесса), база — настоящая, с ролями и
триггерами. Версия плана кладётся настоящей `upload_version`, то есть ключ и
ссылка ровно те, что пишет продукт. Проверяется то, ради чего сверка: что роли
приложения в сессии только для чтения хватает прочитать обе таблицы, что
список хранилища дочитывается до конца, и что подложенные расхождения
называются, а сходящееся — нет.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, точка_справочника

psycopg = pytest.importorskip("psycopg")
boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from src.db import action_plans as plans  # noqa: E402
from src.db import storage_reconcile  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.db.storage import S3PhotoStorage, StorageSettings  # noqa: E402

КОРЗИНА = "reconcile-test"
АДРЕС = "http://storage.reconcile.test:8245"
НОЛЬ = timedelta(0)


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3PhotoStorage]:
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", АДРЕС)
    with moto.mock_aws():
        settings = StorageSettings(
            bucket=КОРЗИНА,
            access_key_id="ключ-теста",
            secret_access_key="секрет-теста",  # выдуманный, не настоящий
            endpoint_url=АДРЕС,
        )
        boto3.client(
            "s3",
            endpoint_url=АДРЕС,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name=settings.region,
        ).create_bucket(Bucket=КОРЗИНА)
        store = S3PhotoStorage(settings)
        monkeypatch.setattr(storage_reconcile, "S3PhotoStorage", lambda _s: store)
        monkeypatch.setattr(storage_reconcile, "load_storage_settings", lambda: settings)
        yield store


def _версия_плана(store: S3PhotoStorage) -> str:
    """Проверка с D2 → запрос сам → партнёр Грузии кладёт версию. Ключ объекта."""
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    start_inspection(9_400_001, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_400_001, code="PRD02", level="D2", zone="cold_kitchen", text="партии вместе")
    ident = push_inspection(9_400_001)
    accept_inspection(ident, tenant="HQ", actor="hq-lead")
    запрос = plans.request_of_inspection(ident, reach=reach_of("HQ"))
    assert запрос is not None
    plans.upload_version(
        запрос.id,
        reach=reach_of("GE"),
        tenant="GE",
        actor="ge-partner",
        file_name="план.pdf",
        content_type="application/pdf",
        data=b"%PDF v1",
        max_bytes=1024,
        storage=store,
    )
    файлы = plans.request_of_inspection(ident, reach=reach_of("HQ"))
    assert файлы is not None and len(файлы.files) == 1
    return plans.object_key(запрос.id, файлы.files[0].id)


@requires_db
def test_reconcile_names_seeded_discrepancies_under_app_role(
    pg_dsn: str,
    db_env: str,
    domain_env: Path,
    склад: S3PhotoStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db_harness import привязать_страну

    set_retraction_env(db_env, monkeypatch)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    ключ = _версия_плана(склад)

    сначала = storage_reconcile.reconcile_live(grace=НОЛЬ)
    assert [(и.area, и.objects, и.rows, и.clean) for и in сначала] == [
        ("action-plans", 1, 1, True),
        ("prescriptions", 0, 0, True),
    ]

    # Порча: объект версии пропал, а рядом лёг объект без строки.
    склад.delete(ключ)
    сирота = "action-plans/00000000-0000-0000-0000-000000000000/lost"
    склад.put(сирота, b"x", content_type="application/pdf")
    потом = {и.area: и for и in storage_reconcile.reconcile_live(grace=НОЛЬ)}

    assert [o.key for o in потом["action-plans"].orphan_objects] == [сирота]
    assert [r.storage_path for r in потом["action-plans"].missing_objects] == [
        f"s3://{КОРЗИНА}/{ключ}"
    ]
    assert потом["prescriptions"].clean


def test_list_prefix_reads_every_page(склад: S3PhotoStorage) -> None:
    """Список больше одной страницы S3 (1000 ключей) — дочитан весь, а не первая страница."""
    for n in range(1003):
        склад.put(f"prescriptions/p/{n:04d}", b"x", content_type="text/plain")
    склад.put("action-plans/r/f", b"x", content_type="text/plain")

    найдено = склад.list_prefix("prescriptions/")

    assert len(найдено) == 1003
    assert all(o.key.startswith("prescriptions/") for o in найдено)
