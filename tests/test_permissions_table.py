"""Таблица «роль × действие → да/нет» — переписана руками из решений, а не из кода.

Оракул `ОЖИДАНИЕ` собран по решениям владельца (D341, D346, D367, D420, D429,
D440, D448), а не скопирован из `MATRIX`: иначе тест сверял бы матрицу с ней
самой. Расхождение — дефект одного из двух, и тест называет клетку.

Ядро прав — тестами вперёд (`testing.md`): прогон на заведомо сломанной матрице
обязан покраснеть (`tools/porcha_permissions.py`).
"""

from __future__ import annotations

import pytest

from src.domain import permissions as perm
from src.domain.permissions import ACTION_CODES, MATRIX, SIDE_HQ, SIDE_PARTNER, validate_matrix
from src.web.sections import OWN_SECTIONS, SECTIONS

ВИДЫ_ВСЕ = {f"view.{s.key}" for s in SECTIONS if s.key not in OWN_SECTIONS}
# «Страна» открыта и партнёру (D508): экран пиццерии, в пределах его стран.
# «Действия» — один раздел у УК и партнёра (D526): разделов «только УК» среди видов нет.
ВИДЫ_ПАРТНЁРА = ВИДЫ_ВСЕ

РАБОТА_УК = {
    "inspection.read",
    "inspection.conduct",
    "inspection.accept",
    "inspection.revise",
    "inspection.retract",
    "inspection.move",
    "inspection.letter",
    "prescription.manage",
    "plan.manage",
    "ratings.read",
    "unit.create",
    "phrases.raw",
    # Поездки «Календаря» своего пространства (D505, D506).
    "trip.plan",
    "checklist.read",
    "checklist.edit",
    "checklist.publish",
    "checklist.manage",
    "phrases.manage",
}
АДМИН_УК = (
    РАБОТА_УК
    | ВИДЫ_ВСЕ
    | {
        "checklist.master",
        "checklist.apply",
        "inspection.import",
        "ratings.manage",
        "people.manage",
        "people.role",
        "space.manage",
        "refusals.read",
    }
)
СОТРУДНИК_ПАРТНЁРА = ВИДЫ_ПАРТНЁРА | {
    "inspection.read",
    "inspection.conduct",
    "inspection.letter",
    "prescription.reply",
    "plan.submit",
    "checklist.read",
    "ratings.read",
    # Свои поездки — где сам исполнитель (D506).
    "trip.own",
}

ОЖИДАНИЕ: dict[tuple[str, str], set[str]] = {
    # Главный админ = админ + ключи API (D440).
    (SIDE_HQ, "superadmin"): АДМИН_УК | {"api.manage", "keys.manage"},
    (SIDE_HQ, "admin"): АДМИН_УК,
    # Бизнес-девелопер: всё в работе, без главного чек-листа, прода, стран, людей,
    # ключей и загрузок рейтингов (D440); загрузка проверок через Claude — открыта
    # (владелец 20.10.2026), партнёрам закрыта (D335).
    (SIDE_HQ, "developer"): РАБОТА_УК | ВИДЫ_ВСЕ | {"inspection.import"},
    # Контроль: рейтинги и свои люди, роли не меняет (D420, D360).
    (SIDE_HQ, "control"): {
        "ratings.read",
        "ratings.manage",
        "people.manage",
        "view.ratings",
        "view.users",
    },
    # Гость: вся сеть на чтение (D429, D440).
    (SIDE_HQ, "guest"): {
        "inspection.read",
        "ratings.read",
        "view.overview",
        "view.registry",
        "view.calendar",
        "view.country",
        "view.ratings",
        "view.users",
    },
    # Админ партнёра: сотрудник + люди, свои чек-листы, вычитка свежих (D346, D367).
    (SIDE_PARTNER, "admin"): СОТРУДНИК_ПАРТНЁРА
    | {
        "inspection.accept",
        "inspection.revise",
        "checklist.edit",
        "checklist.publish",
        "checklist.manage",
        "checklist.master",
        "phrases.manage",
        "people.manage",
        "people.role",
        "trip.plan",
    },
    (SIDE_PARTNER, "auditor"): СОТРУДНИК_ПАРТНЁРА,
}

ПРОСТРАНСТВО = {SIDE_HQ: "HQ", SIDE_PARTNER: "RS"}


def test_роли_матрицы_совпадают_с_оракулом() -> None:
    assert set(MATRIX) == set(ОЖИДАНИЕ)


@pytest.mark.parametrize("клетка", sorted(ОЖИДАНИЕ), ids=lambda k: f"{k[0]}-{k[1]}")
def test_каждая_клетка_матрицы(клетка: tuple[str, str]) -> None:
    сторона, роль = клетка
    лишнее = sorted(set(MATRIX[клетка]) - ОЖИДАНИЕ[клетка])
    нехватает = sorted(ОЖИДАНИЕ[клетка] - set(MATRIX[клетка]))
    assert not лишнее and not нехватает, f"{сторона}/{роль}: лишнее {лишнее}, нет {нехватает}"


@pytest.mark.parametrize("клетка", sorted(ОЖИДАНИЕ), ids=lambda k: f"{k[0]}-{k[1]}")
def test_can_в_своём_пространстве_повторяет_оракул(клетка: tuple[str, str]) -> None:
    сторона, роль = клетка
    кто = perm.Actor(tenant=ПРОСТРАНСТВО[сторона], role=роль)
    for код in sorted(ACTION_CODES):
        assert perm.can(кто, код).allowed is (код in ОЖИДАНИЕ[клетка]), f"{сторона}/{роль}: {код}"


def test_оракул_не_выдумывает_действий() -> None:
    for клетка, коды in ОЖИДАНИЕ.items():
        assert коды <= ACTION_CODES, (клетка, sorted(коды - ACTION_CODES))


def test_разделы_веба_все_в_каталоге() -> None:
    """Новый раздел без `view.<ключ>` в каталоге — закрыт всем: тест называет его."""
    assert ВИДЫ_ВСЕ <= ACTION_CODES
    assert {c for c in ACTION_CODES if c.startswith("view.")} == ВИДЫ_ВСЕ


def test_матрица_проходит_свою_сверку() -> None:
    assert validate_matrix() == []


def test_сверка_ловит_только_УК_у_партнёра() -> None:
    сломанная = {**MATRIX, (SIDE_PARTNER, "auditor"): {"unit.create", "inspection.read"}}
    assert validate_matrix(сломанная) == [
        "partner/auditor: unit.create — действие только УК (hq_only)"
    ]


def test_сверка_ловит_незнакомый_код_и_только_партнёра_у_УК() -> None:
    сломанная = {(SIDE_HQ, "guest"): {"plan.submit", "inspection.telepathy"}}
    assert validate_matrix(сломанная) == [
        "hq/guest: inspection.telepathy — нет в каталоге действий",
        "hq/guest: plan.submit — действие только партнёра (partner_only)",
    ]


def test_граница_держит_даже_сломанную_матрицу(monkeypatch: pytest.MonkeyPatch) -> None:
    """Галочка «только УК» у партнёра не открывает действие: слой 1 сильнее слоя 2."""
    сломанная = {**MATRIX, (SIDE_PARTNER, "admin"): frozenset(ACTION_CODES)}
    monkeypatch.setattr(perm, "MATRIX", сломанная)
    админ_партнёра = perm.Actor(tenant="RS", role="admin")
    for код in ("unit.create", "space.manage", "inspection.retract", "api.manage", "keys.manage"):
        решение = perm.can(админ_партнёра, код)
        assert (решение.allowed, решение.rule) == (False, perm.RULE_HQ_ONLY), код
    решение = perm.can(админ_партнёра, "checklist.edit", "HQ")
    assert (решение.allowed, решение.rule) == (False, perm.RULE_HQ_OBJECT)
