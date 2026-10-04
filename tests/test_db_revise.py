"""D200: правка записи на приёмке — запись и оценка меняются вместе, у принятой — никак.

Правит только своё пространство (D283): роль приложения одна на всех, поэтому
граница стоит в запросе записи, и тест снимает её проверкой чужим пространством.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import accept_pushed, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db.errors import ReviseError  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.revise import Revision, revise_finding  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402
from src.domain.models import Score  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
УК = own_reach("HQ")

#: Оценку сюда приносит вызывающий — движок её уже посчитал. Числа нарочно
#: непохожие на записанные, чтобы было видно, что легли именно они.
ПЕРЕСЧЁТ = Score(
    pct=88.5,
    grade="B",
    label_ru="Хорошо",
    label_en="Good",
    counts={"D1": 0, "D2": 1, "D3": 0},
    deductions=11.5,
    by_zone={},
)

ИСПРАВЛЕНИЕ = Revision(
    code="CLN05", level="D2", zone="dining", zone_unusual=False, text="грязный пол в зале"
)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> None:
    """Справочник УК: Batumi-1 в Грузии; пространство GE привязано к Грузии."""
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")


def _ждущая(chat_id: int, tenant: str = "HQ") -> tuple[str, str]:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant=tenant)
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="грязный пол в цехе")
    ident = push_inspection(chat_id)
    detail = get_inspection(ident, reach=own_reach(tenant), include_on_review=True)
    assert detail is not None
    return ident, detail.findings[0].id


def test_правка_меняет_запись_и_оценку_вместе(сеть: None) -> None:
    # Arrange
    ident, запись = _ждущая(601)

    # Act
    revise_finding(ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, score=ПЕРЕСЧЁТ)

    # Assert
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None
    [f] = после.findings
    assert (f.code, f.level, f.zone, f.text) == ("CLN05", "D2", "dining", "грязный пол в зале")
    assert (после.inspection.pct, после.inspection.grade, после.deductions) == (88.5, "B", 11.5)
    assert после.counts == {"D1": 0, "D2": 1, "D3": 0}


def test_у_принятой_правка_закрыта(сеть: None, db_env: str) -> None:
    # Arrange
    ident, запись = _ждущая(602)
    accept_pushed(ident, dsn=db_env)

    # Act / Assert
    with pytest.raises(ReviseError, match="уже принята"):
        revise_finding(ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, score=ПЕРЕСЧЁТ)
    после = get_inspection(ident, reach=УК)
    assert после is not None and после.findings[0].zone == "hot_kitchen"


def test_занятая_пара_пункт_зона_отклоняется(сеть: None) -> None:
    # Arrange — в цехе уже две записи разных пунктов.
    start_inspection(603, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(603, code="CLN05", level="D1", zone="hot_kitchen", text="пол в цехе")
    add_finding(603, code="CLN06", level="D1", zone="hot_kitchen", text="стены в цехе")
    ident = push_inspection(603)
    detail = get_inspection(ident, reach=УК, include_on_review=True)
    assert detail is not None
    стены = next(f for f in detail.findings if f.code == "CLN06")
    в_занятую = Revision(
        code="CLN05", level="D1", zone="hot_kitchen", zone_unusual=False, text="пол в цехе"
    )

    # Act / Assert — CLN05 в цехе уже записан первой записью.
    with pytest.raises(ReviseError, match="уже записан"):
        revise_finding(ident, стены.id, tenant="HQ", revision=в_занятую, score=ПЕРЕСЧЁТ)


@pytest.mark.parametrize(("владелец", "правит"), [("GE", "HQ"), ("HQ", "GE")])
def test_чужое_пространство_не_правит(сеть: None, владелец: str, правит: str) -> None:
    """УК читает проверки партнёра, но не правит их; партнёр не правит проверки УК."""
    # Arrange
    ident, запись = _ждущая(604, tenant=владелец)

    # Act / Assert
    with pytest.raises(ReviseError, match="нет"):
        revise_finding(ident, запись, tenant=правит, revision=ИСПРАВЛЕНИЕ, score=ПЕРЕСЧЁТ)
    после = get_inspection(ident, reach=own_reach(владелец), include_on_review=True)
    assert после is not None and после.findings[0].zone == "hot_kitchen"
    assert после.inspection.pct != ПЕРЕСЧЁТ.pct
