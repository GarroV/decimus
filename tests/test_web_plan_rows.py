"""Строки электронного плана на экране: заслоны записи, разбор формы, вид панели (#1168).

Ядро здесь — заслоны: заполнять строки и вести их «в работу» → «сделано» может только
партнёр, вердикты, приём и сдвиг отсчёта — только УК, и каждый маршрут отказывает чужой
стороне, не дойдя до двери блока `db`. Двери подменены: что держит база (порядок
переходов, срок не позже положенного), проверяет `tests/test_db_plan_rows.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db import action_plans as plans
from src.db import plan_flow as flow
from src.db.errors import ActionPlanError
from src.db.plan_rows import PlanRow

ORIGIN = {"Origin": "http://localhost"}
ЗАПРОС = "11111111-1111-1111-1111-111111111111"
СТРОКА = "55555555-5555-5555-5555-555555555555"

#: Дверь → имя функции в `plan_flow`; зовы пишутся под этим именем.
ДВЕРИ_ПАРТНЁРА = ("save_row", "submit_plan", "start_row", "finish_row")
ДВЕРИ_УК = ("accept_plan", "return_plan", "confirm_row", "return_row", "set_count_from")

ЗАПИСЬ_ПАРТНЁРА = [
    f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/save",
    f"/actions/requests/{ЗАПРОС}/submit",
    f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/start",
    f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/done",
]
ЗАПИСЬ_УК = [
    f"/actions/requests/{ЗАПРОС}/accept",
    f"/actions/requests/{ЗАПРОС}/return",
    f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/confirm",
    f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/reject",
    f"/actions/requests/{ЗАПРОС}/count-from",
]


def строка(**kw: Any) -> PlanRow:
    данные: dict[str, Any] = {
        "id": СТРОКА,
        "request_id": ЗАПРОС,
        "finding_id": "66666666-6666-6666-6666-666666666666",
        "position": 1,
        "item_code": "PRD01",
        "level": "D2",
        "zone": "fridge",
        "title_ru": "Заготовка размечена",
        "title_en": "Prep item is tagged",
        "days": 5,
        "measure": "",
        "responsible": "",
        "reason": "",
        "own_due": None,
        "extended_due": None,
        "due_on": date(2026, 10, 9),
        "status": "filling",
        "return_reason": "",
        "updated_at": datetime(2026, 10, 4, tzinfo=UTC),
    }
    данные.update(kw)
    return PlanRow(**данные)


def запрос(*, status: str = "requested", rows: tuple[PlanRow, ...] | None = None) -> Any:
    return plans.PlanRequest(
        id=ЗАПРОС,
        inspection_id="33333333-3333-3333-3333-333333333333",
        country="GE",
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
        files=(),
        events=(),
        count_from=date(2026, 10, 4),
        revision=1,
        electronic=True,
        review_comment=None,
        rows=(строка(),) if rows is None else rows,
    )


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Двери `plan_flow`, подменённые и пишущие, кого и с чем звали."""
    журнал: dict[str, list[dict[str, Any]]] = {имя: [] for имя in (*ДВЕРИ_ПАРТНЁРА, *ДВЕРИ_УК)}

    def дверь(имя: str) -> Any:
        def позвать(*args: Any, **kw: Any) -> None:
            журнал[имя].append({"args": args, **kw})

        return позвать

    for имя in журнал:
        monkeypatch.setattr(flow, имя, дверь(имя))
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос())
    monkeypatch.setattr(plans, "list_requests", lambda **_: plans.PlanList((), False))
    return журнал


def _стенд(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str = "admin"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    monkeypatch.setattr("src.web.country.countries", lambda **_: (("GE", 2),))
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def уК(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "HQ")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "GE")


def _не_звали(зовы: dict[str, list[Any]], двери: tuple[str, ...]) -> bool:
    return all(зовы[имя] == [] for имя in двери)


# --- заслоны: каждая сторона пишет только своё ------------------------------


@pytest.mark.parametrize("адрес", ЗАПИСЬ_УК)
def test_вердикты_и_приём_отказывают_партнёру_на_каждом_маршруте(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], адрес: str
) -> None:
    ответ = партнёр.post(
        адрес,
        data={"comment": "нет", "reason": "нет", "count_from": "2026-10-01"},
        headers=ORIGIN,
    )

    assert ответ.status_code == 404
    assert _не_звали(зовы, ДВЕРИ_УК)


@pytest.mark.parametrize("адрес", ЗАПИСЬ_ПАРТНЁРА)
def test_заполнение_и_ход_строк_отказывают_уК(
    уК: FlaskClient, зовы: dict[str, list[Any]], адрес: str
) -> None:
    """УК за партнёра строки не заполняет и не отмечает — ни маршрут, ни база не пустят."""
    ответ = уК.post(адрес, data={"measure": "сделаем"}, headers=ORIGIN)

    assert ответ.status_code in (403, 404)
    assert _не_звали(зовы, ДВЕРИ_ПАРТНЁРА)


@pytest.mark.parametrize("адрес", [*ЗАПИСЬ_УК, *ЗАПИСЬ_ПАРТНЁРА])
@pytest.mark.parametrize("клиент", ["уК", "партнёр"])
def test_чужой_сайт_не_пишет_в_план(
    клиент: str, request: pytest.FixtureRequest, зовы: dict[str, list[Any]], адрес: str
) -> None:
    стенд = request.getfixturevalue(клиент)

    ответ = стенд.post(адрес, data={}, headers={"Origin": "https://evil.example"})

    assert ответ.status_code in (403, 404)
    assert _не_звали(зовы, (*ДВЕРИ_УК, *ДВЕРИ_ПАРТНЁРА))


# --- партнёр: форма строки и ход -------------------------------------------


def test_партнёр_сохраняет_строку_подпись_из_сессии(
    партнёр: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/save",
        data={
            "measure": " Заменить ",
            "responsible": "Иванов",
            "reason": "",
            "own_due": "2026-10-07",
            "actor": "подлог",
        },
        headers=ORIGIN,
    )

    assert ответ.status_code == 200
    [зов] = зовы["save_row"]
    assert зов["args"] == (ЗАПРОС, СТРОКА)
    assert зов["actor"] == ЛОГИН
    assert зов["tenant"] == "GE"
    assert (зов["measure"], зов["responsible"], зов["reason"]) == ("Заменить", "Иванов", "")
    assert зов["own_due"] == date(2026, 10, 7)


def test_пустой_свой_срок_это_без_срока(партнёр: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    партнёр.post(
        f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/save", data={"own_due": ""}, headers=ORIGIN
    )

    assert зовы["save_row"][0]["own_due"] is None


def test_неразобранная_дата_это_отказ_а_не_молчаливое_без_срока(
    партнёр: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/save",
        data={"own_due": "завтра"},
        headers=ORIGIN,
    )

    assert ответ.status_code == 400
    assert "Дата не разобрана" in ответ.get_data(as_text=True)
    assert зовы["save_row"] == []


def test_отказ_базы_виден_партнёру_словами(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(*_a: Any, **_k: Any) -> None:
        raise ActionPlanError("План уже отправлен на согласование")

    monkeypatch.setattr(flow, "submit_plan", отказ)

    ответ = партнёр.post(f"/actions/requests/{ЗАПРОС}/submit", headers=ORIGIN)

    assert ответ.status_code == 400
    assert "План уже отправлен на согласование" in ответ.get_data(as_text=True)


@pytest.mark.parametrize(
    ("шаг", "дверь"),
    [("start", "start_row"), ("done", "finish_row")],
)
def test_ход_строки_зовёт_свою_дверь(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], шаг: str, дверь: str
) -> None:
    ответ = партнёр.post(f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/{шаг}", headers=ORIGIN)

    assert ответ.status_code == 200
    assert [(з["args"], з["actor"]) for з in зовы[дверь]] == [((ЗАПРОС, СТРОКА), ЛОГИН)]


# --- УК: вердикты ----------------------------------------------------------


def test_уК_возвращает_строку_с_причиной(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/reject",
        data={"reason": "нет фото"},
        headers=ORIGIN,
    )

    assert ответ.status_code == 200
    assert зовы["return_row"] == [{"args": (ЗАПРОС, СТРОКА), "actor": ЛОГИН, "reason": "нет фото"}]


def test_уК_подтверждает_строку_и_закрытие_плана_сказано(
    уК: FlaskClient, зовы: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(status="closed"))

    ответ = уК.post(f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/confirm", headers=ORIGIN)

    assert ответ.status_code == 200
    assert [з["args"] for з in зовы["confirm_row"]] == [(ЗАПРОС, СТРОКА)]
    assert "план закрыт" in ответ.get_data(as_text=True)


def test_уК_принимает_и_возвращает_план(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    уК.post(f"/actions/requests/{ЗАПРОС}/accept", headers=ORIGIN)
    уК.post(
        f"/actions/requests/{ЗАПРОС}/return", data={"comment": "добавьте сроки"}, headers=ORIGIN
    )

    assert [з["args"] for з in зовы["accept_plan"]] == [(ЗАПРОС,)]
    assert зовы["return_plan"] == [{"args": (ЗАПРОС,), "actor": ЛОГИН, "comment": "добавьте сроки"}]


def test_сдвиг_отсчёта_без_даты_отказ_без_записи(
    уК: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = уК.post(f"/actions/requests/{ЗАПРОС}/count-from", data={}, headers=ORIGIN)

    assert ответ.status_code == 400
    assert зовы["set_count_from"] == []


def test_сдвиг_отсчёта_передаёт_дату(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        f"/actions/requests/{ЗАПРОС}/count-from", data={"count_from": "2026-10-01"}, headers=ORIGIN
    )

    assert ответ.status_code == 200
    assert зовы["set_count_from"][0]["count_from"] == date(2026, 10, 1)


# --- панель: что видит каждая сторона --------------------------------------


def _панель(клиент: FlaskClient, lang: str = "ru") -> str:
    return клиент.get(f"/actions?tab=plans&id={ЗАПРОС}&lang={lang}").get_data(as_text=True)


def test_партнёр_заполняет_строки_на_экране_или_файлом_туда_и_обратно(партнёр: FlaskClient) -> None:
    страница = _панель(партнёр)

    assert "Заготовка размечена" in страница
    assert f"/actions/requests/{ЗАПРОС}/rows/{СТРОКА}/save" in страница
    # Файл туда и обратно (шаг 3): выгрузка строк плана и загрузка с разбором.
    assert f"/actions/requests/{ЗАПРОС}/upload" in страница
    assert f"/actions/requests/{ЗАПРОС}/template.xlsx" in страница
    # Отправить нельзя, пока не заполнено: кнопка есть, но выключена, и сказано почему.
    assert f"/actions/requests/{ЗАПРОС}/submit" in страница
    assert "заполнено 0 из 1" in страница
    # Свой срок — не позже положенного: 4 окт + 5 дней.
    assert 'max="2026-10-09"' in страница


def test_готовый_план_можно_отправить(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    готовая = строка(measure="Заменить", responsible="Иванов")
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(rows=(готовая,)))

    страница = _панель(партнёр)

    assert "Доступно, когда" not in страница
    assert "Отправить на согласование" in страница and " disabled" not in страница


def test_уК_на_согласовании_видит_приём_а_формы_строк_нет(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(status="on_review"))

    страница = _панель(уК)

    assert f"/actions/requests/{ЗАПРОС}/accept" in страница
    assert f"/actions/requests/{ЗАПРОС}/return" in страница
    assert f"/actions/requests/{ЗАПРОС}/review" not in страница
    assert "/save" not in страница
    assert f"/actions/requests/{ЗАПРОС}/count-from" in страница


@pytest.mark.parametrize(
    ("клиент", "ждём", "не_ждём"),
    [
        ("партнёр", ("Взяли в работу",), ("Подтвердить",)),
        ("уК", ("Подтвердить",), ("Взяли в работу",)),
    ],
)
def test_кнопки_хода_у_плана_в_работе_по_сторонам(
    клиент: str,
    ждём: tuple[str, ...],
    не_ждём: tuple[str, ...],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = request.getfixturevalue(клиент)
    monkeypatch.setattr(
        plans,
        "get_request",
        lambda *_a, **_k: запрос(
            status="in_work",
            rows=(
                строка(position=1, status="filling", measure="a", responsible="b"),
                строка(
                    id="77777777-7777-7777-7777-777777777777",
                    finding_id="88888888-8888-8888-8888-888888888888",
                    position=2,
                    status="done",
                    measure="a",
                    responsible="b",
                ),
            ),
        ),
    )

    страница = _панель(стенд)

    assert all(текст in страница for текст in ждём)
    assert not any(текст in страница for текст in не_ждём)


def test_просроченная_строка_помечена_на_чтении(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plans,
        "get_request",
        lambda *_a, **_k: запрос(status="in_work", rows=(строка(status="in_work"),)),
    )
    monkeypatch.setattr(plans, "today", lambda: date(2026, 10, 20))

    страница = _панель(партнёр)

    assert "Просрочена" in страница


def test_панель_на_английском_без_русских_подписей(партнёр: FlaskClient) -> None:
    страница = _панель(партнёр, "en")

    assert "Plan rows" in страница and "Send for approval" in страница
    assert "Строки плана" not in страница


def test_у_файлового_плана_панель_прежняя(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    файловый = запрос(rows=())
    файловый = plans.PlanRequest(**{**файловый.__dict__, "electronic": False})
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: файловый)

    страница = _панель(партнёр)

    assert f"/actions/requests/{ЗАПРОС}/upload" in страница
    assert "/rows/" not in страница


@pytest.mark.parametrize(("lang", "фраза"), [("ru", "версий файла"), ("en", "file versions")])
def test_сверх_предела_версий_файла_отказ_словами_на_языке_экрана(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch, lang: str, фраза: str
) -> None:
    from io import BytesIO

    from src.db.errors import PlanFileLimitError

    def отказ(*_a: Any, **_k: Any) -> int:
        raise PlanFileLimitError(plans.MAX_FILE_VERSIONS)

    monkeypatch.setattr(plans, "upload_version", отказ)

    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/upload?lang={lang}",
        data={"file": (BytesIO(b"%PDF"), "plan.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    assert ответ.status_code == 400
    assert фраза in ответ.get_data(as_text=True)


def test_строки_таблицей_а_правка_во_второй_панели_справа(партнёр: FlaskClient) -> None:
    страница = _панель(партнёр)

    # Таблица строк со ссылкой-якорем (работает и без скрипта), панель правки — рядом.
    assert 'class="ptable"' in страница
    assert f'href="#row-edit-{СТРОКА}"' in страница and "data-row-open" in страница
    assert f'id="row-edit-{СТРОКА}"' in страница and "data-row-panel" in страница
    assert 'role="dialog"' in страница.split(f'id="row-edit-{СТРОКА}"', 1)[1]
    # Форма правки лежит внутри панели, а не в таблице.
    панель = страница.split(f'id="row-edit-{СТРОКА}"', 1)[1]
    assert f"/rows/{СТРОКА}/save" in панель
    assert f"/rows/{СТРОКА}/save" not in страница.split(f'id="row-edit-{СТРОКА}"', 1)[0]


def test_строка_из_уведомления_приходит_с_открытой_панелью(партнёр: FlaskClient) -> None:
    с_строкой = партнёр.get(f"/actions?tab=plans&id={ЗАПРОС}&row={СТРОКА}&lang=ru")
    без = _панель(партнёр)

    assert 'class="prowpanel is-open"' in с_строкой.get_data(as_text=True)
    assert "prowpanel is-open" not in без


def test_у_уК_кнопка_строки_открывает_а_не_правит(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(status="on_review"))

    страница = _панель(уК)

    assert ">Открыть<" in страница and ">Править<" not in страница


# --- шапка экрана по макету: путь, счётчики, баннер, зона, «немедленно» ------


def _шаг(страница: str) -> str:
    """Подпись текущего шага пути плана."""
    хвост = страница.split('aria-current="step"', 1)[1]
    return хвост.split(">", 1)[1].split("<", 1)[0].strip()


@pytest.mark.parametrize(
    ("status", "шаг"),
    [
        ("requested", "Партнёр заполняет"),
        ("on_review", "Согласование"),
        ("in_work", "Выполнение"),
        ("closed", "Закрыт"),
    ],
)
def test_путь_плана_отмечает_текущий_шаг(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch, status: str, шаг: str
) -> None:
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(status=status))

    assert _шаг(_панель(партнёр)) == шаг


def test_счётчики_подтверждённых_и_просроченных(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    строки = (
        строка(status="confirmed"),
        строка(id="s2", position=2, status="in_work"),
        строка(id="s3", position=3, status="done"),
    )
    monkeypatch.setattr(
        plans, "get_request", lambda *_a, **_k: запрос(status="in_work", rows=строки)
    )
    monkeypatch.setattr(plans, "today", lambda: date(2026, 10, 20))

    страница = _панель(уК)

    assert "1 из 3 подтверждено" in страница
    # Срок прошёл у всех трёх, но подтверждённая и сданная (ждёт УК) — не просрочка партнёра.
    assert "просрочено 1" in страница


def test_баннер_партнёра_со_сроком_и_отправкой_выше_строк(партнёр: FlaskClient) -> None:
    страница = _панель(партнёр)

    баннер = страница.index("Заполните план до")
    assert баннер < страница.index('class="ptable"')
    assert баннер < страница.index(f"/actions/requests/{ЗАПРОС}/submit")
    assert страница.count(f"/actions/requests/{ЗАПРОС}/submit") == 1


def test_у_уК_баннера_заполнения_нет(уК: FlaskClient) -> None:
    assert "Заполните план до" not in _панель(уК)


def test_вход_к_файлу_в_шапке_строк_а_загрузка_под_ними(партнёр: FlaskClient) -> None:
    страница = _панель(партнёр)

    assert 'href="#plan-file"' in страница and 'id="plan-file"' in страница
    assert страница.index('class="ptable"') < страница.index('id="plan-file"')


def test_строка_показывает_зону_словом(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.web.action_plans._zone_titles", lambda: {"fridge": ("Холодильник", "Fridge")}
    )

    assert "Холодильник" in _панель(партнёр)
    assert "Fridge" in _панель(партнёр, "en")


def test_зоны_берутся_из_методики(domain_env: object) -> None:
    from src.domain import list_zones
    from src.web.action_plans import _zone_titles

    зона = list_zones()[0]

    assert _zone_titles()[зона.code] == (зона.title("ru"), зона.title("en"))


def test_D3_без_своего_срока_немедленно(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    критичная = строка(level="D3", days=0, due_on=date(2026, 10, 4))
    monkeypatch.setattr(plans, "get_request", lambda *_a, **_k: запрос(rows=(критичная,)))

    страница = _панель(партнёр)

    assert "немедленно" in страница
    assert "Немедленно" not in страница.split('class="ptable"', 1)[0]


def test_уК_сдвигает_отсчёт_отдельным_блоком(уК: FlaskClient) -> None:
    страница = _панель(уК)

    assert "Считать срок от" in страница and "Срок считается от" in страница
    блок = страница.split("Считать срок от", 1)[1]
    assert f"/actions/requests/{ЗАПРОС}/count-from" in блок


def test_уК_на_заполнении_не_видит_слов_про_согласование(уК: FlaskClient) -> None:
    страница = _панель(уК)

    assert "Партнёр заполняет строки" in страница
    assert "План на согласовании" not in страница


@pytest.mark.parametrize(("lang", "фраза"), [("ru", "не настроено"), ("en", "not set up")])
def test_без_хранилища_загрузка_плана_отказывает_словами_а_не_обрывом(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch, lang: str, фраза: str
) -> None:
    """#1137: незаданный `S3_*` — честный отказ 503, а не 500, который экран читает как обрыв."""
    from io import BytesIO

    from src.db.errors import StorageConfigError

    def без_хранилища(*_a: Any, **_k: Any) -> int:
        raise StorageConfigError("S3_BUCKET")

    monkeypatch.setattr(plans, "upload_version", без_хранилища)

    ответ = партнёр.post(
        f"/actions/requests/{ЗАПРОС}/upload?lang={lang}",
        data={"file": (BytesIO(b"%PDF"), "plan.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    assert ответ.status_code == 503
    assert фраза in ответ.get_data(as_text=True)
    assert "S3_BUCKET" not in ответ.get_data(as_text=True)
