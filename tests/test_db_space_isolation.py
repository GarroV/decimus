"""Изоляция пространств держит сама база (аудит 12.10, F-037, F-005).

До миграции `0061` политики роли приложения на данных пространств были
`using (true)`: запрос без условия охвата отдал бы чужое. Здесь проверяется не
«фильтр в запросе работает» (это `test_db_queries_tenant.py`), а обратное:
запрос БЕЗ условия охвата, под ролью приложения, от имени одного пространства
не видит и не правит строк другого.

Пространства: `GE` и `AM` — партнёры, каждый в стране своего кода; у УК по
проверке в каждой из стран (их партнёр страны видит, D289). Каждый раз набор
сам доказывает, что ловит утечку: снимает политику и видит чужое
(`test_без_политики_чужое_видно`), иначе зелёный цвет остальных ничего бы не
значил.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import (  # noqa: E402
    привязать_пространства,
    слить_проверку,
    точка_пространства,
    точка_справочника,
)

from src.db.queries import list_inspections  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.db.space import SYSTEM_SPACE, acting_space  # noqa: E402

pytestmark = requires_db

А = "GE"
Б = "AM"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def мир(domain_env: Path, db_env: str, pg_dsn: str) -> dict[str, str]:
    """По проверке у каждого партнёра и у УК в каждой стране; их `id` по имени."""
    привязать_пространства(pg_dsn, А, Б)
    точка_пространства("Тбилиси-1", tenant=А)
    точка_пространства("Ереван-1", tenant=Б)
    точка_справочника("Батуми-1", country=А)
    точка_справочника("Гюмри-1", country=Б)
    return {
        "a": слить_проверку(unit="Тбилиси-1", tenant=А),
        "b": слить_проверку(unit="Ереван-1", tenant=Б),
        "hq_a": слить_проверку(unit="Батуми-1", tenant="HQ"),
        "hq_b": слить_проверку(unit="Гюмри-1", tenant="HQ"),
    }


@contextmanager
def от_имени(dsn: str, space: str | None) -> Iterator[Any]:
    """Своё соединение роли приложения; `space=None` — пространство не поставлено."""
    with psycopg.connect(dsn) as conn:
        if space is not None:
            conn.execute("select set_config('decimus.space', %s, false)", (space,))
            conn.commit()
        yield conn


def _ids(conn: Any, sql: str) -> set[str]:
    return {str(row[0]) for row in conn.execute(sql).fetchall()}


def test_партнёр_без_условия_охвата_видит_только_свой_охват(
    мир: dict[str, str], db_env: str
) -> None:
    """Голый `select` без условия охвата: своё и проверки УК своей страны (D289), не больше."""
    with от_имени(db_env, А) as conn:
        видно = _ids(conn, "select id from inspections")
        находки = _ids(conn, "select inspection_id from findings")
    assert видно == {мир["a"], мир["hq_a"]}, (
        f"Пространство {А} без условия охвата видит проверки {видно - {мир['a'], мир['hq_a']}} "
        f"сверх своего охвата: политика базы не держит изоляцию (F-037)"
    )
    assert находки <= видно, "Находки чужих проверок видны мимо политики проверки"


def test_уК_видит_всю_сеть(мир: dict[str, str], db_env: str) -> None:
    with от_имени(db_env, "HQ") as conn:
        assert _ids(conn, "select id from inspections") == set(мир.values())


def test_без_пространства_база_отказывает_а_не_молчит(мир: dict[str, str], db_env: str) -> None:
    """Забытая дверь — ошибка, а не пустой экран и не вся сеть."""
    with (
        от_имени(db_env, None) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege) as отказ,
    ):
        conn.execute("select id from inspections").fetchall()
    assert "decimus.space" in str(отказ.value)


#: Находка в проверку — запись строки-ребёнка; `source` свободный текст.
ВСТАВКА_НАХОДКИ = (
    "insert into findings (inspection_id, n, code, level, zone, source) "
    "values (%s, 99, 'CLN03', 'D1', 'hot_kitchen', 'manual')"
)


@pytest.fixture
def черновики(мир: dict[str, str]) -> dict[str, str]:
    """Неподтверждённые проверки: подтверждённую запрещает править `0004`, а не `0061`."""
    return {
        "a": слить_проверку(unit="Тбилиси-1", tenant=А, accept=False),
        "hq_a": слить_проверку(unit="Батуми-1", tenant="HQ", accept=False),
        "b": слить_проверку(unit="Ереван-1", tenant=Б, accept=False),
    }


def test_партнёр_не_правит_чужое_даже_видимое(черновики: dict[str, str], db_env: str) -> None:
    """Запись — только своё (D283): ни чужого партнёра, ни видимую проверку УК."""
    правка = "update inspections set report_lang = report_lang where id = %s"
    with от_имени(db_env, А) as conn:
        for чья in ("b", "hq_a"):
            n = conn.execute(правка, (черновики[чья],)).rowcount
            assert n == 0, f"Пространство {А} изменило чужую проверку ({чья})"
        n = conn.execute(правка, (черновики["a"],)).rowcount
        assert n == 1, "Своя проверка обязана оставаться доступной на запись"
        conn.execute(ВСТАВКА_НАХОДКИ, (черновики["a"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(ВСТАВКА_НАХОДКИ, (черновики["hq_a"],))


def test_запрос_продукта_с_чужим_охватом_режется_базой(мир: dict[str, str]) -> None:
    """Охват в запросе шире пространства (ошибка двери) — база отдаёт только его охват."""
    with acting_space(А):
        видно = {строка.id for строка in list_inspections(reach=reach_of("HQ"))}
    assert видно == {мир["a"], мир["hq_a"]}, (
        f"Чтение продукта с охватом всей сети от имени {А} отдало {видно}"
    )


def test_рейтинги_видят_все_а_пишет_только_уК(мир: dict[str, str], db_env: str) -> None:
    """D327: чтение рейтингов открыто всем; запись роли приложения — УК и служебной работе."""
    with от_имени(db_env, А) as conn:
        conn.execute("select count(*) from ratings.countries").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "insert into ratings.countries (code, name_ru, name_en, is_imf) "
                "values ('ZZ', 'Тест', 'Test', true)"
            )
    with от_имени(db_env, "HQ") as conn:
        conn.execute(
            "insert into ratings.countries (code, name_ru, name_en, is_imf) "
            "values ('ZZ', 'Тест', 'Test', true)"
        )
        conn.rollback()


def test_журнал_API_пишет_только_служебная_дверь(мир: dict[str, str], db_env: str) -> None:
    вставка = (
        "insert into api.access_log (token_id, path, status, client) values (null, '/x', 401, null)"
    )
    with от_имени(db_env, "HQ") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(вставка)
    with от_имени(db_env, SYSTEM_SPACE) as conn:
        conn.execute(вставка)
        conn.rollback()


def test_без_политики_чужое_видно(
    мир: dict[str, str], черновики: dict[str, str], db_env: str, pg_dsn: str
) -> None:
    """Контроль самого набора: сняли политику — пространство видит чужое.

    Без этого зелёный `test_партнёр_без_условия_охвата...` мог бы значить лишь
    то, что чужих строк в базе не оказалось.
    """
    with psycopg.connect(pg_dsn, autocommit=True) as owner:
        owner.execute("drop policy inspections_space_reads on inspections")
        owner.execute("drop policy findings_space_inserts on findings")
    with от_имени(db_env, А) as conn:
        видно = _ids(conn, "select id from inspections")
        assert мир["b"] in видно, "Без политики чужая проверка не видна — набор ничего не ловит"
        conn.execute(ВСТАВКА_НАХОДКИ, (черновики["hq_a"],))
        conn.rollback()


def test_пространство_не_подменяется_внутри_двери() -> None:
    """Дверь сказала, чьё обращение; код внутри не может молча сменить его на служебное."""
    from src.db.errors import DbError

    with acting_space(А), pytest.raises(DbError), acting_space(SYSTEM_SPACE):
        pass


def test_запасное_пространство_только_у_оснастки_тестов() -> None:
    """`_FALLBACK` — шов для тестов; код продукта его не трогает."""
    чужие = [
        str(путь.relative_to(ROOT))
        for каталог in ("src", "tools")
        for путь in (ROOT / каталог).rglob("*.py")
        if путь.name != "space.py" and re.search(r"\b_FALLBACK\b", путь.read_text(encoding="utf-8"))
    ]
    assert чужие == [], f"Запасное пространство трогает код продукта: {чужие}"


def test_новая_таблица_данных_без_политики_пространства_не_проходит() -> None:
    """Таблица с `tenant_code`, заведённая после `0061`, обязана получить политику пространства.

    Иначе следующая таблица данных снова держалась бы только на условии охвата.
    Таблицы учёток и входа (`web_users`, `mcp_tokens`, …) опознают человека ДО того,
    как известно его пространство, и перечислены здесь явно.
    """
    миграции = sorted((ROOT / "src" / "db" / "migrations").glob("*.sql"))
    после = [м for м in миграции if м.name > "0061"]
    без_политики = []
    for м in после:
        текст = м.read_text(encoding="utf-8").lower()
        for таблица in re.findall(r"create table (?:if not exists )?([\w.]+)\s*\(", текст):
            тело = текст.split(f"create table {таблица}", 1)[1].split(");", 1)[0]
            if "tenant_code" in тело and "decimus_space" not in текст:
                без_политики.append(f"{м.name}: {таблица}")
    assert без_политики == [], (
        f"Таблицы с tenant_code без политики пространства (decimus_space*): {без_политики}"
    )


def _jpeg(цвет: tuple[int, int, int]) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), цвет).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_уборка_кадров_не_удаляет_кадр_другого_пространства(
    domain_env: Path, db_env: str, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Уборка мини-аппа (F-033) видит ссылки ВСЕЙ сети, а не одного пространства.

    Кадр сданной проверки партнёра Б лежит только в папке состояния; уборка,
    увидевшая лишь чьё-то одно пространство, сочла бы его брошенным и удалила.
    """
    import os
    import shutil
    import time

    from src.bot import upload_sweeper
    from src.db import space
    from src.db.push import push_inspection
    from src.domain import add_finding, check_environment, start_inspection
    from src.domain.engine import chat_dir
    from src.domain.upload_sweep import UNATTACHED_TTL_SEC
    from src.domain.uploads import save_upload, upload_file

    привязать_пространства(pg_dsn, Б)
    точка_пространства("Ереван-1", tenant=Б)
    settings = check_environment()
    чат = 4343
    кадр_б = save_upload(_jpeg((10, 20, 30)), settings, owner=чат)
    брошенный = save_upload(_jpeg((40, 50, 60)), settings, owner=чат)
    start_inspection(чат, unit="Ереван-1", kind="planned", report_lang="ru", tenant=Б)
    add_finding(чат, code="CLN05", level="D1", zone="hot_kitchen", text="нагар", photos=[кадр_б])
    push_inspection(чат)
    shutil.rmtree(chat_dir(чат, settings))
    давно = time.time() - UNATTACHED_TTL_SEC - 60
    for ref in (кадр_б, брошенный):
        путь = upload_file(ref, settings)  # type: ignore[arg-type]
        assert путь is not None
        os.utime(путь, (давно, давно))

    # Как на проде: запасного пространства нет, дверь его не поставила.
    monkeypatch.setattr(space, "_FALLBACK", None)
    with acting_space(А):
        assert upload_sweeper.sweep_once() is None, (
            "Уборка внутри двери партнёра обязана пропустить проход, а не убирать"
        )
    assert upload_file(кадр_б, settings) is not None
    итог = upload_sweeper.sweep_once()
    assert итог is not None and итог.frames == 1
    assert upload_file(кадр_б, settings) is not None, "кадр пространства Б удалён уборкой"
    assert upload_file(брошенный, settings) is None, "брошенный кадр не убран"
