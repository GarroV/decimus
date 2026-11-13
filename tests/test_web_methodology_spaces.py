"""«Методика» по пространству (волна 1, #340; Review Focus 4, D283).

Эталон партнёру — на чтение, чек-лист партнёра для УК — на чтение, чужое для
партнёра — «не найден» тем же текстом, что несуществующее. Правки сверяются по
карте маршрутов: новый маршрут записи попадает под проверку сам.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from mcp_checklist_harness import build_methodology
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.mcp.checklist import Store, current_version, read_journal, tip_version
from src.mcp.checklists import create
from src.web.texts import t


@pytest.fixture
def склад(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """Хранилище: эталон УК (`hq/bizdev`) и чек-лист пространства AM (`am/rnd`)."""
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    create(
        replace(store, space="am", code="rnd"),
        tenant="AM",
        name_ru="РНД",
        name_en="RnD",
        today=date(2026, 9, 30),
    )
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    monkeypatch.setenv("AUDIT_DATA_DIR", str(методика))
    return store


def _маршруты_записи(app: Flask) -> list[str]:
    return sorted(
        {
            p.rule
            for p in app.url_map.iter_rules()
            if "POST" in (p.methods or set()) and p.rule.startswith("/admin")
        }
    )


def test_чужой_код_звучит_как_несуществующий(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужой = client.get("/admin?space=am&checklist=rnd").get_data(as_text=True)
        без_пространства = client.get("/admin?checklist=rnd").get_data(as_text=True)
        нет = client.get("/admin?checklist=zzz").get_data(as_text=True)
    assert t("methodology.not_found", "ru", code="rnd") in чужой
    assert t("methodology.not_found", "ru", code="rnd") in без_пространства
    assert t("methodology.not_found", "ru", code="zzz") in нет
    assert "РНД" not in чужой
    assert "РНД" not in без_пространства


def test_уК_открывает_чек_лист_партнёра(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.get("/admin?space=am&checklist=rnd")
        колонка = client.get("/admin").get_data(as_text=True)
    assert ответ.status_code == 200
    assert "РНД" in ответ.get_data(as_text=True)
    assert "space=am" in колонка, "ссылка колонки на чек-лист партнёра потеряла пространство"


def test_партнёр_видит_эталон(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    # Аудитор партнёра чек-лист не правит: экран — только чтение, без падения.
    подменить_двери(monkeypatch, tenant="AM")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        эталон = client.get("/admin?checklist=bizdev")
        своё = client.get("/admin?checklist=rnd")
    assert эталон.status_code == 200
    assert t("methodology.not_found", "ru", code="bizdev") not in эталон.get_data(as_text=True)
    assert "РНД" in своё.get_data(as_text=True)


@pytest.mark.parametrize(
    ("кто", "адрес", "чей"),
    [
        ("GE", "?checklist=bizdev", ("hq", "bizdev")),
        ("AM", "?checklist=bizdev", ("hq", "bizdev")),
        ("HQ", "?space=am&checklist=rnd", ("am", "rnd")),
    ],
)
def test_ни_одна_правка_чужого_не_проходит(
    склад: Store, monkeypatch: pytest.MonkeyPatch, кто: str, адрес: str, чей: tuple[str, str]
) -> None:
    """Каждый POST раздела — по карте маршрутов: новый маршрут записи попадает под проверку сам."""
    цель = replace(склад, space=чей[0], code=чей[1])
    журнал, издание = len(read_journal(цель)), tip_version(цель)
    подменить_двери(monkeypatch, tenant=кто, role="admin")
    app = собрать(tenant="HQ")
    маршруты = _маршруты_записи(app)
    assert len(маршруты) > 5, f"маршрутов записи методики мало — тест проверяет пустоту: {маршруты}"
    with app.test_client() as client:
        войти(client)
        for маршрут in маршруты:
            if маршрут == "/admin/checklists":
                continue  # заведение своего — право админа пространства (D413), ниже свой тест
            ответ = client.post(
                маршрут.replace("<code>", чей[1]) + адрес,
                headers={"Origin": СВОЙ},
                data={
                    "note": "проба",
                    "version": издание,
                    "id": "X01",
                    "on": "1",
                    "state": "retired",
                    "code": чей[1],
                    "name_ru": "Захват",
                    "name_en": "Capture",
                },
            )
            # D761 п.4: отказ — настоящий 403, а не слова на странице с кодом 200.
            if not маршрут.startswith("/admin/"):
                continue  # «/administration/…» — другой раздел, чек-листов не касается
            assert ответ.status_code == 403, f"POST {маршрут}: {ответ.status_code}, ждали 403"
    assert len(read_journal(цель)) == журнал
    assert tip_version(цель) == издание
    for пространство in ("ge", "am") if кто != "HQ" else ():
        assert not (склад.root / пространство / "bizdev").exists(), "у партнёра появилась копия"


def test_отказ_правки_эталона_назван_словами(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(
            "/admin/items?checklist=bizdev", headers={"Origin": СВОЙ}, data={"id": "X01"}
        )
    assert t("methodology.etalon_readonly", "ru") in ответ.get_data(as_text=True)


def test_партнёру_применение_к_проду_не_показано_и_не_выдано(
    склад: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D460: `checklist.apply` — только УК. Кнопки у админа партнёра нет, дверь отказывает;
    у админа УК кнопка есть (чтобы проверка не прошла на пустой странице)."""
    ссылка = "/admin/checklists/rnd/apply"
    подменить_двери(monkeypatch, tenant="AM", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/admin/checklists")
        прямо = client.post(ссылка, headers={"Origin": СВОЙ})
    assert страница.status_code == 200
    assert "РНД" in страница.get_data(as_text=True)
    assert ссылка not in страница.get_data(as_text=True)
    assert прямо.status_code in (403, 404)

    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        у_ук = client.get("/admin/checklists").get_data(as_text=True)
    assert ссылка in у_ук


def test_админ_партнёра_заводит_свой_чек_лист_в_своём_пространстве(
    склад: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D413: заведение — по матрице, а не по «только УК». Пространство берётся у
    вошедшего: код совпал с эталоном, но легла копия у партнёра, эталон цел."""
    эталон = replace(склад, space="hq", code="bizdev")
    журнал_эталона = len(read_journal(эталон))
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/admin/checklists").get_data(as_text=True)
        ответ = client.post(
            "/admin/checklists",
            headers={"Origin": СВОЙ},
            data={"code": "kitchen", "name_ru": "Кухня", "name_en": "Kitchen", "space": "hq"},
        )
    assert t("checklists.new.submit", "ru") in страница, "форма заведения не видна админу партнёра"
    assert ответ.status_code == 200
    assert t("methodology.etalon_readonly", "ru") not in ответ.get_data(as_text=True)
    assert (склад.root / "ge" / "kitchen").exists()
    assert not (склад.root / "hq" / "kitchen").exists(), "чек-лист лёг в пространство УК"
    assert len(read_journal(эталон)) == журнал_эталона


def test_админ_партнёра_не_заводит_в_чужом_пространстве_и_в_ук(
    склад: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        for лишнее in ("am", "hq"):
            client.post(
                f"/admin/checklists?space={лишнее}",
                headers={"Origin": СВОЙ},
                data={
                    "code": "intruder",
                    "name_ru": "Чужой",
                    "name_en": "Intruder",
                    "space": лишнее,
                },
            )
    assert not (склад.root / "am" / "intruder").exists()
    assert not (склад.root / "hq" / "intruder").exists()
    assert (склад.root / "ge" / "intruder").exists(), (
        "заведено у себя: адрес и форма пространство не задают"
    )


def test_сотрудник_партнёра_чек_лист_не_заводит(
    склад: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE", role="auditor")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(
            "/admin/checklists",
            headers={"Origin": СВОЙ},
            data={"code": "kitchen", "name_ru": "Кухня", "name_en": "Kitchen"},
        )
    assert ответ.status_code == 403
    assert not (склад.root / "ge" / "kitchen").exists()


#: Кнопки изменения, которых у чужого чек-листа быть не должно (D761 п.4).
def _кнопки_правки() -> list[str]:
    return [
        t("methodology.master.unset", "ru"),
        t("methodology.master.set", "ru"),
        t("methodology.bar.scoring", "ru"),
        t("methodology.add.open", "ru"),
        t("methodology.publish.submit", "ru"),
    ]


@pytest.mark.parametrize("кто", ["GE", "AM"])
def test_у_партнёра_эталон_без_кнопок_изменения(
    склад: Store, monkeypatch: pytest.MonkeyPatch, кто: str
) -> None:
    """Админ партнёра видит эталон УК только на чтение: ни метки, ни оценки, ни «+ Пункт»."""
    подменить_двери(monkeypatch, tenant=кто, role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/admin?checklist=bizdev").get_data(as_text=True)
        перечень = client.get("/admin/checklists").get_data(as_text=True)
    for кнопка in _кнопки_правки():
        assert кнопка not in страница, f"у партнёра на эталоне осталась кнопка «{кнопка}»"
    assert t("methodology.etalon_readonly", "ru") in страница
    assert "/admin/checklists/bizdev/" not in перечень, "в перечне у партнёра правка эталона"


def test_у_партнёра_свой_чек_лист_правится(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """D762: свой чек-лист партнёр по-прежнему правит — кнопки на месте, правка проходит."""
    подменить_двери(monkeypatch, tenant="AM", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/admin?checklist=rnd").get_data(as_text=True)
        ответ = client.post(
            "/admin/checklists/rnd/state?checklist=rnd",
            headers={"Origin": СВОЙ},
            data={"state": "draft"},
        )
    assert t("methodology.bar.scoring", "ru") in страница
    assert ответ.status_code != 403


def test_колонка_чек_листов_называет_версию_а_не_число_пунктов(
    склад: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D764: подпись строки — «версия от <день> · состояние»; числа пунктов нет."""
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/admin?checklist=bizdev").get_data(as_text=True)
    assert "версия от " in страница
    assert "Пунктов:" not in страница
