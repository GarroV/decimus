"""Путь критерия приёмки на синтетике: контроль загрузил — партнёр видит, но не грузит."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import requires_db
from ratings_samples import rko_evaluations, rko_violations, rs_checkups, snapshot
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

pytestmark = requires_db
ORIGIN = {"Origin": "http://localhost"}


def test_контроль_грузит_партнёр_видит(
    db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="control")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for name, data in (
            ("v.csv", rko_violations()),
            ("e.csv", rko_evaluations()),
            ("r.csv", rs_checkups()),
            ("s.json", snapshot()),
        ):
            ответ = client.post(
                "/ratings/import", data={"file": (io.BytesIO(data), name)}, headers=ORIGIN
            )
            assert ответ.status_code == 200, ответ.get_data(as_text=True)
        повтор = client.post(
            "/ratings/import",
            data={"file": (io.BytesIO(rko_violations()), "v2.csv")},
            headers=ORIGIN,
        )
        assert "уже загружен" in повтор.get_data(as_text=True)
        журнал = client.get("/ratings/imports").get_data(as_text=True)
        assert журнал.count('title="rko-violations"') >= 2
        ответ = client.post(
            "/ratings/countries", data={"code": "RS", "developer": "Dev One"}, headers=ORIGIN
        )
        assert ответ.status_code == 200
        сводка = client.get("/ratings?group=developer&value=Dev+One&period=2026-Q3")
        assert "/ratings/imports" in сводка.get_data(as_text=True)
        # Пустой квартал: проверок не было — блок пишет «нет данных», а не «чисто» (P16).
        пусто = client.get("/ratings?group=developer&value=Dev+One&period=2026-Q1")
        текст = пусто.get_data(as_text=True)
        assert "За период нет данных РКО." in текст and "За период нет данных РС." in текст
        assert "Нарушений не найдено." not in текст.split("Хард-нарушения")[0]

    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="GE").test_client() as client:
        assert войти(client).status_code == 302
        страница = client.get("/ratings?group=developer&value=Dev+One&period=2026-Q3")
        assert страница.status_code == 200
        текст = страница.get_data(as_text=True)
        assert "97.5" in текст
        assert "/ratings/imports" not in текст
        assert (
            client.post(
                "/ratings/import", data={"file": (io.BytesIO(b"x"), "x.csv")}, headers=ORIGIN
            ).status_code
            == 403
        )
