"""Волна 3: проверка начинается по чек-листу из открытых в боте и идёт по его снимку.

Ядро — тихая подмена чек-листа. Проверка «rnd», которую считают по методике
«bizdev», даёт партнёру чужие вопросы и чужую оценку без единой ошибки на
экране. Поэтому сторожится не «функция отработала», а по какому каталогу
методики пошла проверка и что бывает, когда снимка нет.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.domain import edition, get_state, list_items, start_inspection
from src.domain.bot_checklists import DEFAULT_CODE, available, pick
from src.domain.config import check_environment
from src.domain.engine import DOMAIN_KEY, state_file
from src.domain.errors import ChecklistVersionMismatch, DomainError
from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, apply_change, current_version, publish
from src.mcp.checklists import create, set_bot_access, set_state

CHAT = 7301
АРЕНДАТОР = "укашка"
СЕГОДНЯ = date(2026, 9, 28)


@pytest.fixture
def методика(data_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data_copy))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("MCP_CHECKLIST_STORE", raising=False)
    monkeypatch.chdir(tmp_path)
    return data_copy


@pytest.fixture
def хранилище(методика: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """Хранилище, где в боте открыты bizdev и rnd (у rnd один свой пункт)."""
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    rnd = replace(store, code="rnd")
    create(rnd, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD audit", today=СЕГОДНЯ)
    правка = apply_change(
        rnd,
        tenant=АРЕНДАТОР,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Тесто соответствует техкарте",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(rnd, tenant=АРЕНДАТОР, version=правка.version)
    set_state(rnd, tenant=АРЕНДАТОР, state="active")
    set_bot_access(rnd, tenant=АРЕНДАТОР, on=True)
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    return store


def _начать(code: str | None = None) -> None:
    start_inspection(CHAT, unit="Тестовая", kind="planned", report_lang="ru", checklist_code=code)


def test_без_хранилища_чек_лист_один_и_проверка_как_раньше(методика: Path) -> None:
    открыты = available(check_environment(), tenant=HQ_TENANT)
    assert [(c.code, c.source) for c in открыты] == [(DEFAULT_CODE, методика)]

    _начать()

    состояние = get_state(CHAT)
    assert состояние is not None and состояние.checklist_code == DEFAULT_CODE


def test_несколько_открытых_без_кода_это_отказ(хранилище: Store) -> None:
    assert [c.code for c in available(check_environment(), tenant=HQ_TENANT)] == ["rnd", "bizdev"]

    with pytest.raises(DomainError, match="несколько"):
        _начать()


def test_проверка_идёт_по_методике_выбранного_чек_листа(хранилище: Store) -> None:
    _начать("rnd")

    состояние = get_state(CHAT)
    assert состояние is not None and состояние.checklist_code == "rnd"
    assert [i.code for i in list_items(chat_id=CHAT)] == ["RND01"], (
        "проверка rnd получила вопросы bizdev"
    )
    каталог = edition.data_dir(CHAT, check_environment())
    assert каталог.parent == edition.shelf(check_environment(), "rnd")


def test_закрытый_в_боте_не_начинается(хранилище: Store) -> None:
    set_bot_access(replace(хранилище, code="rnd"), tenant=АРЕНДАТОР, on=False)

    with pytest.raises(DomainError, match="больше не открыт"):
        pick(check_environment(), "rnd", tenant=HQ_TENANT)


def test_закрыли_посреди_проверки_она_идёт_по_снимку(хранилище: Store) -> None:
    _начать("rnd")

    set_bot_access(replace(хранилище, code="rnd"), tenant=АРЕНДАТОР, on=False)

    assert [i.code for i in list_items(chat_id=CHAT)] == ["RND01"]


def test_пропал_снимок_не_дефолтного_чек_листа_это_отказ(хранилище: Store) -> None:
    """Молча считать rnd по bizdev нельзя: отказ с понятным текстом."""
    _начать("rnd")
    shutil.rmtree(edition.shelf(check_environment(), "rnd"))

    with pytest.raises(ChecklistVersionMismatch, match="rnd"):
        edition.data_dir(CHAT, check_environment())


def test_проверка_до_волны_три_без_кода_это_bizdev(методика: Path) -> None:
    _начать()
    путь = state_file(CHAT, check_environment())
    сырое = json.loads(путь.read_text(encoding="utf-8"))
    сырое[DOMAIN_KEY].pop("checklist_code")
    путь.write_text(json.dumps(сырое, ensure_ascii=False), encoding="utf-8")

    assert edition.recorded_code(CHAT, check_environment()) == DEFAULT_CODE
    assert list_items(chat_id=CHAT), "старая проверка потеряла свою методику"


def test_ни_одного_открытого_бот_прямо_говорит(хранилище: Store) -> None:
    set_bot_access(replace(хранилище, code="rnd"), tenant=АРЕНДАТОР, on=False)
    set_bot_access(хранилище, tenant=АРЕНДАТОР, on=False)

    with pytest.raises(DomainError, match="не по чему"):
        _начать()


def test_опубликовали_пустое_издание_открытого_бот_его_не_даёт(хранилище: Store) -> None:
    """Заслон пустоты стоит и на чтении, а не только на переключателе.

    Флаг «в боте» ставится один раз, а издания публикуются потом сколько угодно.
    Пустое издание открытого чек-листа дало бы проверку без единого вопроса —
    и 100% с высшей оценкой партнёру.
    """
    rnd = replace(хранилище, code="rnd")
    правка = apply_change(
        rnd,
        tenant=АРЕНДАТОР,
        tool="remove_checklist_item",
        command="remove",
        positional="RND01",
        options={},
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(rnd, tenant=АРЕНДАТОР, version=правка.version)

    assert [c.code for c in available(check_environment(), tenant=HQ_TENANT)] == ["bizdev"]
    with pytest.raises(DomainError, match="больше не открыт"):
        _начать("rnd")
