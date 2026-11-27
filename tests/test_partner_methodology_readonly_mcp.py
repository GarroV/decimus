"""Заслон: в Claude (MCP) партнёр не меняет методику УК и чек-листы другого партнёра.

D285, D460, D761 п.4. Каждый правящий инструмент методики зовётся с ГОДНЫМИ
аргументами — теми, с которыми он у владельца правки проходит (контроль ниже), —
иначе отказ постороннему мог бы быть отказом разбора аргументов, а не границей
пространства. Соседний перебор (`test_mcp_partner_methodology.py`) шлёт всем
инструментам один набор ключей и потому до наведения на хранилище часто не доходит.

Вызов идёт сквозь настоящую дверь: хранилище подставляет `server._checklist_for`
по пространству из токена, роль — из входа через OAuth, подтверждение опасных
инструментов проходит `handle_confirmed`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import handle_confirmed as handle
from partner_readonly_harness import ДРУГОЙ, ПАРТНЁР, УК, свежее_хранилище, снимок, собрать_образец

from src.mcp.catalogue import KIND_CHECKLIST, TOOLS
from src.mcp.checklist import Store, tip_version
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import ETALON_READONLY_FOR_PARTNER
from src.mcp.server import _checklist_for, _checklist_source_for


@pytest.fixture(scope="module")
def образец(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return собрать_образец(tmp_path_factory.mktemp("образец"))


@pytest.fixture
def склад(образец: Path, tmp_path: Path) -> Store:
    return свежее_хранилище(образец, tmp_path / "копия")


def _настройки(склад: Store) -> Settings:
    return Settings(
        tokens={"h" * MIN_TOKEN_LENGTH: УК},
        tenants=(УК,),
        host="127.0.0.1",
        port=0,
        checklist_store=склад.root,
        # Партнёров в списке нет: им методику открывает роль учётки (D460).
        checklist_tenants=(УК,),
        data_dir=склад.root / "current",
    )


def _вызов(склад: Store, имя: str, аргументы: dict[str, Any], *, tenant: str, role: str) -> Any:
    настройки = _настройки(склад)
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=tenant,
        checklist=_checklist_for(настройки, tenant, role),
        source=_checklist_source_for(настройки, tenant, role),
        role=role,
    )
    assert ответ is not None
    return ответ


def _отказ(ответ: Any) -> bool:
    return "error" in ответ or bool(ответ["result"].get("isError"))


def _текст(ответ: Any) -> str:
    if "error" in ответ:
        return str(ответ["error"])
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


#: Инструмент → годные аргументы (без `checklist`). Коды пунктов и зон есть и в
#: эталоне, и в чек-листе AM. `{tip}` — свежая версия цели.
ПРАВКИ: dict[str, dict[str, Any]] = {
    "add_checklist_item": {
        "process": "Чистота",
        "question_ru": "Новый вопрос",
        "levels": "D1",
        "zones": "fridge",
        "days": 10,
        "criteria": "D1: проба",
        "kind": "violation",
    },
    "edit_checklist_item": {"code": "CLN01", "question_ru": "Изменено"},
    "remove_checklist_item": {"code": "CLN01"},
    "restore_checklist_item": {"code": "CLN02"},
    "add_zone": {"code": "newz", "name_ru": "Новая", "equal_shares": True},
    "remove_zone": {"code": "dough", "equal_shares": True},
    "set_zone_shares": {"shares": {"fridge": 60, "dough": 40}},
    "set_scoring": {"d1": 0.7},
    "rename_zone": {"code": "fridge", "name_ru": "Переименована"},
    "set_route": {"zones": ["dough", "fridge"]},
    "add_photo_cue": {"section": "Чистота", "phrase": "Новая примета", "codes": ["CLN01"]},
    "edit_photo_cue": {"phrase": "Стена в подтёках", "new_phrase": "Стена в потёках"},
    "set_photo_cue_zone": {"phrase": "Стеллаж", "zone": "fridge"},
    "remove_photo_cue": {"phrase": "Печь"},
    "publish_checklist_version": {"version": "{tip}"},
    "rename_checklist": {"name_ru": "Захват"},
    "set_checklist_state": {"state": "retired"},
    "set_checklist_bot_access": {"in_bot": False},
    "apply_checklist": {},
    "create_checklist": {"name_ru": "Захват", "name_en": "Capture"},
    "retract_learned_phrase": {"phrase": "проба", "lang": "ru", "reason": "проба"},
    "repoint_learned_phrase": {
        "phrase": "проба",
        "lang": "ru",
        "item_code": "CLN01",
        "reason": "проба",
    },
}

#: Карта слов есть только у эталона (у чек-листа партнёра её заводит человек), а
#: синонимы живут в базе — у этих инструментов нет контроля на чек-листе AM.
БЕЗ_КОНТРОЛЯ_У_ПАРТНЁРА = {
    "add_photo_cue",
    "edit_photo_cue",
    "set_photo_cue_zone",
    "remove_photo_cue",
    "retract_learned_phrase",
    "repoint_learned_phrase",
    "apply_checklist",
    "create_checklist",
}
#: `apply_checklist`: в раскладке нет второго годного к проду чек-листа УК — что УК
#: применяет, проверяют `test_mcp_checklists_tools.py`; здесь — лишь отказ партнёру.
БЕЗ_КОНТРОЛЯ_У_УК = {
    "retract_learned_phrase",
    "repoint_learned_phrase",
    "create_checklist",
    "apply_checklist",
}
#: Состояние и метку у применённого к проду эталона дверь меняет не всякие — в
#: пространстве УК они проверяются на черновике `spare`.
НА_ЗАПАСНОМ = {"set_checklist_state", "apply_checklist"}


def _аргументы(склад: Store, имя: str, *, space: str, code: str) -> dict[str, Any]:
    цель = Store(root=склад.root, live=склад.live, space=space, code=code)
    return {
        **{
            ключ: (tip_version(цель) if значение == "{tip}" else значение)
            for ключ, значение in ПРАВКИ[имя].items()
        },
        "checklist": code,
    }


def _код(имя: str, space: str) -> str:
    if space == "hq":
        return "spare" if имя in НА_ЗАПАСНОМ else "bizdev"
    return "rnd"


def test_каждый_правящий_инструмент_методики_проверен() -> None:
    правящие = {s.name for s in TOOLS if s.kind == KIND_CHECKLIST and s.writes}
    assert правящие == set(ПРАВКИ)


# --- контроль: аргументы годны, у владельца правки хранилище меняется ---------------


@pytest.mark.parametrize("имя", sorted(set(ПРАВКИ) - БЕЗ_КОНТРОЛЯ_У_УК))
def test_контроль_уК_меняет_эталон(склад: Store, имя: str) -> None:
    до = снимок(склад.root)

    ответ = _вызов(
        склад,
        имя,
        _аргументы(склад, имя, space="hq", code=_код(имя, "hq")),
        tenant=УК,
        role="admin",
    )

    assert not _отказ(ответ), _текст(ответ)
    assert снимок(склад.root) != до


@pytest.mark.parametrize("имя", sorted(set(ПРАВКИ) - БЕЗ_КОНТРОЛЯ_У_ПАРТНЁРА))
def test_контроль_партнёр_меняет_своё(склад: Store, имя: str) -> None:
    до = снимок(склад.root)

    ответ = _вызов(
        склад, имя, _аргументы(склад, имя, space="am", code="rnd"), tenant=ПАРТНЁР, role="admin"
    )

    assert not _отказ(ответ), _текст(ответ)
    assert снимок(склад.root) != до


# --- партнёр на эталоне и на чужом ---------------------------------------------------


@pytest.mark.parametrize("роль", ["admin", "auditor"])
@pytest.mark.parametrize("имя", sorted(ПРАВКИ))
def test_партнёр_не_меняет_эталон(склад: Store, имя: str, роль: str) -> None:
    код = _код(имя, "hq")
    до = снимок(склад.root, кроме="am")

    ответ = _вызов(
        склад, имя, _аргументы(склад, имя, space="hq", code=код), tenant=ПАРТНЁР, role=роль
    )

    assert _отказ(ответ), f"{имя}: правка эталона партнёром не отказала"
    assert снимок(склад.root, кроме="am") == до, f"{имя}: партнёр изменил эталон"
    if роль == "admin" and имя not in {"apply_checklist", "create_checklist"}:
        assert _текст(ответ) == ETALON_READONLY_FOR_PARTNER.format(код=код)


@pytest.mark.parametrize("имя", sorted(ПРАВКИ))
def test_партнёр_не_меняет_чек_лист_другого_партнёра(склад: Store, имя: str) -> None:
    """GE называет код чек-листа AM: наведение остаётся в пространстве GE."""
    до = снимок(склад.root, кроме="ge")

    _вызов(склад, имя, _аргументы(склад, имя, space="am", code="rnd"), tenant=ДРУГОЙ, role="admin")

    assert снимок(склад.root, кроме="ge") == до, f"{имя}: GE изменил чужое"


@pytest.mark.parametrize("имя", sorted(ПРАВКИ))
def test_партнёр_без_кода_не_попадает_в_эталон(склад: Store, имя: str) -> None:
    """Без `checklist` правка партнёра не соскальзывает в применённый к проду эталон."""
    аргументы = {
        к: з
        for к, з in _аргументы(склад, имя, space="hq", code="bizdev").items()
        if к != "checklist"
    }
    до = снимок(склад.root, кроме="am")

    _вызов(склад, имя, аргументы, tenant=ПАРТНЁР, role="admin")

    assert снимок(склад.root, кроме="am") == до


# --- выученные фразы: правка идёт в карту СВОЕГО пространства ------------------------


class _Слой:
    """Подмена слоя синонимов: пишет, с каким пространством его позвали."""

    ALREADY_RETRACTED, ALREADY_POINTED, RESTORED = "already", "pointed", "restored"

    def __init__(self) -> None:
        self.звали: list[str] = []

    def _записать(self, tenant: str) -> Any:
        self.звали.append(tenant)
        raise RuntimeError("стоп: дальше базы тест не идёт")

    def retract_phrase(self, *_: Any, tenant: str, **__: Any) -> Any:
        return self._записать(tenant)

    def repoint_phrase(self, *_: Any, tenant: str, **__: Any) -> Any:
        return self._записать(tenant)


@pytest.mark.parametrize("имя", ["retract_learned_phrase", "repoint_learned_phrase"])
def test_выученные_фразы_партнёр_правит_только_свою_карту(
    склад: Store, имя: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Карта синонимов в базе, ключ — пространство. Его берут из токена, не из аргументов:
    с кодом эталона вызов не доходит до базы, со своим — доходит с пространством AM."""
    слой = _Слой()
    monkeypatch.setattr("src.mcp.phrases._слой", lambda: слой)

    на_эталоне = _вызов(
        склад, имя, _аргументы(склад, имя, space="hq", code="bizdev"), tenant=ПАРТНЁР, role="admin"
    )
    с_чужим_ключом = _вызов(
        склад,
        имя,
        {**_аргументы(склад, имя, space="am", code="rnd"), "tenant": УК},
        tenant=ПАРТНЁР,
        role="admin",
    )
    try:
        _вызов(
            склад, имя, _аргументы(склад, имя, space="am", code="rnd"), tenant=ПАРТНЁР, role="admin"
        )
    except RuntimeError:
        pass

    assert _отказ(на_эталоне) and _отказ(с_чужим_ключом)
    assert слой.звали == [ПАРТНЁР]
