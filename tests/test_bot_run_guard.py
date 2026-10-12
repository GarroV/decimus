"""D392: память бота сверяется с личностью проверки (`bot/run_guard.py`).

Проверку может начать мини-апп — другой процесс, до памяти бота ему не
дотянуться. Хранилище, не заметившее смены, отдало бы новой проверке кнопки и
слова прежней. Здесь — сама сверка на подменяемой личности; настоящий старт из
мини-аппа проверен в `test_web_walk_start.py`.
"""

from __future__ import annotations

from src.bot.material import Comment, MaterialStore
from src.bot.pending import PendingStore, Proposal
from src.bot.unit_pick import (
    UNIT_KNOWN,
    UNIT_NEW,
    UNIT_PARTNER_REFUSED,
    UnitMatch,
    resolve_unit,
)
from src.domain.unit_name import (
    PROBLEM_NEED_NUMBER,
    PROBLEM_TOO_LONG,
    PROBLEM_TOO_LONG_BYTES,
    UNIT_NAME_LIMIT,
    canonical_unit,
    check_unit_name,
)

ЧАТ = 7


class Личность:
    """Подменяемая личность проверки: то, что в жизни лежит в `inspection.json`."""

    def __init__(self, run: str) -> None:
        self.run = run

    def __call__(self, _chat_id: int) -> str:
        return self.run


def _предложение() -> Proposal:
    return Proposal(file_ids=("f1",), source="comment", slot=1)


def test_смена_личности_сбрасывает_предложения() -> None:
    личность = Личность("A")
    pending = PendingStore(личность)
    pending.propose(ЧАТ, _предложение(), at=10)

    личность.run = "B"

    assert pending.proposal(ЧАТ, at=10) is None


def test_та_же_личность_ничего_не_сбрасывает() -> None:
    pending = PendingStore(Личность("A"))
    pending.propose(ЧАТ, _предложение(), at=10)

    assert pending.proposal(ЧАТ, at=10) is not None


def test_смена_личности_сбрасывает_придержанные_слова() -> None:
    личность = Личность("A")
    store = MaterialStore(личность)
    store.queue(ЧАТ).hold_comment(Comment(text="слова старой проверки"))

    личность.run = "B"

    assert store.queue(ЧАТ).held_comments() == ()


def test_чужой_чат_не_страдает() -> None:
    личность = Личность("A")
    pending = PendingStore(личность)
    pending.propose(ЧАТ, _предложение(), at=10)

    другой = pending.proposal(ЧАТ + 1, at=10)

    assert другой is None and pending.proposal(ЧАТ, at=10) is not None


def test_без_сверки_хранилища_работают_как_раньше() -> None:
    pending = PendingStore()
    pending.propose(ЧАТ, _предложение(), at=10)

    assert pending.proposal(ЧАТ, at=10) is not None


# ── общая проверка названия: бот и мини-апп отказывают одинаково ─────────


def test_название_без_номера_отказ() -> None:
    assert check_unit_name("Белград").problem == PROBLEM_NEED_NUMBER


def test_название_слишком_длинное_в_знаках_и_в_байтах() -> None:
    assert check_unit_name("Б" * (UNIT_NAME_LIMIT + 1)).problem == PROBLEM_TOO_LONG
    assert check_unit_name("😀" * UNIT_NAME_LIMIT).problem == PROBLEM_TOO_LONG_BYTES


def test_название_сводится_к_каноничному() -> None:
    проверка = check_unit_name(" белград 1 ")

    assert проверка.name == canonical_unit("Белград-1") and проверка.problem == ""


# ── решение по названию после сверки ─────────────────────────────────────


def test_решение_по_названию() -> None:
    имя = canonical_unit("Белград-1")
    assert имя is not None
    знаю = UnitMatch(name="Belgrade-1", suggestions=(), checked=True)
    не_знаю = UnitMatch(name=None, suggestions=(), checked=True)
    нет_справочника = UnitMatch(name=None, suggestions=(), checked=False)

    assert resolve_unit(имя, знаю, "GE").status == UNIT_KNOWN
    assert resolve_unit(имя, нет_справочника, "GE").status == UNIT_KNOWN
    assert resolve_unit(имя, не_знаю, "GE").status == UNIT_PARTNER_REFUSED
    assert resolve_unit(имя, не_знаю, "HQ").status == UNIT_NEW
