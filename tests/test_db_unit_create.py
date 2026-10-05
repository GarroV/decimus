"""Заведение НОВОЙ точки справочника: дубль — отказ, а не тихое обновление (#437).

Ядро: `upsert_unit` на совпавшее имя обновляет существующую строку — для
загрузки справочника это правильно, для человека с формой «Новая пиццерия» нет:
опечатка в чужом номере молча переписала бы географию чужой точки. Поэтому
проверяется не «вставилось», а что существующее осталось нетронутым.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.directory import create_unit, resolve_unit, upsert_unit  # noqa: E402
from src.db.errors import PushError, UnitExistsError  # noqa: E402

pytestmark = requires_db

УК = "HQ"


@pytest.fixture(autouse=True)
def _пространства(request: pytest.FixtureRequest) -> None:
    if "db_env" in request.fixturenames:
        завести_пространства(request.getfixturevalue("pg_dsn"), УК)


def _строка(dsn: str, unit_id: str) -> tuple[object, ...] | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select name, country, city from units where id = %s", (unit_id,))
        row = cur.fetchone()
        return None if row is None else tuple(row)


def test_новая_точка_заводится_с_географией_и_синонимом(db_env: str) -> None:
    заведена = create_unit(
        "Belgrade-6", country="rs", city="beograd", aliases=("Белград 6",), tenant=УК
    )
    unit_id = заведена.id
    assert заведена.taken_aliases == ()

    assert _строка(db_env, unit_id) == ("Belgrade-6", "RS", "beograd")
    по_синониму = resolve_unit("белград  6", tenant=УК)
    assert по_синониму is not None and по_синониму.id == unit_id


def test_дубль_по_имени_отказ_и_прежняя_строка_нетронута(db_env: str) -> None:
    прежняя = upsert_unit("Belgrade-1", country="RS", city="beograd", tenant=УК)

    with pytest.raises(UnitExistsError) as отказ:
        create_unit("belgrade-1", country="ME", city="podgorica", tenant=УК)

    assert (отказ.value.unit_id, отказ.value.name) == (прежняя, "Belgrade-1")
    assert _строка(db_env, прежняя) == ("Belgrade-1", "RS", "beograd")


def test_имя_совпавшее_с_синонимом_чужой_точки_дубль(db_env: str) -> None:
    прежняя = upsert_unit("Yerevan-2", country="AM", aliases=("Ереван-2",), tenant=УК)

    with pytest.raises(UnitExistsError) as отказ:
        create_unit("Ереван-2", country="AM", tenant=УК)

    assert отказ.value.unit_id == прежняя


def test_синоним_новой_точки_называющий_существующую_дубль(db_env: str) -> None:
    прежняя = upsert_unit("Тбилиси-1", tenant=УК)

    with pytest.raises(UnitExistsError) as отказ:
        create_unit("Tbilisi-1", country="GE", aliases=("Тбилиси-1",), tenant=УК)

    assert отказ.value.unit_id == прежняя
    assert resolve_unit("Tbilisi-1", tenant=УК) is None


def test_незаведённое_пространство_отказ(db_env: str) -> None:
    with pytest.raises(PushError):
        create_unit("Belgrade-7", country="RS", tenant="nowhere")


def test_гонка_двух_заведений_даёт_отказ_а_не_вторую_строку(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сверка не увидела точку — её завели между сверкой и вставкой.

    Уникальный ключ имени не даёт второй строки, и вторая вставка обязана
    стать тем же отказом «уже есть», а не «база не вставила».
    """
    import src.db.directory as directory

    прежняя = upsert_unit("Belgrade-2", country="RS", tenant=УК)
    настоящая = directory._existing
    вызовов: list[tuple[object, ...]] = []

    def _слепая_первая_сверка(*args: object) -> object:
        вызовов.append(args)
        return None if len(вызовов) == 1 else настоящая(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(directory, "_existing", _слепая_первая_сверка)

    with pytest.raises(UnitExistsError) as отказ:
        create_unit("Belgrade-2", country="RS", tenant=УК)

    assert отказ.value.unit_id == прежняя
    assert _строка(db_env, прежняя) == ("Belgrade-2", "RS", None)


def test_синоним_занятый_в_гонке_возвращается_а_точка_остаётся(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сверка синонима не увидела чужой; запись синонима упёрлась в ключ.

    Точка заведена верно и не откатывается, но потеря написания не молчит:
    оно приходит в `taken_aliases`, а синоним по-прежнему ведёт к прежней точке.
    """
    import src.db.directory as directory

    чужая = upsert_unit("Novi Sad-1", country="RS", aliases=("Нови Сад 12",), tenant=УК)
    monkeypatch.setattr(directory, "_existing", lambda *_args: None)

    заведена = create_unit("Novi Sad-12", country="RS", aliases=("Нови Сад 12",), tenant=УК)

    assert заведена.taken_aliases == ("Нови Сад 12",)
    assert _строка(db_env, заведена.id) == ("Novi Sad-12", "RS", None)
    по_синониму = resolve_unit("Нови Сад 12", tenant=УК)
    assert по_синониму is not None and по_синониму.id == чужая
