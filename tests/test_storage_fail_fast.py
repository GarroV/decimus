"""#459: короткий срок и одна попытка — только на пути сдачи и дозагрузки.

Остальные пользователи хранилища (снятие, админка, предписания, экшн-планы)
обязаны остаться с повторами botocore: там человек сам нажал кнопку и
потерять запись из-за одной неудачной попытки хуже, чем подождать.
"""

from __future__ import annotations

import pytest

pytest.importorskip("boto3")

from src.db import photos, reports, retract
from src.db.storage import (
    CONNECT_TIMEOUT_SEC,
    MAX_ATTEMPTS,
    S3PhotoStorage,
    StorageSettings,
)

НАСТРОЙКИ = StorageSettings(
    bucket="inspection-frames",
    access_key_id="ключ-теста",
    secret_access_key="секрет-теста",  # выдуманный
    endpoint_url="http://storage.local.test:8244",
)


def _конфиг(fail_fast: bool) -> object:
    return S3PhotoStorage(НАСТРОЙКИ, fail_fast=fail_fast)._client.meta.config


def test_быстрый_клиент_ждёт_мало_и_пробует_один_раз() -> None:
    конфиг = _конфиг(True)

    assert конфиг.connect_timeout == CONNECT_TIMEOUT_SEC  # type: ignore[attr-defined]
    assert конфиг.retries["total_max_attempts"] == MAX_ATTEMPTS  # type: ignore[attr-defined]


def test_обычный_клиент_остаётся_с_повторами_botocore() -> None:
    конфиг = _конфиг(False)

    assert конфиг.connect_timeout == 60  # type: ignore[attr-defined]
    retries = конфиг.retries or {}  # type: ignore[attr-defined]
    assert retries.get("total_max_attempts", 5) > 1, "у обычного клиента отняли повторы"


class _Стоп(Exception):
    pass


@pytest.fixture
def какой_клиент(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Подменить драйвер во всех модулях и запомнить, каким его просили собрать."""
    просили: list[bool] = []

    def шпион(settings: StorageSettings, *, fail_fast: bool = False) -> object:
        просили.append(fail_fast)
        raise _Стоп

    for модуль in (photos, reports, retract):
        monkeypatch.setattr(модуль, "S3PhotoStorage", шпион)
    monkeypatch.setenv("DATABASE_URL", "postgresql://никуда/не-ходим")
    monkeypatch.setenv("S3_BUCKET", НАСТРОЙКИ.bucket)
    monkeypatch.setenv("S3_ACCESS_KEY_ID", НАСТРОЙКИ.access_key_id)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", НАСТРОЙКИ.secret_access_key)
    return просили


def test_выгрузка_кадров_на_сдаче_идёт_быстрым_клиентом(какой_клиент: list[bool]) -> None:
    with pytest.raises(_Стоп):
        photos.upload_photos("insp", fetch=lambda _: None)

    assert какой_клиент == [True]


def test_выгрузка_отчёта_на_сдаче_идёт_быстрым_клиентом(какой_клиент: list[bool]) -> None:
    with pytest.raises(_Стоп):
        reports.upload_report("insp", data=b"%PDF")

    assert какой_клиент == [True]


def test_снятие_проверки_идёт_клиентом_с_повторами(какой_клиент: list[bool]) -> None:
    with pytest.raises(_Стоп):
        retract._default_storage()

    assert какой_клиент == [False]
