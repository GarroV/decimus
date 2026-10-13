"""Забор общей таблицы через настоящую базу (ядро: пропуск неизменного, журнал, сбой, D464).

Сеть подменена словарём «номер листа → байты». Что держим: неизменный лист не плодит
строк журнала; изменённая ячейка обновляет данные; лист, вернувшийся к прежнему
содержимому, применяется заново; сбой одного листа не останавливает остальные и
оставляет причину в журнале и в состоянии; тот же сбой подряд журнал не засоряет.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import requires_db
from ratings_samples import U1, snapshot, to_csv
from test_ratings_base import (
    COLLECTION_HEADER,
    RKO_VIOLATIONS_HEADER,
    RS_VIOLATIONS_HEADER,
    SEP_8,
    _score_row,
    scores,
)

psycopg = pytest.importorskip("psycopg")

from src.db import ratings_sync as state  # noqa: E402
from src.ratings import sheet_sync  # noqa: E402
from src.ratings.importer import CHANNEL_WEB, import_file  # noqa: E402
from src.ratings.sheet_sync import SyncError  # noqa: E402

pytestmark = requires_db

СЕГОДНЯ = date(2026, 10, 13)
ENV = {"RATINGS_SHEET_ID": "a" * 30}
SCORES, COLLECTION, RKO_V, RS_V = (gid for _, gid in sheet_sync.TABS)


def _листы(score: str = "92,5") -> dict[int, bytes]:
    return {
        SCORES: scores(_score_row("05.01 — 11.01", "РКО", score)),
        COLLECTION: to_csv(
            COLLECTION_HEADER, [["05.01 — 11.01", "Dev", "Serbia", "Testville-1", "1", "4", ""]]
        ),
        RKO_V: to_csv(
            RKO_VIOLATIONS_HEADER,
            [
                [
                    "Сентябрь",
                    "07.09 — 13.09",
                    "Dev",
                    "Serbia",
                    "Testville-1",
                    "2",
                    "РКО",
                    "Борт",
                    SEP_8,
                ]
            ],
        ),
        RS_V: to_csv(
            RS_VIOLATIONS_HEADER,
            [
                [
                    "Сентябрь",
                    "Сентябрь 2",
                    "Dev",
                    "Serbia",
                    "Testville-1",
                    "РС",
                    "Грязно",
                    "x",
                    SEP_8,
                ]
            ],
        ),
    }


def _забрать(листы: dict[int, bytes], *, закрыть: frozenset[int] = frozenset()) -> dict[str, str]:
    def fetch(sheet: str, gid: int) -> bytes:
        assert sheet == ENV["RATINGS_SHEET_ID"]
        if gid in закрыть:
            raise SyncError(sheet_sync.ERR_CLOSED, "таблица закрыта")
        if gid not in листы:
            raise SyncError(sheet_sync.ERR_HTTP, "нет листа")  # справочники в тесте не нужны
        return листы[gid]

    return {r.tab: r.outcome for r in sheet_sync.run(today=СЕГОДНЯ, fetch=fetch, env=ENV)}


def _строки(db_env: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(db_env) as conn:
        return [tuple(r) for r in conn.execute(sql, params).fetchall()]


def _журнал(db_env: str) -> int:
    return int(
        _строки(db_env, "select count(*) from ratings.imports where actor = 'sheet-sync'")[0][0]
    )  # type: ignore[call-overload]


def _подготовить(db_env: str) -> None:
    import_file(snapshot(), kind=None, channel=CHANNEL_WEB, actor="ctl", file_name="s.json")


def test_первый_забор_кладёт_все_листы_через_журнал(db_env: str) -> None:
    _подготовить(db_env)
    assert set(_забрать(_листы()).values()) == {"loaded"}
    assert _строки(
        db_env,
        "select channel, format, outcome from ratings.imports where actor = 'sheet-sync' "
        "order by id",
    ) == [("sync", f, "loaded") for f, _ in sheet_sync.TABS]
    assert {s.tab: s.outcome for s in state.states()} == {f: "loaded" for f, _ in sheet_sync.TABS}


def test_неизменный_лист_пропускается_без_строки_журнала(db_env: str) -> None:
    _подготовить(db_env)
    _забрать(_листы())
    до = _журнал(db_env)
    assert set(_забрать(_листы()).values()) == {"unchanged"}
    assert _журнал(db_env) == до


def test_изменённая_ячейка_обновляет_данные_а_откат_листа_применяется_заново(db_env: str) -> None:
    _подготовить(db_env)
    _забрать(_листы("92,5"))
    итог = _забрать(_листы("80"))
    assert итог["base-scores"] == "loaded" and итог["base-collection"] == "unchanged"
    балл = (
        "select score::float from ratings.scores where unit_dodo_id = %s and period_id = "
        "(select id from ratings.periods where begin_on = '2026-01-05')"
    )
    assert _строки(db_env, балл, (U1,)) == [(80.0,)]
    # таблицу вернули к содержимому, которое уже грузилось: данные обязаны вернуться
    assert _забрать(_листы("92,5"))["base-scores"] == "loaded"
    assert _строки(db_env, балл, (U1,)) == [(92.5,)]


def test_сбой_листа_в_журнале_остальные_идут_дальше(db_env: str) -> None:
    _подготовить(db_env)
    итог = _забрать(_листы(), закрыть=frozenset({COLLECTION}))
    assert итог["base-collection"] == "failed" and итог["base-scores"] == "loaded"
    assert _строки(
        db_env,
        "select outcome, note from ratings.imports where actor = 'sheet-sync' "
        "and file_name = 'sheet:base-collection'",
    ) == [("failed", "closed: таблица закрыта")]
    (сбой,) = [s for s in state.states() if s.tab == "base-collection"]
    assert сбой.outcome == "failed" and (сбой.note or "").startswith("closed:")
    # таблицу открыли: лист не застревает в «сбое»
    assert _забрать(_листы())["base-collection"] == "loaded"


def test_заголовок_изменился_причина_видна_повтор_журнал_не_засоряет(db_env: str) -> None:
    _подготовить(db_env)
    листы = _листы()
    листы[SCORES] = to_csv(["Совсем", "Другое"], [["1", "2"]])
    assert _забрать(листы)["base-scores"] == "failed"
    (сбой,) = [s for s in state.states() if s.tab == "base-scores"]
    assert (сбой.note or "").startswith("header:")
    до = _журнал(db_env)
    assert _забрать(листы)["base-scores"] == "failed"
    assert _журнал(db_env) == до
    # лист починили
    assert _забрать(_листы())["base-scores"] == "loaded"


def test_без_настройки_ничего_не_пишется(db_env: str) -> None:
    with pytest.raises(SyncError):
        sheet_sync.run(today=СЕГОДНЯ, fetch=lambda *_: b"", env={})
    assert _журнал(db_env) == 0 and state.states() == ()


def test_заявка_одна_пока_не_выполнена_и_закрывается(db_env: str) -> None:
    первая, создана = state.request_sync(by="ctl")
    вторая, снова = state.request_sync(by="ещё кто-то")
    assert (создана, снова, вторая.id) == (True, False, первая.id)
    open_ = state.open_request()
    assert open_ is not None and open_.id == первая.id
    state.finish_request(первая.id, ok=False, error="x" * 600)
    assert state.open_request() is None
    ((_, исход, ошибка),) = state.recent_requests()
    assert исход == "failed" and len(ошибка or "") == 500
    assert state.request_sync(by="ctl")[1] is True
