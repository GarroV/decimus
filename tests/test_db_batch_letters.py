"""D739 (#1579): общее письмо по нескольким проверкам в базе.

Запись обязана держать сама: письмо ложится только к принятым проверкам своего пространства
из названной страны, не меняется после записи и находится по составу и языку. Правило
«не больше семи дней» стоит выше (`tests/test_batch_letter.py`), здесь — то, что нельзя
обойти, позвав запись напрямую.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from conftest import requires_db

from src.db import batch_letters as store
from src.db.errors import DbError, PushError

pytestmark = requires_db

ТЕКСТ = "Здравствуйте!\n\nРезультаты проверок.\n"


def _проверка(
    conn: psycopg.Connection,
    *,
    tenant: str = "HQ",
    name: str,
    country: str = "RS",
    day: date = date(2026, 11, 4),
    status: str = "finalized",
    origin: str = "field",
) -> str:
    unit = conn.execute(
        "insert into units(tenant_code,name,name_normalized,country) values (%s,%s,%s,%s) "
        "returning id",
        (tenant, name, name.lower(), country),
    ).fetchone()[0]
    return str(
        conn.execute(
            "insert into inspections(tenant_code,unit_id,chat_id,kind,inspection_date,"
            "report_lang,ui_lang,speech_lang,checklist_version,pct,grade,source_fingerprint,"
            "status,origin) values (%s,%s,0,'planned',%s,'ru','ru','ru','v1',95,'B',%s,%s,%s) "
            "returning id",
            (tenant, unit, day, f"{name}-{status}-{origin}", status, origin),
        ).fetchone()[0]
    )


@pytest.fixture
def две(pg_dsn: str, db_env: str) -> list[str]:
    with psycopg.connect(pg_dsn) as conn:
        return [_проверка(conn, name="Batch One"), _проверка(conn, name="Batch Two")]


def _сохранить(ids: list[str], **поля: object) -> store.SavedBatchLetter:
    параметры: dict[str, object] = {
        "tenant": "HQ",
        "country": "RS",
        "body": ТЕКСТ,
        "lang": "ru",
        "saved_by": "director",
    }
    параметры.update(поля)
    return store.save_batch_letter(ids, **параметры)  # type: ignore[arg-type]


def test_письмо_читается_обратно_слово_в_слово_с_составом(две: list[str]) -> None:
    записано = _сохранить(две)

    прочитано = store.latest_for_set(две, tenant="HQ", lang="ru")

    assert прочитано is not None
    assert прочитано.id == записано.id
    assert прочитано.body == ТЕКСТ
    assert прочитано.saved_by == "director"
    assert прочитано.country == "RS"
    assert set(прочитано.inspection_ids) == set(две)


def test_письмо_находится_только_для_того_же_набора_и_языка(две: list[str]) -> None:
    _сохранить(две)

    assert store.latest_for_set(две[:1], tenant="HQ") is None
    assert store.latest_for_set(две, tenant="HQ", lang="en") is None
    assert store.latest_for_set(две, tenant="чужой") is None


def test_новая_запись_не_стирает_прежнюю_и_считается_версией(две: list[str]) -> None:
    _сохранить(две)
    _сохранить(две, body="Правленое письмо")

    assert store.count_for_set(две, tenant="HQ", lang="ru") == 2
    последнее = store.latest_for_set(две, tenant="HQ")
    assert последнее is not None and последнее.body == "Правленое письмо"


def test_карточка_проверки_знает_в_какие_письма_она_вошла(две: list[str]) -> None:
    записано = _сохранить(две)

    письма = store.letters_of_inspection(две[0], tenant="HQ")

    assert [п.id for п in письма] == [записано.id]
    assert store.letters_of_inspection(две[0], tenant="чужой") == ()


def test_запись_заморожена_правкой_не_меняется(две: list[str], db_env: str) -> None:
    записано = _сохранить(две)
    # Под ролью приложения: правки и удаления ей не выданы вовсе.
    with psycopg.connect(db_env) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update batch_letters set body = 'подмена' where id = %s", (записано.id,))
    with psycopg.connect(db_env) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from batch_letters where id = %s", (записано.id,))
    прочитано = store.latest_for_set(две, tenant="HQ")
    assert прочитано is not None and прочитано.body == ТЕКСТ


@pytest.mark.parametrize(
    "поля",
    [
        {"body": "  \n"},
        {"lang": " "},
        {"saved_by": ""},
        {"country": ""},
    ],
)
def test_пустое_письмо_язык_автор_страна_отказ(две: list[str], поля: dict[str, object]) -> None:
    with pytest.raises(PushError):
        _сохранить(две, **поля)


def test_одной_проверки_и_повтора_в_составе_нет(две: list[str]) -> None:
    with pytest.raises(PushError, match="меньше двух"):
        _сохранить(две[:1])
    with pytest.raises(PushError, match="дважды"):
        _сохранить([две[0], две[0]])


def test_кривой_идентификатор_отказ_а_не_не_найдено(две: list[str]) -> None:
    with pytest.raises(DbError):
        _сохранить([две[0], "не-uuid"])


def test_чужая_страна_не_принятая_и_загруженная_не_ложатся(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        хорошая = _проверка(conn, name="Fit One")
        другая_страна = _проверка(conn, name="Fit Two", country="GE")
        на_приёмке = _проверка(conn, name="Fit Three", status="draft")
        загруженная = _проверка(conn, name="Fit Four", origin="import")
    for плохая in (другая_страна, на_приёмке, загруженная):
        with pytest.raises(PushError, match="не все проверки"):
            _сохранить([хорошая, плохая])


def test_проверка_чужого_пространства_и_несуществующая_один_отказ(pg_dsn: str, db_env: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        своя = _проверка(conn, name="Own One")
        чужая = _проверка(conn, tenant="HQ", name="Own Two")
    with pytest.raises(PushError, match="не все проверки"):
        _сохранить([своя, чужая], tenant="чужой")
    with pytest.raises(PushError, match="не все проверки"):
        _сохранить([своя, "00000000-0000-0000-0000-000000000000"])
