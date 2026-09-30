"""#359, D255: предыдущая проверка точки и её нарушения — основа вопроса о повторе.

Вопрос задаёт бот, а решение принимает проверяющий: система говорит «такое же
было в прошлый раз (дата)», человек решает, повтор это или другое нарушение с
тем же кодом. Поэтому выборка отдаёт ровно факт — когда была ПРЕДЫДУЩАЯ
проверка и какие коды были в ней нарушениями, — и ничего не выводит из него сама.

Предыдущая — именно одна, последняя по дате обхода. «Было когда-то за год» —
другое утверждение и другая цена: правило D191 говорит про предыдущую проверку.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import previous_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"


def проверка(chat_id: int, *, unit: str, коды: tuple[str, ...], day: str | None = None) -> str:
    start_inspection(chat_id, unit=unit, kind="planned", report_lang="ru", date=day)
    for код in коды:
        add_finding(chat_id, code=код, level="D1", zone="hot_kitchen", text="запись")
    return push_inspection(chat_id)


def коды(tenant: str, unit: str) -> frozenset[str] | None:
    прошлая = previous_inspection(tenant=tenant, unit=unit)
    return None if прошлая is None else прошлая.codes


def test_коды_берутся_из_последней_проверки_точки(domain_env: Path, db_env: str) -> None:
    проверка(1, unit="Белград-1", коды=("CLN05",), day="2026-09-01")
    проверка(2, unit="Белград-1", коды=("CLN06",), day="2026-09-15")

    прошлая = previous_inspection(tenant=ТЕНАНТ, unit="Белград-1")
    assert прошлая is not None
    assert прошлая.codes == {"CLN06"}
    assert прошлая.date.isoformat() == "2026-09-15", "в вопросе была бы не та дата"


def test_прошлая_проверка_без_нарушений_не_пропадает(domain_env: Path, db_env: str) -> None:
    # Чистая последняя проверка — это «в прошлый раз нарушений не было», а не
    # «прошлой проверки нет»: иначе вопрос достал бы код из позапрошлой.
    проверка(1, unit="Белград-1", коды=("CLN05",), day="2026-09-01")
    проверка(2, unit="Белград-1", коды=(), day="2026-09-15")

    assert коды(ТЕНАНТ, "Белград-1") == frozenset()


def test_чужая_точка_в_подсказку_не_попадает(domain_env: Path, db_env: str) -> None:
    # Подсказка «это уже было» про соседнюю пиццерию — не подсказка, а повод
    # удвоить вычет там, где повтора не было.
    проверка(1, unit="Белград-1", коды=("CLN05",))

    assert коды(ТЕНАНТ, "Белград-2") is None


def test_без_прошлых_проверок_подсказывать_нечем(domain_env: Path, db_env: str) -> None:
    assert коды(ТЕНАНТ, "Белград-1") is None


def test_чужой_арендатор_не_виден(domain_env: Path, db_env: str) -> None:
    проверка(1, unit="Белград-1", коды=("CLN05",))

    assert коды("другой-арендатор", "Белград-1") is None


def test_замер_нарушением_не_считается(domain_env: Path, db_env: str) -> None:
    # D0 — информационная запись без вычета: спрашивать «считать повтором ×2?»
    # про замер температуры значило бы предлагать удвоить ноль.
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(1, code="INF10", level="D0", zone="fridge", text="замер")
    add_finding(1, code="CLN05", level="D1", zone="hot_kitchen", text="запись")
    push_inspection(1)

    assert коды(ТЕНАНТ, "Белград-1") == {"CLN05"}
