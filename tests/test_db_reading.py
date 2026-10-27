"""#855 (D495): показание термометра переживает сдачу и правится на вычитке.

Число — факт проверки: аудитор подтвердил или исправил его на точке (#836).
Потерянное при сливе, оно молча исчезает из сданной проверки, а заменённое
правкой на вычитке — обязано лечь в базу, а не остаться прежним.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import accept_pushed, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db.inspection_edits import Editor  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.revise import Revision, revise_finding  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402
from src.domain.models import Score  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
УК = own_reach("HQ")
ОЦЕНКА = Score(pct=99.0, grade="A", label_ru="", label_en="", counts={}, deductions=1.0, by_zone={})


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> None:
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")


def _проверка(chat_id: int, reading_c: float | None) -> str:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(
        chat_id,
        code="CLN05",
        level="D1",
        zone="hot_kitchen",
        text="про градусы",
        reading_c=reading_c,
    )
    return push_inspection(chat_id)


def _показание(ident: str) -> float | None:
    detail = get_inspection(ident, reach=УК, include_on_review=True)
    assert detail is not None
    return detail.findings[0].reading_c


def test_слив_переносит_показание(сеть: None) -> None:
    ident = _проверка(801, 26.5)

    assert _показание(ident) == 26.5


def test_без_замера_показания_нет(сеть: None) -> None:
    ident = _проверка(802, None)

    assert _показание(ident) is None


def test_показание_видно_у_принятой(сеть: None) -> None:
    ident = _проверка(803, 4.0)
    accept_pushed(ident)

    detail = get_inspection(ident, reach=УК)

    assert detail is not None and detail.findings[0].reading_c == 4.0


@pytest.mark.parametrize("новое", [6.0, None])
def test_правка_на_вычитке_пишет_показание(сеть: None, новое: float | None) -> None:
    ident = _проверка(804, 26.0)
    detail = get_inspection(ident, reach=УК, include_on_review=True)
    assert detail is not None
    запись = detail.findings[0]

    revise_finding(
        ident,
        запись.id,
        tenant="HQ",
        editor=Editor(
            user_id="00000000-0000-0000-0000-0000000000a1", login="kontroling", role="admin"
        ),
        revision=Revision(
            code=запись.code,
            level=запись.level,
            zone=запись.zone,
            zone_unusual=False,
            text="про градусы",
            reading_c=новое,
        ),
        score_of=lambda _d: ОЦЕНКА,
    )

    assert _показание(ident) == новое


def test_язык_речи_проверки_читается_с_карточкой(сеть: None) -> None:
    """D663: письмо сверяет язык обратной связи аудитора с языком письма — по `speech_lang`."""
    start_inspection(
        805, unit=ТОЧКА, kind="planned", report_lang="en", speech_lang="ru", tenant="HQ"
    )
    add_finding(805, code="CLN05", level="D1", zone="hot_kitchen", text="про градусы")
    ident = push_inspection(805)

    detail = get_inspection(ident, reach=УК, include_on_review=True)

    assert detail is not None
    assert detail.inspection.report_lang == "en"
    assert detail.inspection.speech_lang == "ru", (
        "язык речи не дочитан: письмо угадает его по находкам"
    )
