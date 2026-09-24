"""#359: коды нарушений предыдущей проверки точки — основа подсказки о повторе.

Подсказку показывает бот, а решение принимает аудитор: система говорит «такое
же было в прошлый раз», человек решает, повтор это или другое нарушение с тем
же кодом. Поэтому выборка отдаёт ровно факт — какие коды были записаны в
ПРЕДЫДУЩЕЙ проверке, — и ничего не выводит из него сама.

Предыдущая — именно одна, последняя по дате обхода. «Было когда-то за год» —
другое утверждение и другая цена: правило D191 говорит про предыдущую проверку.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import previous_codes  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"


def проверка(chat_id: int, *, unit: str, коды: tuple[str, ...]) -> str:
    start_inspection(chat_id, unit=unit, kind="planned", report_lang="ru")
    for код in коды:
        add_finding(chat_id, code=код, level="D1", zone="hot_kitchen", text="запись")
    return push_inspection(chat_id)


def test_коды_берутся_из_последней_проверки_точки(domain_env: Path, db_env: str) -> None:
    проверка(1, unit="Белград-1", коды=("CLN05",))
    проверка(2, unit="Белград-1", коды=("CLN06",))

    assert previous_codes(tenant=ТЕНАНТ, unit="Белград-1") == {"CLN06"}


def test_чужая_точка_в_подсказку_не_попадает(domain_env: Path, db_env: str) -> None:
    # Подсказка «это уже было» про соседнюю пиццерию — не подсказка, а повод
    # удвоить вычет там, где повтора не было.
    проверка(1, unit="Белград-1", коды=("CLN05",))

    assert previous_codes(tenant=ТЕНАНТ, unit="Белград-2") == set()


def test_без_прошлых_проверок_подсказывать_нечем(domain_env: Path, db_env: str) -> None:
    assert previous_codes(tenant=ТЕНАНТ, unit="Белград-1") == set()


def test_чужой_арендатор_не_виден(domain_env: Path, db_env: str) -> None:
    проверка(1, unit="Белград-1", коды=("CLN05",))

    assert previous_codes(tenant="другой-арендатор", unit="Белград-1") == set()
