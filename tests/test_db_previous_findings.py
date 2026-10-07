"""#418: прошлая проверка точки вместе с формулировками — подсказка «здесь было».

Мини-апп обхода показывает аудитору, что и где записали в прошлый раз. Та же
прошлая проверка, что у вопроса о повторе (`previous_inspection`): если две
подсказки опираются на разные обходы, аудитор получит два разных прошлых.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import previous_findings, previous_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"


def test_отдаёт_последнюю_проверку_с_зонами_классами_и_словами(
    domain_env: Path, db_env: str
) -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", date="2026-09-01")
    add_finding(1, code="CLN05", level="D1", zone="hot_kitchen", text="старое")
    push_inspection(1)
    start_inspection(2, unit="Белград-1", kind="planned", report_lang="ru", date="2026-09-15")
    add_finding(2, code="PRD09", level="D2", zone="fridge", text="контейнеры без даты")
    add_finding(2, code="INF10", level="D0", zone="fridge", text="замер")
    push_inspection(2)

    прошлая = previous_findings(tenant=ТЕНАНТ, unit="Белград-1")

    assert прошлая is not None
    assert прошлая.date.isoformat() == "2026-09-15"
    assert [(f.code, f.level, f.zone, f.text) for f in прошлая.findings] == [
        ("PRD09", "D2", "fridge", "контейнеры без даты")
    ], "замер (D0) не нарушение, а позапрошлая проверка — не прошлая"
    повтор = previous_inspection(tenant=ТЕНАНТ, unit="Белград-1")
    assert повтор is not None and повтор.date == прошлая.date, "подсказки смотрят в разные обходы"


def test_чистая_прошлая_проверка_это_пустой_список_а_не_её_отсутствие(
    domain_env: Path, db_env: str
) -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", date="2026-09-15")
    push_inspection(1)

    прошлая = previous_findings(tenant=ТЕНАНТ, unit="Белград-1")

    assert прошлая is not None and прошлая.findings == ()


def test_чужая_точка_и_чужой_арендатор_не_видны(domain_env: Path, db_env: str) -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(1, code="CLN05", level="D1", zone="hot_kitchen", text="запись")
    push_inspection(1)

    assert previous_findings(tenant=ТЕНАНТ, unit="Белград-2") is None
    assert previous_findings(tenant="другой-арендатор", unit="Белград-1") is None
