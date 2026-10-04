"""D199: проверки, принятые до этапа приёмки, живут после `0034` как прежде.

На проде лежат проверки, которые слив запечатал сам: `status = 'finalized'`, а
`accepted_at`/`accepted_by` пусты — колонок тогда не было. Миграция их не
трогает. Тест держит, что ни история, ни отклонение, ни перенос не упираются
в новый триггер и в новые ограничения.

Такую строку воспроизводим ровно так, как она возникла: слив кладёт черновик,
а печать ставится без отметки о приёмке. Нынешний продуктовый путь сделать
так не даёт (на то и триггер), поэтому на время печати владелец таблицы
выключает триггер приёмки — в одной транзакции с самой печатью.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import AcceptError  # noqa: E402
from src.db.move import move_inspection  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection, list_inspections, unit_ids  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.retract import retract_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Белград-1"
ДРУГАЯ = "Белград-2"
СВОИ = own_reach("default")


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _слить(chat_id: int, *, точка: str = ТОЧКА) -> str:
    start_inspection(chat_id, unit=точка, kind="planned", report_lang="ru", tenant="default")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(chat_id)


def _как_до_приёмки(pg_dsn: str, ident: str) -> None:
    """Печать без отметки о приёмке — та строка, что лежит на проде с до `0034`."""
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("alter table inspections disable trigger inspections_acceptance_guarded")
        conn.execute("update inspections set status = 'finalized' where id = %s", (ident,))
        conn.execute("alter table inspections enable trigger inspections_acceptance_guarded")
        conn.commit()
        row = conn.execute(
            "select status, accepted_at, accepted_by from inspections where id = %s", (ident,)
        ).fetchone()
    assert row == ("finalized", None, None), "строка не похожа на принятую до этапа приёмки"


def _прежняя(pg_dsn: str, chat_id: int, *, точка: str = ТОЧКА) -> str:
    ident = _слить(chat_id, точка=точка)
    _как_до_приёмки(pg_dsn, ident)
    return ident


def test_прежняя_проверка_в_истории_с_пустой_отметкой(
    domain_env: Path, admin_env: str, pg_dsn: str
) -> None:
    # Arrange
    ident = _прежняя(pg_dsn, 1201)

    # Act
    история = list_inspections(reach=СВОИ)
    карточка = get_inspection(ident, reach=СВОИ)

    # Assert
    assert [i.id for i in история] == [ident]
    assert карточка is not None
    assert карточка.inspection.on_review is False
    assert (карточка.inspection.accepted_at, карточка.inspection.accepted_by) == ("", "")


def test_прежнюю_проверку_можно_отклонить(domain_env: Path, admin_env: str, pg_dsn: str) -> None:
    # Arrange
    ident = _прежняя(pg_dsn, 1202)

    # Act
    retract_inspection(ident, tenant="default", reason="дубль")

    # Assert
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select status, retracted_at is not null, accepted_at from inspections where id = %s",
            (ident,),
        ).fetchone()
    assert row == ("finalized", True, None)


def test_прежнюю_проверку_можно_перенести(domain_env: Path, admin_env: str, pg_dsn: str) -> None:
    # Arrange
    ident = _прежняя(pg_dsn, 1203)
    _прежняя(pg_dsn, 1204, точка=ДРУГАЯ)  # заводит вторую точку в справочнике

    # Act
    изменено = move_inspection(
        ident,
        tenant="default",
        new_date=date(2026, 9, 1),
        new_unit_id=unit_ids(reach=СВОИ)[ДРУГАЯ],
        reason="аудитор выбрал не ту точку",
        actor="admin",
    )

    # Assert
    после = get_inspection(ident, reach=СВОИ)
    assert изменено is True
    assert после is not None
    assert (после.inspection.unit_name, после.inspection.accepted_at) == (ДРУГАЯ, "")


def test_прежнюю_проверку_повторно_не_подтверждают(
    domain_env: Path, admin_env: str, pg_dsn: str
) -> None:
    # Arrange
    ident = _прежняя(pg_dsn, 1205)

    # Act / Assert — отметку задним числом не ставят, строка не меняется.
    with pytest.raises(AcceptError):
        accept_inspection(ident, tenant="default", actor="admin")
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select accepted_at, accepted_by from inspections where id = %s", (ident,)
        ).fetchone()
    assert row == (None, None)
