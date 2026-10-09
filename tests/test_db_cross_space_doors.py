"""Действие УК над проверкой партнёра и строка журнала — одной транзакцией (D017).

Для каждой двери проверок: (а) УК в пространстве партнёра оставляет ровно одну
строку, (б) откатившееся действие не оставляет ни строки, ни следа действия,
(в) своё пространство строки не пишет. Откат проверяется «записал и упал»: журнал
уже вставлен, а затем действие рушится — строка обязана уйти вместе с ним. Если
бы журнал писался после коммита или другим подключением, либо действие осталось
бы без строки, либо строка без действия: тест смотрит на обе половины.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import (
    set_retraction_env,
    привязать_пространства,
    слить_проверку,
    точка_пространства,
)

psycopg = pytest.importorskip("psycopg")

from src.db import accept, letters, move, retract, revise  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.cross_space import Entry, entry_for, record  # noqa: E402
from src.db.errors import AcceptError, MoveError, RetractionError, ReviseError  # noqa: E402
from src.db.letters import latest_letter, save_letter  # noqa: E402
from src.db.move import move_inspection  # noqa: E402
from src.db.queries import unit_ids  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.retract import retract_inspection  # noqa: E402
from src.db.revise import Revision, revise_finding  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain.models import Score  # noqa: E402
from src.domain.permissions import Actor  # noqa: E402

pytestmark = requires_db
ТОЧКА = "Тбилиси-1"
ДРУГАЯ = "Тбилиси-2"
НОВАЯ_ДАТА = date(2026, 9, 1)

ОЦЕНКА = Score(
    pct=90.0,
    grade="A",
    label_ru="",
    label_en="",
    counts={"D1": 1, "D2": 0, "D3": 0},
    deductions=10.0,
    by_zone={},
)
ПРАВКА = Revision(
    code="CLN05", level="D1", zone="dining", zone_unusual=False, text="правка записи в зале"
)


@pytest.fixture
def retraction_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _учётка_уК(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-doors', %s, 'hq_admin') returning id",
            (password_hash("пароль-дверей-1"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def _журнал(pg_dsn: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select object_tenant, action_code, object_ref from cross_space_actions")
        return [(str(a), str(b), str(c)) for a, b, c in cur.fetchall()]


def _одно(pg_dsn: str, sql: str, ident: str) -> tuple[Any, ...]:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, (ident,))
        строка = cur.fetchone()
    assert строка is not None
    return tuple(строка)


def _шапка(pg_dsn: str, ident: str) -> tuple[Any, ...]:
    return _одно(
        pg_dsn,
        "select status, retracted_at is not null, inspection_date, unit_id "
        "from inspections where id = %s",
        ident,
    )


def _текст_записи(pg_dsn: str, ident: str) -> tuple[Any, ...]:
    return _одно(
        pg_dsn,
        "select code, zone from findings where inspection_id = %s order by n limit 1",
        ident,
    )


def _партнёрская(pg_dsn: str, *, accept_it: bool) -> tuple[str, str]:
    привязать_пространства(pg_dsn, "GE")
    точка_пространства(ТОЧКА, tenant="GE")
    точка_пространства(ДРУГАЯ, tenant="GE")
    return слить_проверку(unit=ТОЧКА, tenant="GE", accept=accept_it), _учётка_уК(pg_dsn)


def _запись(кто: str, action: str, ident: str, *, tenant: str = "GE") -> Entry | None:
    """Строка журнала так, как её собирает вызывающий: через `entry_for`."""
    actor = Actor(tenant="HQ", role="hq_admin", grants={}, user_id=кто)
    return entry_for(actor, object_tenant=tenant, action=action, object_ref=f"inspection:{ident}")


def _упасть_после_записи(monkeypatch: pytest.MonkeyPatch, модуль: Any) -> None:
    """Подменить `record` в двери: пишет по-настоящему и тут же рушит транзакцию."""

    def _пишет_и_падает(conn: Any, entry: Entry | None) -> None:
        record(conn, entry)
        raise psycopg.OperationalError("обрыв после записи журнала")

    monkeypatch.setattr(модуль, "record", _пишет_и_падает)


def _считать_подключения(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Счётчик `psycopg.connect`: строка журнала обязана идти на подключении двери."""
    открыто: list[int] = []
    настоящее = psycopg.connect

    def _считает(*args: Any, **kwargs: Any) -> Any:
        открыто.append(1)
        return настоящее(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", _считает)
    return открыто


# --- снятие -----------------------------------------------------------------------


def test_снятие_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    retract_inspection(
        ident,
        tenant="GE",
        reason="УК сняла ошибочную",
        journal=_запись(кто, "inspection.retract", ident),
    )
    assert _журнал(pg_dsn) == [("GE", "inspection.retract", f"inspection:{ident}")]


def test_отказ_двери_снятия_не_оставляет_журнала(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Дверь падает ПОСЛЕ записи журнала — строка уходит вместе с пометкой."""
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    # Запрос отметки времени идёт после `record`: его поломка роняет транзакцию,
    # в которой журнал уже записан. Отказ раньше записи этого бы не проверил.
    monkeypatch.setattr(
        retract, "_SELECT_RETRACTED_AT_SQL", "select нет_такой_колонки where %s is not null"
    )
    with pytest.raises(RetractionError):
        retract_inspection(
            ident,
            tenant="GE",
            reason="упадёт после журнала",
            journal=_запись(кто, "inspection.retract", ident),
        )
    assert _журнал(pg_dsn) == []
    assert _шапка(pg_dsn, ident)[1] is False


def test_снятие_в_один_коммит_с_журналом(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обрыв сразу после записи журнала откатывает и пометку: ни следа, ни строки."""
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    _упасть_после_записи(monkeypatch, retract)
    with pytest.raises(RetractionError):
        retract_inspection(
            ident,
            tenant="GE",
            reason="обрыв после журнала",
            journal=_запись(кто, "inspection.retract", ident),
        )
    assert _журнал(pg_dsn) == []
    assert _шапка(pg_dsn, ident)[1] is False


def test_повторное_снятие_журнал_не_дублирует(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    запись = _запись(кто, "inspection.retract", ident)
    retract_inspection(ident, tenant="GE", reason="первый вызов", journal=запись)
    retract_inspection(ident, tenant="GE", reason="повтор доделывает уборку", journal=запись)
    assert len(_журнал(pg_dsn)) == 1


def test_снятие_в_своём_пространстве_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    assert _запись(кто, "inspection.retract", ident, tenant="HQ") is None
    retract_inspection(
        ident,
        tenant="GE",
        reason="партнёр снял свою",
        journal=_запись(кто, "inspection.retract", ident, tenant="HQ"),
    )
    assert _журнал(pg_dsn) == []


# --- приёмка ----------------------------------------------------------------------


def test_приёмка_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    accept_inspection(
        ident, tenant="GE", actor="hq", journal=_запись(кто, "inspection.accept", ident)
    )
    assert _журнал(pg_dsn) == [("GE", "inspection.accept", f"inspection:{ident}")]
    assert _шапка(pg_dsn, ident)[0] == "finalized"


def test_приёмка_откатилась_журнала_нет(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    _упасть_после_записи(monkeypatch, accept)
    with pytest.raises(AcceptError):
        accept_inspection(
            ident, tenant="GE", actor="hq", journal=_запись(кто, "inspection.accept", ident)
        )
    assert _журнал(pg_dsn) == []
    assert _шапка(pg_dsn, ident)[0] == "draft"


def test_приёмка_отказавшая_до_действия_журнала_нет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)  # уже принята
    with pytest.raises(AcceptError):
        accept_inspection(
            ident, tenant="GE", actor="hq", journal=_запись(кто, "inspection.accept", ident)
        )
    assert _журнал(pg_dsn) == []


def test_приёмка_в_своём_пространстве_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    accept_inspection(
        ident,
        tenant="GE",
        actor="партнёр",
        journal=_запись(кто, "inspection.accept", ident, tenant="HQ"),
    )
    assert _журнал(pg_dsn) == []


# --- перенос ----------------------------------------------------------------------


def _перенести(ident: str, journal: Entry | None, *, unit_id: str | None = None) -> bool:
    return move_inspection(
        ident,
        tenant="GE",
        new_date=НОВАЯ_ДАТА,
        new_unit_id=unit_id or unit_ids(reach=own_reach("HQ"))[ДРУГАЯ],
        reason="УК поправила точку",
        actor="hq",
        journal=journal,
    )


def test_перенос_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    assert _перенести(ident, _запись(кто, "inspection.move", ident)) is True
    assert _журнал(pg_dsn) == [("GE", "inspection.move", f"inspection:{ident}")]


def test_перенос_откатился_журнала_нет(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    до = _шапка(pg_dsn, ident)
    _упасть_после_записи(monkeypatch, move)
    with pytest.raises(MoveError):
        _перенести(ident, _запись(кто, "inspection.move", ident))
    assert _журнал(pg_dsn) == []
    assert _шапка(pg_dsn, ident) == до


def test_перенос_ничего_не_изменивший_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    """«Всё уже так» — действие не состоялось, следа «кто и когда» нет."""
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    _, _, дата, точка = _шапка(pg_dsn, ident)
    изменено = move_inspection(
        ident,
        tenant="GE",
        new_date=дата,
        new_unit_id=str(точка),
        reason="без перемен",
        actor="hq",
        journal=_запись(кто, "inspection.move", ident),
    )
    assert изменено is False
    assert _журнал(pg_dsn) == []


def test_перенос_в_своём_пространстве_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    assert _перенести(ident, _запись(кто, "inspection.move", ident, tenant="HQ")) is True
    assert _журнал(pg_dsn) == []


# --- правка на приёмке ------------------------------------------------------------


def _запись_проверки(pg_dsn: str, ident: str) -> str:
    return str(_одно(pg_dsn, "select id from findings where inspection_id = %s limit 1", ident)[0])


def _исправить(
    pg_dsn: str, ident: str, journal: Entry | None, *, finding_id: str | None = None
) -> None:
    revise_finding(
        ident,
        finding_id or _запись_проверки(pg_dsn, ident),
        tenant="GE",
        revision=ПРАВКА,
        score_of=lambda _detail: ОЦЕНКА,
        journal=journal,
    )


def test_правка_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    _исправить(pg_dsn, ident, _запись(кто, "inspection.revise", ident))
    assert _журнал(pg_dsn) == [("GE", "inspection.revise", f"inspection:{ident}")]
    assert _текст_записи(pg_dsn, ident) == ("CLN05", "dining")


def test_правка_откатилась_журнала_нет(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    до = _текст_записи(pg_dsn, ident)
    _упасть_после_записи(monkeypatch, revise)
    with pytest.raises(ReviseError):
        _исправить(pg_dsn, ident, _запись(кто, "inspection.revise", ident))
    assert _журнал(pg_dsn) == []
    assert _текст_записи(pg_dsn, ident) == до


def test_правка_в_своём_пространстве_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    _исправить(pg_dsn, ident, _запись(кто, "inspection.revise", ident, tenant="HQ"))
    assert _журнал(pg_dsn) == []


# --- письмо -----------------------------------------------------------------------


def _письмо(ident: str, journal: Entry | None) -> None:
    save_letter(
        ident, tenant="GE", body="Уважаемые коллеги", lang="ru", saved_by="hq", journal=journal
    )


def test_письмо_по_проверке_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    _письмо(ident, _запись(кто, "inspection.letter", ident))
    assert _журнал(pg_dsn) == [("GE", "inspection.letter", f"inspection:{ident}")]


def test_письмо_откатилось_журнала_нет(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    _упасть_после_записи(monkeypatch, letters)
    with pytest.raises(psycopg.OperationalError):
        _письмо(ident, _запись(кто, "inspection.letter", ident))
    assert _журнал(pg_dsn) == []
    assert latest_letter(ident) is None


def test_письмо_к_несуществующей_проверке_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    from src.db.errors import PushError

    _, кто = _партнёрская(pg_dsn, accept_it=True)
    чужая = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(PushError):
        _письмо(чужая, _запись(кто, "inspection.letter", чужая))
    assert _журнал(pg_dsn) == []


def test_письмо_в_своём_пространстве_журнала_не_пишет(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    _письмо(ident, _запись(кто, "inspection.letter", ident, tenant="HQ"))
    assert _журнал(pg_dsn) == []


def test_журнал_идёт_подключением_двери_снятия(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    открыто = _считать_подключения(monkeypatch)
    retract_inspection(
        ident,
        tenant="GE",
        reason="одно подключение",
        journal=_запись(кто, "inspection.retract", ident),
    )
    assert len(открыто) == 1


def test_журнал_идёт_подключением_двери_приёмки(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    открыто = _считать_подключения(monkeypatch)
    accept_inspection(
        ident, tenant="GE", actor="hq", journal=_запись(кто, "inspection.accept", ident)
    )
    assert len(открыто) == 1


def test_журнал_идёт_подключением_двери_переноса(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    точка = unit_ids(reach=own_reach("HQ"))[ДРУГАЯ]
    открыто = _считать_подключения(monkeypatch)
    _перенести(ident, _запись(кто, "inspection.move", ident), unit_id=точка)
    assert len(открыто) == 1


def test_журнал_идёт_подключением_двери_правки(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=False)
    запись = _запись_проверки(pg_dsn, ident)
    открыто = _считать_подключения(monkeypatch)
    _исправить(pg_dsn, ident, _запись(кто, "inspection.revise", ident), finding_id=запись)
    assert len(открыто) == 1


def test_журнал_идёт_подключением_двери_письма(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident, кто = _партнёрская(pg_dsn, accept_it=True)
    открыто = _считать_подключения(monkeypatch)
    _письмо(ident, _запись(кто, "inspection.letter", ident))
    assert len(открыто) == 1
