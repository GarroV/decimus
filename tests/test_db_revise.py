"""D200: правка записи на приёмке — запись и оценка меняются вместе, у принятой — никак.

Правит только своё пространство (D283): роль приложения одна на всех, поэтому
граница стоит в запросе записи, и тест снимает её проверкой чужим пространством.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import accept_pushed, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db.errors import ReviseError  # noqa: E402
from src.db.inspection_edits import Editor  # noqa: E402
from src.db.models import InspectionDetail  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.review_edit import Addition  # noqa: E402
from src.db.review_edit import add_finding as add_review_finding  # noqa: E402
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

ПРАВИТ = Editor(user_id="00000000-0000-0000-0000-0000000000a1", login="kontroling", role="admin")

ИСПРАВЛЕНИЕ = Revision(
    code="CLN05", level="D2", zone="dining", zone_unusual=False, text="грязный пол в зале"
)


def _по(оценка: Score) -> Callable[[InspectionDetail], Score]:
    """Движок, который всегда отвечает одной и той же оценкой."""
    return lambda _detail: оценка


def _считать_d2(detail: InspectionDetail) -> Score:
    """Подставной движок: минус 10 за каждую запись D2 — видно, от каких записей посчитано."""
    d2 = sum(1 for f in detail.findings if f.level == "D2")
    return Score(
        pct=100.0 - 10 * d2,
        grade="A",
        label_ru="",
        label_en="",
        counts={"D1": len(detail.findings) - d2, "D2": d2, "D3": 0},
        deductions=10.0 * d2,
        by_zone={},
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
    revise_finding(
        ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
    )

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
        revise_finding(
            ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
        )
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
        revise_finding(
            ident, стены.id, tenant="HQ", revision=в_занятую, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
        )


@pytest.mark.parametrize(("владелец", "правит"), [("GE", "HQ"), ("HQ", "GE")])
def test_чужое_пространство_не_правит(сеть: None, владелец: str, правит: str) -> None:
    """УК читает проверки партнёра, но не правит их; партнёр не правит проверки УК."""
    # Arrange
    ident, запись = _ждущая(604, tenant=владелец)

    # Act / Assert
    with pytest.raises(ReviseError, match="нет"):
        revise_finding(
            ident,
            запись,
            tenant=правит,
            revision=ИСПРАВЛЕНИЕ,
            editor=ПРАВИТ,
            score_of=_по(ПЕРЕСЧЁТ),
        )
    после = get_inspection(ident, reach=own_reach(владелец), include_on_review=True)
    assert после is not None and после.findings[0].zone == "hot_kitchen"
    assert после.inspection.pct != ПЕРЕСЧЁТ.pct


def test_две_правки_одной_проверки_не_теряют_друг_друга(сеть: None) -> None:
    """Ядро: в отчёт уходит оценка, посчитанная по ОБЕИМ правкам, а не по одной.

    Первая правка держит транзакцию открытой, пока вторая уже начала свою. Без
    сериализации вторая посчитала бы от снимка без первой правки — и её оценка
    легла бы последней.
    """
    # Arrange — две записи D1 в разных зонах.
    start_inspection(605, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(605, code="CLN05", level="D1", zone="hot_kitchen", text="пол в цехе")
    add_finding(605, code="CLN06", level="D1", zone="hot_kitchen", text="стены в цехе")
    ident = push_inspection(605)
    detail = get_inspection(ident, reach=УК, include_on_review=True)
    assert detail is not None
    пол, стены = sorted(detail.findings, key=lambda f: f.code)
    первая_внутри, вторая_посчитала = threading.Event(), threading.Event()
    ошибки: list[BaseException] = []

    def медленный_движок(current: InspectionDetail) -> Score:
        # Первая держит транзакцию, пока вторая не дойдёт до движка. С замком
        # вторая до движка не дойдёт (ждёт замка) — ожидание истечёт; без
        # замка она посчитает от снимка без первой правки — и это поймается.
        первая_внутри.set()
        вторая_посчитала.wait(timeout=5)
        return _считать_d2(current)

    def второй_движок(current: InspectionDetail) -> Score:
        оценка = _считать_d2(current)
        вторая_посчитала.set()
        return оценка

    def правка(запись: str, код: str, движок: Callable[[InspectionDetail], Score]) -> None:
        try:
            revise_finding(
                ident,
                запись,
                tenant="HQ",
                revision=Revision(
                    code=код, level="D2", zone="hot_kitchen", zone_unusual=False, text="d2"
                ),
                editor=ПРАВИТ,
                score_of=движок,
            )
        except BaseException as exc:  # поток отдаёт ошибку тесту
            ошибки.append(exc)

    первый = threading.Thread(target=правка, args=(пол.id, "CLN05", медленный_движок))

    # Act
    первый.start()
    assert первая_внутри.wait(timeout=10), "первая правка не дошла до пересчёта"
    второй = threading.Thread(target=правка, args=(стены.id, "CLN06", второй_движок))
    второй.start()
    первый.join(timeout=30)
    второй.join(timeout=30)

    # Assert
    assert ошибки == []
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None
    assert sorted(f.level for f in после.findings) == ["D2", "D2"]
    assert после.inspection.pct == 80.0, "оценка посчитана без одной из правок"


def test_правка_без_задетой_записи_не_пишет_оценку(
    сеть: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись не обновилась — оценка тоже не ложится, отказ понятен."""
    # Arrange
    import src.db.revise as revise_module

    ident, запись = _ждущая(606)
    до = get_inspection(ident, reach=УК, include_on_review=True)
    assert до is not None
    monkeypatch.setattr(
        revise_module,
        "_UPDATE_FINDING_SQL",
        revise_module._UPDATE_FINDING_SQL.rstrip() + " and false\n",
    )

    # Act / Assert
    with pytest.raises(ReviseError, match="Запись не исправлена"):
        revise_finding(
            ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
        )
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None and после.inspection.pct == до.inspection.pct


# --- журнал правок (F-134, #1006) ---------------------------------------------


def _журнал(pg_dsn: str, ident: str) -> list[dict[str, Any]]:
    """Строки журнала правок проверки — под владельцем: роль приложения их не читает."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select finding_id::text, tenant_code, user_id::text, login, role, kind, changes, "
            "occurred_at is not null from inspection_edits where inspection_id = %s order by id",
            (ident,),
        )
        return [
            {
                "finding": r[0],
                "tenant": r[1],
                "user": r[2],
                "login": r[3],
                "role": r[4],
                "kind": r[5],
                "changes": r[6],
                "timed": r[7],
            }
            for r in cur.fetchall()
        ]


def _одна_строка(pg_dsn: str, ident: str) -> dict[str, Any]:
    журнал = _журнал(pg_dsn, ident)
    assert len(журнал) == 1, f"правка не оставила следа в журнале: строк {len(журнал)}, ждали 1"
    return журнал[0]


def test_правка_пишет_в_журнал_кто_что_и_было_стало(сеть: None, pg_dsn: str) -> None:
    # Arrange
    ident, запись = _ждущая(610)
    до = get_inspection(ident, reach=УК, include_on_review=True)
    assert до is not None

    # Act
    revise_finding(
        ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
    )

    # Assert
    строка = _одна_строка(pg_dsn, ident)
    assert (строка["finding"], строка["tenant"], строка["kind"]) == (запись, "HQ", "revise")
    assert (строка["user"], строка["login"], строка["role"]) == (
        ПРАВИТ.user_id,
        "kontroling",
        "admin",
    )
    assert строка["timed"] is True
    изменения = строка["changes"]
    assert изменения["level"] == {"old": "D1", "new": "D2"}
    assert изменения["zone"] == {"old": "hot_kitchen", "new": "dining"}
    assert изменения["text"] == {"old": "грязный пол в цехе", "new": "грязный пол в зале"}
    assert "code" not in изменения, "код не менялся — в журнал не идёт"
    assert изменения["score_pct"] == {"old": до.inspection.pct, "new": 88.5}
    assert изменения["score_grade"] == {"old": до.inspection.grade, "new": "B"}
    assert изменения["score_deductions"] == {"old": до.deductions, "new": 11.5}


def test_правка_партнёра_тоже_в_журнале(сеть: None, pg_dsn: str) -> None:
    """Вычитка одинакова для УК и партнёра (решение владельца): след — у обоих."""
    # Arrange
    ident, запись = _ждущая(611, tenant="GE")
    партнёр = Editor(
        user_id="00000000-0000-0000-0000-0000000000b2", login="geo-admin", role="admin"
    )

    # Act
    revise_finding(
        ident, запись, tenant="GE", revision=ИСПРАВЛЕНИЕ, editor=партнёр, score_of=_по(ПЕРЕСЧЁТ)
    )

    # Assert
    строка = _одна_строка(pg_dsn, ident)
    assert (строка["tenant"], строка["login"], строка["kind"]) == ("GE", "geo-admin", "revise")
    assert строка["changes"]["level"] == {"old": "D1", "new": "D2"}


def test_несколько_правок_дают_несколько_строк_по_порядку(сеть: None, pg_dsn: str) -> None:
    # Arrange
    ident, запись = _ждущая(612)
    вторая = Revision(
        code="CLN05", level="D3", zone="dining", zone_unusual=False, text="грязный пол в зале"
    )

    # Act
    revise_finding(
        ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
    )
    revise_finding(
        ident, запись, tenant="HQ", revision=вторая, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
    )

    # Assert — вторая правка помнит результат первой как «было».
    журнал = _журнал(pg_dsn, ident)
    assert len(журнал) == 2, f"две правки — две строки в журнале, а их {len(журнал)}"
    первая_строка, вторая_строка = журнал
    assert первая_строка["changes"]["level"] == {"old": "D1", "new": "D2"}
    assert вторая_строка["changes"]["level"] == {"old": "D2", "new": "D3"}
    assert "zone" not in вторая_строка["changes"]


def test_правка_принятой_закрыта_и_следа_не_оставляет(сеть: None, db_env: str, pg_dsn: str) -> None:
    # Arrange
    ident, запись = _ждущая(613)
    accept_pushed(ident, dsn=db_env)

    # Act / Assert — гейт приёмки на месте, журнал пуст.
    with pytest.raises(ReviseError, match="уже принята"):
        revise_finding(
            ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=_по(ПЕРЕСЧЁТ)
        )
    assert _журнал(pg_dsn, ident) == []


def test_отказ_правки_не_оставляет_строки_в_журнале(сеть: None, pg_dsn: str) -> None:
    """Движок упал — ни правки, ни следа: они в одной транзакции."""
    # Arrange
    ident, запись = _ждущая(614)

    def упавший(_detail: InspectionDetail) -> Score:
        raise RuntimeError("движок упал")

    # Act / Assert
    with pytest.raises(RuntimeError):
        revise_finding(
            ident, запись, tenant="HQ", revision=ИСПРАВЛЕНИЕ, editor=ПРАВИТ, score_of=упавший
        )
    assert _журнал(pg_dsn, ident) == []


def test_без_названной_учётки_правка_не_проходит_и_запись_не_меняется(
    сеть: None, pg_dsn: str
) -> None:
    """След без автора не пишется, а правка без следа не бывает: отказ целиком."""
    # Arrange
    ident, запись = _ждущая(615)
    безымянный = Editor(user_id=ПРАВИТ.user_id, login="  ", role="admin")

    # Act / Assert
    with pytest.raises(ReviseError):
        revise_finding(
            ident,
            запись,
            tenant="HQ",
            revision=ИСПРАВЛЕНИЕ,
            editor=безымянный,
            score_of=_по(ПЕРЕСЧЁТ),
        )
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None and после.findings[0].level == "D1"
    assert _журнал(pg_dsn, ident) == []


def test_добавление_записи_пишется_в_журнал(сеть: None, pg_dsn: str) -> None:
    # Arrange
    ident = _ждущая(616)[0]

    # Act
    новая = add_review_finding(
        ident,
        tenant="HQ",
        addition=Addition(
            code="CLN06", level="D2", zone="dining", zone_unusual=False, text="  стены  "
        ),
        editor=ПРАВИТ,
        score_of=_по(ПЕРЕСЧЁТ),
    )

    # Assert
    строка = _одна_строка(pg_dsn, ident)
    assert (строка["finding"], строка["kind"], строка["login"]) == (новая, "add", "kontroling")
    assert строка["changes"]["level"] == {"old": None, "new": "D2"}
    assert строка["changes"]["text"] == {"old": None, "new": "стены"}
    assert строка["changes"]["score_pct"]["new"] == 88.5


def test_роль_приложения_журнал_правок_только_дописывает(сеть: None, pg_dsn: str) -> None:
    """Правку следа задним числом база не даёт: у роли приложения нет update/delete/select."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select privilege_type from information_schema.role_table_grants "
            "where table_name = 'inspection_edits' and grantee = 'dodo_audit_app'"
        )
        права = {r[0] for r in cur.fetchall()}
    assert права == {"INSERT"}
