"""«Подключения» на настоящей базе (D425): весь цикл ключа без командной строки.

Экран выдаёт ключ, а API (`/api/v1/*`) его принимает или отбивает — база
настоящая, поэтому видно то, чего не видно на двойнике: в таблице лежит только
отпечаток, права правятся без нового ключа, перевыпуск гасит старый ключ в той
же транзакции, отзыв закрывает дверь. Вошедший подменён на границе `auth`
(как у остальных экранных наборов), всё остальное — как в продукте.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from conftest import requires_db
from flask.testing import FlaskClient
from web_harness import ЛОГИН, СВОЙ, войти, подменить_двери, собрать

psycopg = pytest.importorskip("psycopg")

from src.db.mcp_access import token_fingerprint  # noqa: E402

pytestmark = requires_db

ЗАГОЛОВКИ = {"Origin": СВОЙ}
СПИСОК = "/api/v1/inspections"
МАПЫ = "/api/v1/maps/ratings"
РЕЙТИНГИ = "/api/v1/ratings/scores?type=rs"


@pytest.fixture
def экран(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _ключ(html: str) -> str:
    найдено = re.search(r'<code id="service-key">([^<]+)</code>', html)
    assert найдено is not None, "на странице нет ключа"
    return найдено.group(1)


def _api(путь: str, ключ: str) -> int:
    """Адрес API без сессии человека: только заголовок ключа."""
    with собрать(tenant="HQ").test_client() as client:
        return client.get(путь, headers={"Authorization": f"Bearer {ключ}"}).status_code


def test_цикл_ключа_выдача_правка_перевыпуск_отзыв(экран: FlaskClient, pg_dsn: str) -> None:
    # Выдача: ключ на странице один раз, в базе — отпечаток и след выдачи.
    выдан = экран.post(
        "/administration/connections/issue",
        data={
            "title": "Проверочный сервис",
            "code": "probe",
            "scope": ["inspections:list", "ratings:scores"],
        },
        headers=ЗАГОЛОВКИ,
    )
    assert выдан.status_code == 200
    html = выдан.get_data(as_text=True)
    ключ = _ключ(html)
    assert html.count(ключ) == 1 and "no-store" in выдан.headers["Cache-Control"]
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select id, fingerprint, issued_by, tokens::text from api.tokens "
            "where consumer = 'probe'"
        )
        номер, отпечаток, кем, строка = cur.fetchone()
    assert отпечаток == token_fingerprint(ключ) and ключ not in строка
    assert кем == ЛОГИН
    assert ключ not in экран.get(f"/administration?tab=connections&service={номер}").get_data(
        as_text=True
    )

    # Выданное право открывает свой адрес, чужое — нет.
    assert _api(СПИСОК, ключ) == 200
    assert _api(МАПЫ, ключ) == 403

    # Правка: снятое право закрывает свой адрес, ключ тот же.
    правка = экран.post(
        f"/administration/connections/{номер}/update",
        data={"title": "Проверочный сервис", "scope": ["ratings:scores"]},
        headers=ЗАГОЛОВКИ,
    )
    assert правка.status_code == 200 and "Сохранено" in правка.get_data(as_text=True)
    assert _api(СПИСОК, ключ) == 403
    assert _api(РЕЙТИНГИ, ключ) == 200

    # Журнал виден в карточке: ходил — путь и ответ записаны.
    карточка = экран.get(f"/administration?tab=connections&service={номер}").get_data(as_text=True)
    assert "/api/v1/inspections" in карточка

    # Перевыпуск: старый ключ перестаёт пускать, новый пускает с теми же правами.
    новый_ответ = экран.post(f"/administration/connections/{номер}/reissue", headers=ЗАГОЛОВКИ)
    assert новый_ответ.status_code == 200
    новый = _ключ(новый_ответ.get_data(as_text=True))
    assert новый != ключ
    assert _api(РЕЙТИНГИ, ключ) == 401, "старый ключ после перевыпуска ещё пускает"
    assert _api(РЕЙТИНГИ, новый) == 200

    # Отзыв: новый ключ тоже закрыт, строка остаётся со следом.
    живой_номер = _номер_живого(pg_dsn)
    отозван = экран.post(f"/administration/connections/{живой_номер}/revoke", headers=ЗАГОЛОВКИ)
    assert отозван.status_code == 200 and "отозван" in отозван.get_data(as_text=True)
    assert _api(РЕЙТИНГИ, новый) == 401
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*), count(revoked_at) from api.tokens where consumer = 'probe'")
        assert cur.fetchone() == (2, 2)


def _номер_живого(pg_dsn: str) -> int:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select id from api.tokens where consumer = 'probe' and revoked_at is null")
        return int(cur.fetchone()[0])


def test_отказ_формы_ничего_не_пишет_в_таблицу(экран: FlaskClient, pg_dsn: str) -> None:
    плохие = [
        {"title": "x", "code": "probe", "scope": []},
        {"title": "x", "code": "probe", "scope": ["admin"]},
        {"title": "x", "code": "Probe!", "scope": ["ratings:scores"]},
        {"title": "x", "code": "probe", "scope": ["ratings:scores"], "countries": "ZZ"},
        {"title": "x", "code": "probe", "scope": ["ratings:scores"], "expires": "2020-01-01"},
    ]
    for форма in плохие:
        assert (
            экран.post(
                "/administration/connections/issue", data=форма, headers=ЗАГОЛОВКИ
            ).status_code
            == 400
        )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from api.tokens where consumer ilike 'probe%'")
        assert cur.fetchone() == (0,)
