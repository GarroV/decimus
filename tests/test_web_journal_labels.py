"""У каждого изменяющего действия есть подпись на двух языках (D462).

Журнал хранит код (имя маршрута или инструмента), а читаемую фразу рисует экран. Новый
маршрут или инструмент без подписи показывался бы человеку сырым кодом, поэтому он
краснит этот набор: подпись заводится тем же изменением, что и маршрут. Чистый Python.
"""

from __future__ import annotations

import pytest
from web_harness import собрать

from src.mcp.audit import READ_ONLY_TOOLS
from src.mcp.catalogue import TOOLS
from src.web.journal import WRITE_METHODS
from src.web.journal_screen import action_label
from src.web.texts import TEXTS, UI_LANGS
from src.web.texts_journal import MCP_ACTION_CODES, WEB_ACTION_CODES

#: То, что владелец назвал прямо (D462): заморозка, роли, методика, ключи API.
ОБЯЗАТЕЛЬНЫЕ_ВЕБ = {
    "freeze_user": "Заморожена учётка",
    "unfreeze_user": "Разморожена учётка",
    "user_role": "Изменена роль человека",
    "methodology_publish": "Опубликована версия методики",
    "checklists_apply": "Чек-лист применён к проду",
    "checklists_master": "Переключён главный чек-лист",
    "connections_issue": "Выдан ключ API",
    "connections_reissue": "Перевыпущен ключ API",
    "connections_revoke": "Отозван ключ API",
    "connections_update": "Изменены права ключа API",
}


def _изменяющие_маршруты() -> set[str]:
    app = собрать(
        tenant="HQ",
        admin_public_url="https://admin.example",
        mcp_public_url="https://mcp.example/mcp",
    )
    return {
        правило.endpoint
        for правило in app.url_map.iter_rules()
        if правило.methods and правило.methods & WRITE_METHODS
    }


def test_у_каждого_изменяющего_маршрута_есть_подпись() -> None:
    без_подписи = _изменяющие_маршруты() - WEB_ACTION_CODES

    assert not без_подписи, (
        f"у маршрутов нет подписи для журнала: {sorted(без_подписи)}. Добавьте их в "
        f"src/web/texts_journal.py (_WEB) тем же изменением, что и маршрут"
    )


def test_в_подписях_нет_маршрутов_которых_уже_нет() -> None:
    лишние = WEB_ACTION_CODES - _изменяющие_маршруты()

    assert not лишние, f"подписи к несуществующим маршрутам: {sorted(лишние)}"


def test_у_каждого_изменяющего_инструмента_mcp_есть_подпись() -> None:
    изменяющие = {s.name for s in TOOLS if s.writes and s.name not in READ_ONLY_TOOLS}

    assert not (изменяющие - MCP_ACTION_CODES), sorted(изменяющие - MCP_ACTION_CODES)
    assert not (MCP_ACTION_CODES - изменяющие), "подписи к читающим или несуществующим инструментам"


def test_читающие_инструменты_названы_в_каталоге() -> None:
    assert READ_ONLY_TOOLS <= {s.name for s in TOOLS}, "в списке читающих есть неизвестное имя"


@pytest.mark.parametrize("код", sorted(WEB_ACTION_CODES | MCP_ACTION_CODES))
def test_подпись_есть_на_обоих_языках(код: str) -> None:
    запись = TEXTS[f"journal.action.{код}"]

    assert set(UI_LANGS) <= set(запись)
    assert all(запись[язык].strip() for язык in UI_LANGS)


@pytest.mark.parametrize(("код", "подпись"), sorted(ОБЯЗАТЕЛЬНЫЕ_ВЕБ.items()))
def test_названные_владельцем_действия_читаемы(код: str, подпись: str) -> None:
    assert action_label(код, "ru") == подпись
    assert action_label(код, "en") != подпись


def test_незнакомый_код_показывается_как_есть() -> None:
    assert action_label("новый_маршрут", "ru") == "новый_маршрут"
