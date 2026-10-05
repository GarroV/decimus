"""Волна 1 (#340): УК читает всё, партнёр — пиццерии своей страны; справочник один (D283, D284).

Партнёр видит проверки пиццерий своих стран, кто бы их ни проводил (D289), и
не видит пиццерий чужих стран. Справочник у всей сети один — у УК; своих точек
партнёр не заводит (D234). Граница держится схемой: сторож-триггер не пишет
проверку партнёра на точку чужой страны, даже если бот её пропустил.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import привязать_страну, слить_проверку, точка_справочника  # noqa: E402

from src.db import move, previews, queries, reports  # noqa: E402
from src.db.directory import list_units  # noqa: E402
from src.db.errors import DbError, PushError, UnitRefusedError  # noqa: E402
from src.db.reach import Reach, countries_of, reach_of  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> dict[str, str]:
    """Справочник УК: Batumi-1 (GE), Yerevan-1 (AM). Пространство GE привязано к GE."""
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    return {
        "уК_батуми": слить_проверку(unit="Batumi-1", tenant="HQ"),
        "уК_ереван": слить_проверку(unit="Yerevan-1", tenant="HQ"),
        "партнёр_батуми": слить_проверку(unit="Batumi-1", tenant="GE"),
    }


def _ids(reach: Reach) -> set[str]:
    return {row.id for row in queries.list_inspections(reach=reach, limit=100)}


def test_уК_читает_все_проверки(сеть: dict[str, str]) -> None:
    assert set(сеть.values()) <= _ids(reach_of("HQ"))


def test_партнёр_видит_только_свою_страну(сеть: dict[str, str]) -> None:
    видно = _ids(reach_of("GE"))
    assert сеть["партнёр_батуми"] in видно
    assert сеть["уК_батуми"] in видно, "D289: партнёр видит проверки УК своей страны"
    assert сеть["уК_ереван"] not in видно


def test_чужая_карточка_партнёру_не_найдена(сеть: dict[str, str]) -> None:
    assert queries.get_inspection(сеть["уК_ереван"], reach=reach_of("GE")) is None
    своя = queries.get_inspection(сеть["уК_батуми"], reach=reach_of("GE"))
    assert своя is not None, "пустота выше была бы по другой причине"


def test_пространство_без_стран_не_видит_ничего(сеть: dict[str, str], pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('XX') on conflict do nothing")
    охват = reach_of("XX")
    assert охват.countries == (), "закрыто по умолчанию: без стран — пусто, а не всё"
    assert _ids(охват) == set()
    assert list_units(reach=охват) == []


def test_страны_пространства_читаются_из_базы(сеть: dict[str, str]) -> None:
    assert countries_of("GE") == ("GE",)
    assert reach_of("GE") == Reach(tenant="GE", tenants=None, countries=("GE",))
    assert reach_of("HQ") == Reach(tenant="HQ", tenants=None, countries=None)


def test_справочник_партнёра_это_точки_его_страны(сеть: dict[str, str]) -> None:
    assert [u.name for u in list_units(reach=reach_of("GE"))] == ["Batumi-1"]
    assert {u.name for u in list_units(reach=reach_of("HQ"))} == {"Batumi-1", "Yerevan-1"}
    assert [u.name for u in list_units(reach=reach_of("HQ"), country="am")] == ["Yerevan-1"]


def test_сводки_и_справочные_чтения_стоят_на_охвате(сеть: dict[str, str]) -> None:
    """Агрегаты экрана «Обзор» и справочные чтения — тоже граница, а не только список."""
    ge = reach_of("GE")
    assert queries.units_total(reach=ge) == 1
    assert set(queries.unit_ids(reach=ge)) == {"Batumi-1"}
    assert set(queries.unit_geography(reach=ge)) == {"Batumi-1"}
    assert set(queries.class_counts(reach=ge)) == {сеть["уК_батуми"], сеть["партнёр_батуми"]}
    assert set(queries.worst_zones(reach=ge)) == {сеть["уК_батуми"], сеть["партнёр_батуми"]}
    assert {z[4] for z in queries.zone_losses(reach=ge)} == {2}
    assert [s[3] for s in queries.systemic_findings(reach=ge)] == [1]
    assert {f.inspection_id for f in queries.findings_by_unit(reach=ge, unit="Yerevan-1")} == set()
    assert queries.units_total(reach=reach_of("HQ")) == 2


def _след_проверки(pg_dsn: str, inspection_id: str) -> None:
    """Отчёт, сжатая копия кадра и перенос у проверки — всё, что читают карточные чтения."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into reports (inspection_id, storage_path, size_bytes) "
            "values (%s, 's3://b/report.pdf', 10)",
            (inspection_id,),
        )
        cur.execute(
            "insert into photos (finding_id, inspection_id, telegram_file_id, preview_path) "
            "select f.id, f.inspection_id, 'кадр', 's3://b/preview.jpg' "
            "from findings f where f.inspection_id = %s limit 1",
            (inspection_id,),
        )
        cur.execute(
            "insert into inspection_moves (tenant_code, inspection_id, old_date, new_date, "
            "old_unit_id, new_unit_id, reason, moved_by) "
            "select tenant_code, id, inspection_date - 1, inspection_date, unit_id, unit_id, "
            "'перепутана дата', 'тест' from inspections where id = %s",
            (inspection_id,),
        )


def test_карточные_чтения_чужой_страны_пусты(сеть: dict[str, str], pg_dsn: str) -> None:
    """Отчёт, кадры и переносы проверки чужой страны партнёру не отдаются.

    Рядом — УК, которой те же чтения отдают: пустота у партнёра без этой
    сверки была бы и от отсутствия данных, а не от охвата.
    """
    чужая = сеть["уК_ереван"]
    _след_проверки(pg_dsn, чужая)
    уК, ge = reach_of("HQ"), reach_of("GE")

    assert reports.latest_report(чужая, reach=уК) is not None
    assert previews.finding_previews(чужая, reach=уК) != {}
    assert move.list_moves(чужая, reach=уК) != ()

    assert reports.latest_report(чужая, reach=ge) is None
    assert previews.finding_previews(чужая, reach=ge) == {}
    assert move.list_moves(чужая, reach=ge) == ()


def test_проверка_партнёра_ссылается_на_точку_справочника_уК(
    сеть: dict[str, str], pg_dsn: str
) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select u.tenant_code from inspections i join units u on u.id = i.unit_id "
            "where i.id = %s",
            (сеть["партнёр_батуми"],),
        )
        assert cur.fetchone() == ("HQ",)


def test_база_не_пишет_проверку_партнёра_на_точку_чужой_страны(
    сеть: dict[str, str], db_env: str
) -> None:
    """Review Focus 7: сторож в схеме, а не только в боте.

    Строка пишется в обход слива — прямой вставкой под ролью приложения: так
    отказ приходит от схемы, а не от кода, который точку и не нашёл бы.
    """
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("select id from units where name = 'Yerevan-1'")
        (ереван,) = cur.fetchone() or (None,)
        with pytest.raises(psycopg.errors.RaiseException, match="не из справочника страны"):
            cur.execute(
                "insert into inspections (tenant_code, unit_id, chat_id, kind, inspection_date, "
                "report_lang, ui_lang, speech_lang, checklist_version, pct, grade, "
                "source_fingerprint, status) values ('GE', %s, 1, 'planned', '2026-09-03', "
                "'ru', 'ru', 'ru', 'v1', 100, 'A', 'отпечаток-сторожа', 'draft')",
                (ереван,),
            )


def test_слив_партнёра_на_точку_чужой_страны_отказ(сеть: dict[str, str]) -> None:
    """Точка есть в справочнике УК, но страна не своя — отказ сторожа, а не запись."""
    with pytest.raises(PushError, match="нет в справочнике стран пространства GE"):
        слить_проверку(unit="Yerevan-1", tenant="GE")


def test_чужая_страна_и_вне_справочника_отказывают_одним_текстом(сеть: dict[str, str]) -> None:
    """Ревью #340, п.10: отказ не подтверждает, что пиццерия в сети есть."""
    отказы = []
    for точка in ("Yerevan-1", "Yerevan-99"):
        with pytest.raises(UnitRefusedError) as отказ:
            слить_проверку(unit=точка, tenant="GE")
        assert отказ.value.unit == точка
        отказы.append(str(отказ.value).replace(точка, "…"))
    assert отказы[0] == отказы[1]


def test_слив_партнёра_не_заводит_новую_точку(сеть: dict[str, str]) -> None:
    """#471: у партнёра незнакомое имя — отказ, а не новая пиццерия (D234)."""
    with pytest.raises(DbError, match="справочник"):
        слить_проверку(unit="Batumi-99", tenant="GE")
    assert "Batumi-99" not in {u.name for u in list_units(reach=reach_of("HQ"))}


def test_одна_страна_одно_пространство(сеть: dict[str, str], pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('G2') on conflict do nothing")
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("insert into space_countries (country, tenant_code) values ('GE', 'G2')")


def test_изоляция_партнёров_охватом_своего_тенанта(сеть: dict[str, str]) -> None:
    """`tenants=(t,)` — только свои проверки: проверка УК той же страны не видна."""
    свои = _ids(Reach(tenant="GE", tenants=("GE",), countries=None))
    assert свои == {сеть["партнёр_батуми"]}
