"""Путь из критерия приёмки спеки — через настоящую базу, двери и экраны (волна 2).

Один честный путь вместо стены подменённых тестов: УК подтверждает проверку с
D2 → у партнёра Грузии сам появился запрос → он загружает план → УК
возвращает с «нет сроков» → партнёр загружает вторую версию → УК принимает. На
экране страны видны обе версии, комментарий и «Принят». Партнёр Армении ничего
из этого не видит, а раздел УК отвечает ему 404.

Подменены только опознание (вход без базы учёток) и хранилище файлов (в
памяти) — всё остальное настоящее: база с ролями и триггерами `0036`,
подтверждение проверки, маршруты, шаблоны.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

from src.db import action_plans as plans
from src.db.accept import accept_inspection
from src.db.reach import reach_of

pytestmark = requires_db

ORIGIN = {"Origin": "http://localhost"}


class Хранилище:
    def __init__(self) -> None:
        self.объекты: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.объекты[key] = data
        return f"s3://test/{key}"

    def get(self, key: str) -> bytes:
        return self.объекты[key]

    def delete(self, key: str) -> None:
        self.объекты.pop(key, None)


Вход = Callable[[str], FlaskClient]


@pytest.fixture
def как(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Вход:
    """`как("GE")` — клиент, вошедший человеком этого пространства."""
    set_retraction_env(db_env, monkeypatch)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    склад = Хранилище()
    monkeypatch.setattr(plans, "S3PhotoStorage", lambda _settings: склад)
    monkeypatch.setattr(plans, "load_storage_settings", lambda: None)

    def войти_как(tenant: str) -> FlaskClient:
        подменить_двери(monkeypatch, tenant=tenant, role="admin")
        # Охват — настоящий, из базы (`space_countries`), а не по коду.
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        client = собрать(tenant=tenant).test_client()
        assert войти(client).status_code == 302
        return client

    return войти_как


def _проверка_уК_с_d2() -> str:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    start_inspection(9_300_001, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_300_001, code="PRD02", level="D2", zone="cold_kitchen", text="партии вместе")
    ident = push_inspection(9_300_001)
    accept_inspection(ident, tenant="HQ", actor="hq-lead")
    return ident


def _загрузить(client: FlaskClient, request_id: str, байты: bytes) -> str:
    ответ = client.post(
        f"/plans/{request_id}/upload?lang=ru",
        data={"file": (io.BytesIO(байты), "план.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    assert ответ.status_code == 200, ответ.get_data(as_text=True)[:400]
    return ответ.get_data(as_text=True)


def test_путь_из_критерия_приёмки(как: Вход) -> None:
    # Arrange — УК подтвердила проверку с D2: запрос появился сам.
    проверка = _проверка_уК_с_d2()
    запрос = plans.request_of_inspection(проверка, reach=reach_of("HQ"))
    assert запрос is not None and запрос.origin == "auto"

    # Партнёр Грузии видит запрос у себя и загружает PDF.
    грузия = как("GE")
    assert "Batumi-1" in грузия.get("/plans?lang=ru").get_data(as_text=True)
    assert "Версия 1 загружена" in _загрузить(грузия, запрос.id, b"%PDF v1")

    # Партнёр Армении не видит ничего, и раздел УК ему закрыт.
    армения = как("AM")
    assert "Batumi-1" not in армения.get("/plans?lang=ru").get_data(as_text=True)
    файл = plans.request_of_inspection(проверка, reach=reach_of("HQ"))
    assert файл is not None
    assert армения.get(f"/plans/files/{файл.files[0].id}").status_code == 404
    assert армения.get("/actions").status_code == 404
    assert армения.get(f"/actions/requests/{запрос.id}").status_code == 404

    # УК видит план на приёмке и возвращает с комментарием.
    уК = как("HQ")
    assert "Ждут приёмки · 1" in уК.get("/actions?lang=ru").get_data(as_text=True)
    ответ = уК.post(
        f"/actions/requests/{запрос.id}/review?lang=ru",
        data={"verdict": "returned", "comment": "нет сроков"},
        headers=ORIGIN,
    )
    assert "План возвращён" in ответ.get_data(as_text=True)

    # Партнёр видит комментарий и загружает вторую версию.
    грузия = как("GE")
    assert "нет сроков" in грузия.get("/plans?lang=ru").get_data(as_text=True)
    _загрузить(грузия, запрос.id, b"%PDF v2")

    # УК принимает.
    уК = как("HQ")
    ответ = уК.post(
        f"/actions/requests/{запрос.id}/review?lang=ru",
        data={"verdict": "accepted"},
        headers=ORIGIN,
    )
    assert "План принят." in ответ.get_data(as_text=True)

    # Assert — на экране страны обе версии, комментарий и «Принят»; файл УК скачивает.
    страница = уК.get("/country/GE?lang=ru").get_data(as_text=True)
    assert "Версия 1" in страница and "Версия 2" in страница
    assert "нет сроков" in страница and "Принят" in страница
    итог = plans.request_of_inspection(проверка, reach=reach_of("HQ"))
    assert итог is not None and итог.state == plans.STATE_ACCEPTED
    скачано = уК.get(f"/plans/files/{итог.files[-1].id}")
    assert скачано.status_code == 200 and скачано.data == b"%PDF v2"
    assert [e.action for e in итог.events] == [
        "requested",
        "uploaded",
        "returned",
        "uploaded",
        "accepted",
    ]


def test_карточка_отмечает_нужный_план_у_точки_без_страны(как: Вход) -> None:
    """D2 у точки без страны: запроса нет, а на карточке — видимая отметка (ревью #495, п.4)."""
    from src.db.directory import upsert_unit
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    # Arrange — точка без страны, проверка УК с D2 подтверждена: запрос не завёлся.
    upsert_unit("Nowhere-1", tenant="HQ")
    start_inspection(9_300_002, unit="Nowhere-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_300_002, code="PRD02", level="D2", zone="cold_kitchen", text="партии вместе")
    без_страны = push_inspection(9_300_002)
    accept_inspection(без_страны, tenant="HQ", actor="hq-lead")
    assert plans.request_of_inspection(без_страны, reach=reach_of("HQ")) is None
    со_страной = _проверка_уК_с_d2()
    start_inspection(9_300_003, unit="Nowhere-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_300_003, code="PRD01", level="D1", zone="fridge", text="мелочь")
    только_d1 = push_inspection(9_300_003)
    accept_inspection(только_d1, tenant="HQ", actor="hq-lead")

    # Act
    уК = как("HQ")
    карточка = уК.get(f"/inspections/{без_страны}?lang=ru").get_data(as_text=True)
    обычная = уК.get(f"/inspections/{со_страной}?lang=ru").get_data(as_text=True)
    без_d2 = уК.get(f"/inspections/{только_d1}?lang=ru").get_data(as_text=True)

    # Assert
    assert "Нужен экшн-план, у точки не задана страна" in карточка
    assert "Открыть запрос" in обычная, "карточка не та: блока плана на ней нет"
    assert "Нужен экшн-план, у точки не задана страна" not in обычная
    assert "Запросить экшн-план" in без_d2, "карточка не та: формы запроса на ней нет"
    assert "Нужен экшн-план, у точки не задана страна" not in без_d2
