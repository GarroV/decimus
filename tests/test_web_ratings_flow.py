"""Путь критерия приёмки на синтетике: контроль загрузил — партнёр видит, но не грузит."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import requires_db
from ratings_samples import P_RS_PREV, rko_evaluations, rko_violations, rs_checkups, snapshot
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

pytestmark = requires_db
ORIGIN = {"Origin": "http://localhost"}
СЕНТЯБРЬ_2 = "from=2026-09-16&to=2026-09-30"  # даты периода РС из образца снимка
ПРОШЛЫЙ_РС = {
    "id": P_RS_PREV,
    "rating_type": 2,
    "begin": "2026-09-01",
    "end": "2026-09-15",
    "alias": "Сентябрь 1 часть 2026",
    "alias_en": "September part 1 2026",
}


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
        # Пустой квартал: проверок не было — каждый блок, включая хард-нарушения,
        # пишет «нет данных», а не «чисто»; зону риска не судили — «мало периодов»
        # (P16, P37). Проверяется вся страница, а не её начало.
        пусто = client.get("/ratings?group=developer&value=Dev+One&period=2026-Q1")
        текст = пусто.get_data(as_text=True)
        # Хард РС и РКО — одна секция с таблицей (D423).
        хард = текст.split("Хард-нарушения РС и РКО")[1].split("</section>")[0]
        assert "За период нет данных РС и РКО." in хард
        assert "Нарушений не найдено." not in текст
        assert "В зоне риска никого." not in текст
        assert "Недостаточно периодов для оценки: РС, РКО." in текст
        # Пустой кластер не обёрнут в карточку — «нет данных» стоит на месте секции.
        assert "rt-viol__cluster" not in текст
        # Дельта к периоду РС подписана его названием, а не ключом `rs:<id>` (P39):
        # догружаем прошлый период РС с оценкой — в первом снимке он пустой.
        прошлый = snapshot(history=[{"score": 90, "status": "1", "period": ПРОШЛЫЙ_РС}], remarks=[])
        ответ = client.post(
            "/ratings/import", data={"file": (io.BytesIO(прошлый), "p.json")}, headers=ORIGIN
        )
        assert ответ.status_code == 200, ответ.get_data(as_text=True)
        текст = client.get("/ratings?group=developer&value=Dev+One&period=2026-Q1").get_data(
            as_text=True
        )
        # Календарь «с — по»: даты периода РС узнаются как он сам — его имя в
        # заголовке и «Δ к прошлому периоду РС» его названием.
        период = client.get(f"/ratings?group=developer&value=Dev+One&{СЕНТЯБРЬ_2}")
        период_текст = период.get_data(as_text=True)
        assert "Сентябрь 2 часть 2026" in период_текст.split("rt-cal__title")[1][:80]
        assert "Δ к Сентябрь 1 часть 2026" in период_текст and "Δ к rs:" not in период_текст
        # Вторая страна застройщика без замечаний РС: её карточка пишет «нет данных»,
        # а не «нарушений не найдено» — при данных в кластере.
        ответ = client.post(
            "/ratings/countries", data={"code": "BY", "developer": "Dev One"}, headers=ORIGIN
        )
        assert ответ.status_code == 200
        две = client.get(f"/ratings?group=developer&value=Dev+One&{СЕНТЯБРЬ_2}")
        замечания_рс = две.get_data(as_text=True).split("rt-viol__cluster")[1]
        assert "За период нет данных РС." in замечания_рс
        # Сравнение девелоперов и стран (D551) — у УК: Dev One со своими странами.
        сравнение = две.get_data(as_text=True).split('id="rt-compare"')[1].split("</section>")[0]
        assert "Dev One" in сравнение and "rt-cmp__v is-" in сравнение

    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="GE").test_client() as client:
        assert войти(client).status_code == 302
        # Период РС второй половины сентября: квартал теперь усредняет и прошлый период.
        страница = client.get(f"/ratings?group=developer&value=Dev+One&{СЕНТЯБРЬ_2}")
        assert страница.status_code == 200
        текст = страница.get_data(as_text=True)
        assert "97.5" in текст
        assert "/ratings/imports" not in текст
        assert 'id="rt-compare"' not in текст  # D551: сравнение — только УК
        assert (
            client.post(
                "/ratings/import", data={"file": (io.BytesIO(b"x"), "x.csv")}, headers=ORIGIN
            ).status_code
            == 403
        )
