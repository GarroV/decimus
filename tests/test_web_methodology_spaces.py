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
            client.post(
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
