"""Дверь загрузки рейтингов через настоящую базу (ядро: идемпотентность, журнал).

Тот же файл — `duplicate` со ссылкой на первую загрузку; тот же смысл другими
байтами — обновление по ключу, а не вторая строка; неразобранный файл — `failed`
с причиной; база отказала посреди файла — не легло ничего.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from conftest import requires_db
from ratings_samples import (
    C1,
    C2,
    P_RS,
    SHEET_RS_HEADER,
    U1,
    rko_evaluations,
    rko_violations,
    sheet_rs,
    snapshot,
    to_csv,
)

psycopg = pytest.importorskip("psycopg")

from src.db import ratings as store  # noqa: E402
from src.db.errors import ConfigError, RatingsError  # noqa: E402
from src.ratings import importer  # noqa: E402
from src.ratings.importer import CHANNEL_MCP, CHANNEL_WEB, ImportReport, import_file  # noqa: E402
from src.ratings.model import (  # noqa: E402
    CATEGORY_REMARK,
    FORMAT_SNAPSHOT,
    RS,
    Parsed,
    PeriodRef,
    RatingsFormatError,
    Remark,
    UnitRef,
    Violation,
)

pytestmark = requires_db

СЕГОДНЯ = date(2026, 10, 8)


def _грузить(data: bytes, **kw: object) -> ImportReport:
    return import_file(
        data,
        kind=None,
        channel=CHANNEL_WEB,
        actor="ctl",
        file_name="f.csv",
        today=СЕГОДНЯ,
        **kw,  # type: ignore[arg-type]
    )


def _одно(db_env: str, sql: str, params: tuple[object, ...] = ()) -> object:
    with psycopg.connect(db_env) as conn:
        row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def _строка(db_env: str, sql: str, params: tuple[object, ...] = ()) -> tuple[object, ...] | None:
    with psycopg.connect(db_env) as conn:
        row = conn.execute(sql, params).fetchone()
    return None if row is None else tuple(row)


def test_нарушения_ркО_ложатся_с_журналом(db_env: str) -> None:
    отчёт = _грузить(rko_violations())
    assert (отчёт.outcome, отчёт.format, отчёт.accepted, отчёт.updated, отчёт.skipped) == (
        "loaded",
        "rko-violations",
        2,
        0,
        1,
    )
    assert _одно(db_env, "select count(*) from ratings.checkups") == 2
    assert _одно(db_env, "select sum(amount) from ratings.violations") == 4
    assert _одно(db_env, "select country_code from ratings.units where dodo_id = %s", (U1,)) == "RS"
    assert _строка(
        db_env,
        "select outcome, actor, channel, accepted, updated, skipped from ratings.imports",
    ) == ("loaded", "ctl", "web", 2, 0, 1)


def test_тот_же_файл_дубль_со_ссылкой(db_env: str) -> None:
    первая = _грузить(rko_violations())
    повтор = _грузить(rko_violations())
    assert повтор.outcome == "duplicate" and повтор.loaded_at is not None
    assert (
        _одно(db_env, "select duplicate_of from ratings.imports where id = %s", (повтор.import_id,))
        == первая.import_id
    )
    assert _одно(db_env, "select count(*) from ratings.checkups") == 2


def test_те_же_строки_другими_байтами_обновляются(db_env: str) -> None:
    _грузить(rko_violations())
    как_текст = rko_violations().decode("utf-8-sig").replace("\r\n", "\n").encode()
    повтор = import_file(
        как_текст,
        kind="rko-violations",
        channel=CHANNEL_MCP,
        actor="mcp:HQ",
        file_name=None,
        today=СЕГОДНЯ,
    )
    assert (повтор.outcome, повтор.accepted, повтор.updated) == ("loaded", 0, 2)
    assert _одно(db_env, "select count(*) from ratings.violations") == 3
    assert _одно(db_env, "select count(*) from ratings.checkups") == 2
    # Журнал второй загрузки говорит «обновлено 2», а не «принято 2».
    assert _строка(
        db_env,
        "select outcome, accepted, updated from ratings.imports where id = %s",
        (повтор.import_id,),
    ) == ("loaded", 0, 2)


def test_приёмка_до_и_после_нарушений(db_env: str) -> None:
    _грузить(rko_evaluations())
    _грузить(rko_violations())
    sql = "select acceptance, unit_dodo_id from ratings.checkups where dodo_id = %s"
    assert _строка(db_env, sql, (C1,)) == ("accepted", U1)
    assert (
        _одно(db_env, "select acceptance from ratings.checkups where dodo_id = %s", (C2,)) is None
    )


def test_неразобранный_файл_строкой_failed(db_env: str) -> None:
    with pytest.raises(RatingsFormatError):
        _грузить(b"a,b\r\n1,2\r\n")
    assert _одно(db_env, "select outcome from ratings.imports") == "failed"
    assert "rko-violations" in str(_одно(db_env, "select note from ratings.imports"))


def test_незнакомый_формат_явно_строкой_failed(db_env: str) -> None:
    with pytest.raises(RatingsFormatError) as пойман:
        import_file(
            rko_violations(), kind="xlsx", channel=CHANNEL_WEB, actor="ctl", file_name="f.csv"
        )
    assert пойман.value.code == "unknown_format"
    assert _одно(db_env, "select outcome from ratings.imports") == "failed"


def test_снимок_главнее_листа(db_env: str) -> None:
    _грузить(snapshot())
    лист = _грузить(sheet_rs())
    sql = (
        "select s.score, s.source from ratings.scores s "
        "join ratings.periods p on p.id = s.period_id "
        "where s.unit_dodo_id = %s and p.begin_on = '2026-09-16'"
    )
    # Лист даёт тот же балл 97.5 — различает только источник (P9).
    assert _строка(db_env, sql, (U1,)) == (pytest.approx(97.5), "snapshot")
    assert лист.skipped >= 2  # Россия + балл, уступивший снимку


def test_части_снимка_в_любом_порядке_и_с_повтором(db_env: str) -> None:
    вторая = snapshot()
    третья = snapshot(name="Testville-1").replace(b'"index": 2', b'"index": 3')
    assert _грузить(третья).outcome == "loaded"
    отчёт = _грузить(вторая)
    assert (отчёт.outcome, отчёт.label) == ("loaded", "часть 2 из 3")
    повтор = _грузить(вторая)
    assert (повтор.outcome, повтор.label) == ("duplicate", "часть 2 из 3")
    assert _одно(db_env, "select count(*) from ratings.scores") == 2
    assert _одно(db_env, "select note from ratings.imports where id = %s", (отчёт.import_id,)) == (
        "часть 2 из 3"
    )


def test_лист_без_id_сопоставляет_и_пишет_несопоставленное(db_env: str) -> None:
    _грузить(snapshot())
    отчёт = _грузить(sheet_rs())
    assert отчёт.unmatched == 1  # «Testville 2» в Словении неизвестна
    assert _одно(db_env, "select reason from ratings.import_issues") == "unit_unmatched"
    assert _одно(db_env, "select developer from ratings.countries where code = 'RS'") == "Dev One"


def test_несопоставленная_строка_листа_считается_строкой_а_не_баллами(db_env: str) -> None:
    """P10: три балла одной неизвестной пиццерии — одна строка журнала и «не сопоставлено 1»."""
    лист = to_csv(SHEET_RS_HEADER, [["Dev One", "Slovenia", "Testville 2", "", "70", "71", "72"]])
    отчёт = _грузить(лист)
    assert (отчёт.unmatched, отчёт.issues) == (1, 1)
    assert _строка(db_env, "select unmatched from ratings.imports") == (1,)
    assert _одно(db_env, "select count(*) from ratings.import_issues") == 1


def test_пиццерия_без_страны_не_цепляется_к_чужой_стране(db_env: str) -> None:
    """Запись справочника без страны не сопоставляется со строкой листа из любой страны."""
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.units (dodo_id, name, name_normalized) "
            "values (%s, 'Testville 2', 'testville 2')",
            ("ab" * 16,),
        )
    отчёт = _грузить(to_csv(SHEET_RS_HEADER, [["", "Slovenia", "Testville 2", "", "", "71", ""]]))
    assert (отчёт.accepted, отчёт.unmatched) == (0, 1)
    assert _одно(db_env, "select count(*) from ratings.scores") == 0


def test_отказ_базы_посреди_файла_не_оставляет_половины(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    настоящая = store.replace_checkup_violations
    вызовы = {"n": 0}

    def вторая_падает(*a: object, **kw: object) -> None:
        вызовы["n"] += 1
        if вызовы["n"] == 2:
            raise psycopg.errors.CheckViolation("порча")
        настоящая(*a, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "replace_checkup_violations", вторая_падает)
    with pytest.raises(RatingsError):
        _грузить(rko_violations())
    assert _одно(db_env, "select count(*) from ratings.checkups") == 0
    assert _строка(db_env, "select outcome, accepted, updated from ratings.imports") == (
        "failed",
        0,
        0,
    )
    assert "CheckViolation" in str(_одно(db_env, "select note from ratings.imports"))


def test_сбой_не_базы_оставляет_failed_и_уходит_наружу(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def падает(*a: object, **kw: object) -> None:
        raise RuntimeError("порча")

    monkeypatch.setattr(store, "replace_checkup_violations", падает)
    with pytest.raises(RuntimeError):
        _грузить(rko_violations())
    assert _одно(db_env, "select count(*) from ratings.checkups") == 0
    assert _строка(db_env, "select outcome, format from ratings.imports") == (
        "failed",
        "rko-violations",
    )
    assert "RuntimeError" in str(_одно(db_env, "select note from ratings.imports"))


def test_сбой_следа_не_подменяет_причину_отказа(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def след_падает(**kw: object) -> int:
        raise ConfigError("нет окружения")

    monkeypatch.setattr(store, "record_failure", след_падает)
    with pytest.raises(RatingsFormatError):
        _грузить(b"a,b\r\n1,2\r\n")
    assert _одно(db_env, "select count(*) from ratings.imports") == 0


def test_период_того_же_слота_с_другим_id_отказ_а_не_склейка(db_env: str) -> None:
    _грузить(snapshot())
    другой = "ee" * 16
    with pytest.raises(RatingsError, match="другим id"):
        _грузить(snapshot().replace(P_RS.encode(), другой.encode()))
    assert _строка(db_env, "select outcome from ratings.imports order by id desc limit 1") == (
        "failed",
    )
    assert "другим id" in str(
        _одно(db_env, "select note from ratings.imports order by id desc limit 1")
    )
    sql = "select dodo_id from ratings.periods where begin_on = '2026-09-16'"
    assert _одно(db_env, sql) == P_RS
    assert _одно(db_env, "select count(*) from ratings.periods where dodo_id = %s", (другой,)) == 0


def test_длинный_текст_нарушения_ложится(db_env: str) -> None:
    """Ключ — хеш текста: 8 КБ плохо сжимаемого текста не упираются в предел btree."""
    длинный = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(125))
    отчёт = _грузить(rko_violations(**{"Выявленные нарушения": длинный}))
    assert (отчёт.outcome, отчёт.accepted) == ("loaded", 2)
    assert _одно(db_env, "select max(length(text)) from ratings.violations") == 500
    assert int(str(_одно(db_env, "select max(length(row_key)) from ratings.violations"))) < 200


def test_замечание_без_id_пиццерии_в_журнал(db_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    период = PeriodRef(RS, date(2026, 9, 16), date(2026, 9, 30), "Сентябрь 2", "September 2")
    замечание = Remark(UnitRef(None, "Testville-9", "RS"), период, Violation("x", CATEGORY_REMARK))
    разобрано = Parsed(FORMAT_SNAPSHOT, remarks=(замечание,))
    monkeypatch.setattr(importer, "parse_file", lambda *a, **kw: разобрано)
    отчёт = _грузить(b"{}")
    assert (отчёт.outcome, отчёт.issues) == ("loaded", 1)
    assert _строка(db_env, "select row_no, reason from ratings.import_issues") == (1, "bad_row")


def test_сбой_разборщика_оставляет_failed_и_уходит_наружу(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def падает(*a: object, **kw: object) -> Parsed:
        raise RuntimeError("порча")

    monkeypatch.setattr(importer, "parse_file", падает)
    with pytest.raises(RuntimeError):
        _грузить(rko_violations())
    assert _строка(db_env, "select outcome, note from ratings.imports") == (
        "failed",
        "сбой разбора: RuntimeError",
    )
