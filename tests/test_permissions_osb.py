"""ОСБ и предписания: кто что может — словами решений D599–D608, а не копией матрицы.

Ядро прав (`testing.md`): тесты стоят раньше кода. Таблица `test_permissions_table.py`
сверяет клетки целиком; здесь — смысл: ОСБ читает как гость и не пишет в проверки,
запросить предписание могут четверо, вести его — двое, страницу «ОСБ» видят трое.
Порча этих защит — `tools/porcha_permissions.py`.
"""

from __future__ import annotations

from src.domain import permissions as perm
from src.domain.permissions import ACTIONS, SIDE_HQ, can

HQ = "HQ"


def _can(role: str, code: str, tenant: str = HQ) -> bool:
    return can(perm.Actor(tenant=tenant, role=role), code).allowed


def _роли_с(code: str) -> set[str]:
    return {
        role
        for role in ("superadmin", "admin", "developer", "control", "guest", "osb")
        if _can(role, code)
    }


def test_запросить_предписание_могут_девелопер_админ_осб_и_главный_админ() -> None:
    assert _роли_с("prescription.request") == {"developer", "admin", "osb", "superadmin"}


def test_вести_предписание_могут_только_осб_и_главный_админ() -> None:
    assert _роли_с("prescription.manage") == {"osb", "superadmin"}


def test_страницу_осб_видят_осб_админ_и_главный_админ() -> None:
    assert _роли_с("view.osb") == {"osb", "admin", "superadmin"}


def test_осб_не_пишет_в_проверки_и_вообще_ничего_кроме_предписаний() -> None:
    пишущие = {a.code for a in ACTIONS if a.writes}
    разрешено = {c for c in пишущие if _can("osb", c)}
    # Плюс блок «Договор» карточки страны (D603) — и только он.
    assert разрешено == {"prescription.request", "prescription.manage", "contract.manage"}


def test_осб_читает_как_гость() -> None:
    читает_гость = {a.code for a in ACTIONS if not a.writes and _can("guest", a.code)}
    читает_осб = {a.code for a in ACTIONS if not a.writes and _can("osb", a.code)}
    # Вид «Администрирования» — вкладка «Страны» с договором (D640); других лишних видов нет.
    assert читает_осб == читает_гость | {"view.osb", "view.administration"}


def test_партнёру_ничего_из_предписаний_ведения_не_открыто() -> None:
    for роль in ("admin", "auditor"):
        for код in ("prescription.request", "prescription.manage", "view.osb"):
            assert not _can(роль, код, tenant="GE"), (роль, код)


def test_роль_осб_бывает_только_в_ук() -> None:
    assert (SIDE_HQ, "osb") in perm.MATRIX
    assert ("partner", "osb") not in perm.MATRIX
    assert not perm.grants_of("osb", "GE")


def test_договор_страны_правят_осб_админ_и_главный_админ() -> None:
    assert _роли_с("contract.manage") == {"osb", "admin", "superadmin"}


def test_договор_страны_партнёру_не_открыт_даже_админу_пространства() -> None:
    for роль in ("admin", "auditor"):
        assert not _can(роль, "contract.manage", tenant="GE"), роль


def test_осб_правит_договор_но_не_остальную_карточку_страны() -> None:
    # Девелопер и партнёр страны — `space.manage`; у ОСБ его нет и не появилось.
    assert not _can("osb", "space.manage")
    assert not _can("osb", "ratings.manage")
    assert _can("admin", "space.manage")


def test_договор_страны_только_для_ук_и_пишущее() -> None:
    действие = next(a for a in ACTIONS if a.code == "contract.manage")
    assert действие.hq_only and действие.writes
