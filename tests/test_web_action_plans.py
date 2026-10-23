"""Экшн-планы на экране: заслоны записи, кто что может отправить, выдача файла.

Ядро здесь — заслоны (D264, D284, D526): раздел «Действия» один у УК и партнёра,
а запись УК (приём, срок, запрос) отказывает партнёру на каждом маршруте;
загрузка — только партнёру; запрос и файл — по охвату вошедшего, файл только
вложением. Двери блока `db` подменены: что держит база, проверяет
`tests/test_db_action_plans.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db import action_plans as plans
from src.web import action_plans

ORIGIN = {"Origin": "http://localhost"}
ЗАПРОС = "11111111-1111-1111-1111-111111111111"
ФАЙЛ = "22222222-2222-2222-2222-222222222222"


def _куда(ответ: Any) -> tuple[str, dict[str, str]]:
    """Адрес и параметры переадресации — порядок параметров ничего не значит."""
    разбор = urlsplit(ответ.headers["Location"])
    return разбор.path, dict(parse_qsl(разбор.query))


def запрос(
    *,
    status: str = "on_review",
    files: tuple[plans.PlanFile, ...] = (),
    country: str = "GE",
) -> plans.PlanRequest:
    return plans.PlanRequest(
        id=ЗАПРОС,
        inspection_id="33333333-3333-3333-3333-333333333333",
        country=country,
        due_on=date(2026, 10, 11),
        status=status,
        origin="auto",
        requested_by="garva",
        requested_at=datetime(2026, 10, 4, tzinfo=UTC),
        unit_id="44444444-4444-4444-4444-444444444444",
        unit_name="Batumi-1",
        inspection_date=date(2026, 10, 3),
        pct=91.5,
        grade="C",
        files=files,
        events=(),
        count_from=date(2026, 10, 4),
        revision=1,
        electronic=False,
        review_comment=None,
        rows=(),
    )


ВЕРСИЯ = plans.PlanFile(
    id=ФАЙЛ,
    version=1,
    file_name="план.pdf",
    size_bytes=2048,
    content_type="application/pdf",
    uploaded_by="partner",
    uploaded_at=datetime(2026, 10, 5, tzinfo=UTC),
    verdict="returned",
    comment="нет сроков",
    reviewed_by="hq",
    reviewed_at=datetime(2026, 10, 6, tzinfo=UTC),
)


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Двери блока `db` экшн-планов, подменённые и пишущие, кого звали."""
    журнал: dict[str, list[dict[str, Any]]] = {
        "list": [],
        "get": [],
        "review": [],
        "due": [],
        "new": [],
        "upload": [],
        "file": [],
    }

    def записать(имя: str, результат: Any = None) -> Any:
        def дверь(*args: Any, **kw: Any) -> Any:
            журнал[имя].append({"args": args, **kw})
            return результат

        return дверь

    monkeypatch.setattr(
        plans,
        "list_requests",
        записать("list", plans.PlanList(rows=(запрос(files=(ВЕРСИЯ,)),), truncated=False)),
    )
    monkeypatch.setattr(plans, "get_request", записать("get", запрос(files=(ВЕРСИЯ,))))
    monkeypatch.setattr(plans, "review", записать("review"))
    monkeypatch.setattr(plans, "set_due", записать("due"))
    monkeypatch.setattr(plans, "request_plan", записать("new", ЗАПРОС))
    monkeypatch.setattr(plans, "upload_version", записать("upload", 2))
    monkeypatch.setattr(plans, "file_for_download", записать("file", None))
    return журнал


def _стенд(monkeypatch: pytest.MonkeyPatch, tenant: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role="admin")
    monkeypatch.setattr("src.web.country.countries", lambda **_: (("GE", 2), ("AM", 1)))
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def уК(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "HQ")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "GE")


# --- запись УК закрыта партнёру на каждом маршруте --------------------------

ЗАПИСЬ_УК = [
    ("post", f"/actions/requests/{ЗАПРОС}/review"),
    ("post", f"/actions/requests/{ЗАПРОС}/due"),
    ("post", "/actions/request"),
]


@pytest.mark.parametrize(("метод", "адрес"), ЗАПИСЬ_УК)
def test_запись_уК_отказывает_партнёру_на_каждом_маршруте(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], метод: str, адрес: str
) -> None:
    # Act
    ответ = getattr(партнёр, метод)(
        адрес, data={"verdict": "accepted", "due": "2030-01-01"}, headers=ORIGIN
    )

    # Assert — отказ, и ни одна дверь записи не позвана.
    assert ответ.status_code == 404
    assert зовы["review"] == зовы["due"] == зовы["new"] == []


@pytest.mark.parametrize(("метод", "адрес"), ЗАПИСЬ_УК)
def test_второй_заслон_держит_и_без_границы_пространств(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch, метод: str, адрес: str
) -> None:
    """Границу пространств по объявлениям сняли — матрица всё равно отказывает."""
    monkeypatch.setattr("src.web.app.refused_for", lambda *_: False)
    monkeypatch.setattr("src.web.guard.open_to_tenant", lambda *_: True)
    ответ = getattr(партнёр, метод)(адрес, data={"verdict": "accepted"}, headers=ORIGIN)
    # Запись без права в матрице отказывает заслоном ещё до маршрута: 403.
    assert ответ.status_code == 403


@pytest.mark.parametrize("клиент", ["уК", "партнёр"])
def test_меню_обеих_сторон_зовёт_в_одни_действия(
    клиент: str, request: pytest.FixtureRequest
) -> None:
    """D526: одно меню — «Действия»; пунктов «Экшн-планы» и «Предписания» у партнёра нет."""
    страница = request.getfixturevalue(клиент).get("/actions").get_data(as_text=True)
    assert 'href="/actions' in страница
    assert 'href="/plans' not in страница
    assert 'href="/prescriptions' not in страница


# --- раздел УК: очередь и вердикт -----------------------------------------


def test_уК_видит_очередь_и_запрос(уК: FlaskClient) -> None:
    страница = уК.get("/actions?lang=ru").get_data(as_text=True)
    assert "Batumi-1" in страница
    assert "Ждут приёмки" in страница
    # Даты — словами, как везде (#1086), а не ISO.
    assert "3 окт 2026" in страница and "11 окт 2026" in страница
    assert "2026-10-03" not in страница.split("slist", 1)[1]


def test_уК_переключается_на_принятые_и_блок_принятых_открыт(
    уК: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    страница = уК.get("/actions?accepted=1&lang=ru").get_data(as_text=True)
    assert зовы["list"][-1]["accepted"] is True
    assert "Принятые" in страница and 'class="pk-archive"' not in страница


def test_очередь_по_умолчанию_только_открытые(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    уК.get("/actions?lang=ru")
    assert зовы["list"][-1]["accepted"] is False


def test_партнёр_переключается_на_принятые(
    партнёр: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    партнёр.get("/actions?accepted=1&lang=ru")
    assert зовы["list"][-1]["accepted"] is True


@pytest.mark.parametrize("tenant", ["HQ", "GE"])
def test_обрезанный_список_сказан_на_экране(
    tenant: str, monkeypatch: pytest.MonkeyPatch, зовы: Any
) -> None:
    monkeypatch.setattr(
        plans,
        "list_requests",
        lambda **_: plans.PlanList(rows=(запрос(files=(ВЕРСИЯ,)),), truncated=True),
    )
    for client in _стенд(monkeypatch, tenant):
        страница = client.get("/actions?lang=ru").get_data(as_text=True)
        assert f"Показаны первые {plans.LIST_LIMIT}" in страница


def test_уК_возвращает_план_подпись_из_сессии(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    # Act
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/review",
        data={"verdict": "returned", "comment": "нет сроков", "actor": "подлог"},
        headers=ORIGIN,
    )

    # Assert
    assert ответ.status_code == 200
    assert зовы["review"] == [
        {"args": (ЗАПРОС,), "actor": ЛОГИН, "verdict": "returned", "comment": "нет сроков"}
    ]


def test_чужой_сайт_не_отправляет_вердикт(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/review",
        data={"verdict": "accepted"},
        headers={"Origin": "https://evil.example"},
    )
    assert ответ.status_code == 403
    assert зовы["review"] == []


def test_ручной_запрос_ведёт_к_запросу(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        "/actions/request",
        data={"inspection_id": "x", "due": "2030-01-15"},
        headers=ORIGIN,
    )
    assert ответ.status_code == 303
    assert ответ.headers["Location"].startswith(f"/actions?tab=plans&id={ЗАПРОС}")
    assert зовы["new"][0]["due_on"] == date(2030, 1, 15)


# --- панель запроса: одна у обеих сторон, добавки по стороне -------------------


def test_панель_уК_даёт_приёмку_и_срок_а_загрузки_нет(уК: FlaskClient) -> None:
    страница = уК.get(f"/actions?tab=plans&id={ЗАПРОС}&lang=ru").get_data(as_text=True)
    assert f"/actions/requests/{ЗАПРОС}/review" in страница
    assert f"/actions/requests/{ЗАПРОС}/due" in страница
    assert "/upload" not in страница
    assert "Batumi-1" in страница


def test_панель_партнёра_даёт_загрузку_а_приёмки_и_срока_нет(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    ждём = запрос(status="requested", files=(ВЕРСИЯ,))
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: ждём)
    страница = партнёр.get(f"/actions?tab=plans&id={ЗАПРОС}&lang=ru").get_data(as_text=True)
    assert f"/actions/requests/{ЗАПРОС}/upload" in страница
    assert "Загрузить файл плана" in страница
    assert "/review" not in страница and "/due" not in страница
    # Поле — не голая кнопка браузера, а зона дизайн-системы.
    assert "supload" in страница


def test_партнёр_видит_комментарий_возврата_и_версии(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plans, "get_request", lambda *_a, **_k: запрос(status="requested", files=(ВЕРСИЯ,))
    )
    страница = партнёр.get(f"/actions?tab=plans&id={ЗАПРОС}&lang=ru").get_data(as_text=True)
    assert "нет сроков" in страница
    assert f"/actions/plan-files/{ФАЙЛ}" in страница


def test_партнёр_не_открывает_чужой_запрос_по_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """`?id=` не обходит охват: запрос страны AM партнёру GE — «не найдена», без сведений."""
    чужой = запрос(country="AM", files=(ВЕРСИЯ,))
    просмотры: list[Any] = []

    def получить(request_id: str, *, reach: Any) -> Any:
        просмотры.append(reach.countries)
        return чужой if "AM" in reach.countries else None

    monkeypatch.setattr(plans, "get_request", получить)
    monkeypatch.setattr(plans, "list_requests", lambda **_: plans.PlanList((), False))
    for клиент in _стенд(monkeypatch, "GE"):
        ответ = клиент.get(f"/actions?tab=plans&id={ЗАПРОС}&lang=ru")
        страница = ответ.get_data(as_text=True)
        assert ответ.status_code == 200
        assert "Запись не найдена" in страница
        assert "Batumi-1" not in страница and "план.pdf" not in страница
    assert просмотры == [("GE",)]


def test_старый_адрес_партнёра_переадресует_в_действия(партнёр: FlaskClient) -> None:
    ответ = партнёр.get("/plans?accepted=1&lang=ru")
    assert ответ.status_code == 303
    assert _куда(ответ) == ("/actions", {"tab": "plans", "accepted": "1", "lang": "ru"})


def test_старая_карточка_запроса_уК_переадресует_в_панель(уК: FlaskClient) -> None:
    ответ = уК.get(f"/actions/requests/{ЗАПРОС}?lang=ru")
    assert ответ.status_code == 303
    assert _куда(ответ) == ("/actions", {"tab": "plans", "id": ЗАПРОС, "lang": "ru"})


def test_старая_ссылка_на_файл_ведёт_на_новый_адрес(партнёр: FlaskClient) -> None:
    ответ = партнёр.get(f"/plans/files/{ФАЙЛ}")
    assert ответ.status_code == 303
    assert ответ.headers["Location"] == f"/actions/plan-files/{ФАЙЛ}"


def test_действие_из_панели_отвечает_только_панелью(
    уК: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """`split.js` шлёт форму фоном (`X-Panel`): страницы целиком быть не должно."""
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/review",
        data={"verdict": "accepted"},
        headers={**ORIGIN, "X-Panel": "1"},
    )
    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert 'class="sdetail spanel' in страница
    assert "<html" not in страница
    assert "План принят." in страница


def test_отказ_из_панели_остаётся_200_иначе_скрипт_примет_его_за_обрыв(
    партнёр: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/upload",
        data={},
        headers={**ORIGIN, "X-Panel": "1"},
        content_type="multipart/form-data",
    )
    assert ответ.status_code == 200
    assert "Файл не выбран." in ответ.get_data(as_text=True)
    assert зовы["upload"] == []


def test_уК_версию_не_загружает(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/upload",
        data={"file": (_файл(b"x"), "p.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    assert ответ.status_code == 403
    assert зовы["upload"] == []


def test_партнёр_загружает_в_своём_охвате(партнёр: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    # Act
    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/upload",
        data={"file": (_файл(b"%PDF plan"), "план.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    # Assert — пространство и охват берутся из входа, а не из формы.
    assert ответ.status_code == 200
    [зов] = зовы["upload"]
    assert (зов["tenant"], зов["reach"].countries) == ("GE", ("GE",))
    assert (зов["data"], зов["file_name"], зов["actor"]) == (b"%PDF plan", "план.pdf", ЛОГИН)


def test_больше_предела_отказ_словами(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    monkeypatch.setenv("ATTACHMENT_MAX_MB", "1")
    клиент = next(_стенд(monkeypatch, "GE"))
    ответ = клиент.post(
        f"/actions/requests/{ЗАПРОС}/upload",
        data={"file": (_файл(b"x" * (2 * 1024 * 1024)), "big.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    assert ответ.status_code == 413
    assert "1 МБ" in ответ.get_data(as_text=True)
    assert зовы["upload"] == []


# --- выдача файла ---------------------------------------------------------


def test_чужой_файл_отвечает_404(партнёр: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = партнёр.get(f"/actions/plan-files/{ФАЙЛ}")
    assert ответ.status_code == 404
    assert зовы["file"][0]["reach"].countries == ("GE",)


def test_файл_отдаётся_только_вложением(уК: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ссылка = plans.PlanFileRef("s3://b/action-plans/x/y", "plan.html", "text/html", 10)
    monkeypatch.setattr(plans, "file_for_download", lambda *_a, **_k: ссылка)
    monkeypatch.setattr(plans, "fetch_file", lambda *_a, **_k: b"<script>1</script>")

    ответ = уК.get(f"/actions/plan-files/{ФАЙЛ}")

    assert ответ.status_code == 200
    assert ответ.mimetype == "application/octet-stream"
    assert ответ.headers["Content-Disposition"].startswith("attachment")
    assert ответ.headers["X-Content-Type-Options"] == "nosniff"


def _файл(байты: bytes) -> Any:
    import io

    return io.BytesIO(байты)


def test_состояния_размечены_все() -> None:
    assert set(action_plans.STATE_TONES) == {
        plans.STATE_REQUESTED,
        plans.STATE_RETURNED,
        plans.STATE_ON_REVIEW,
        plans.STATE_ACCEPTED,
    }
