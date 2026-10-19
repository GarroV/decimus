"""Расход модели (D537, миграция `0078`) — уровень базы.

Ядро доступа: расход видят только главный админ и админ УК; прочим функция чтения
отдаёт пустое, а прямого права на таблицу у роли приложения нет. Всё идёт под ролью
приложения (`db_env`), как на площадке. Требует живой базы: без неё набор пропускается,
а пропуск — не зелёный.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import model_usage  # noqa: E402
from src.db.web_access import authenticate, create_account, open_session  # noqa: E402
from src.domain.model_usage import ModelCall  # noqa: E402

pytestmark = requires_db

#: Настоящая запись: автоподмена в conftest снимается уже после импорта этого модуля.
_REAL_RECORD = model_usage.record
ПАРОЛЬ = "пароль-учётки-теста-d537-расход"


def _токен(логин: str, роль: str, tenant: str) -> str:
    create_account(логин, tenant=tenant, password=ПАРОЛЬ, role=роль)
    учётка = authenticate(логин, ПАРОЛЬ)
    assert учётка is not None
    return open_session(учётка, ip="198.51.100.1", user_agent="UA").token


@pytest.fixture
def токены(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ", "RS")
    return {
        "super": _токен("sofia", "superadmin", "HQ"),
        "hq_admin": _токен("anna", "admin", "HQ"),
        "partner_admin": _токен("boris", "admin", "RS"),
        "auditor": _токен("dev", "auditor", "HQ"),
    }


def _вызов(**kw: object) -> None:
    base: dict[str, object] = dict(
        kind="recognize", model="gpt-5.6-sol", ok=True, input_tokens=100, output_tokens=10
    )
    _REAL_RECORD(ModelCall(**{**base, **kw}))  # type: ignore[arg-type]


def test_админ_ук_и_главный_админ_видят_суммы_по_четырём_срезам(
    токены: dict[str, str],
) -> None:
    _вызов(inspection_ref="run-1", telegram_id=7)
    _вызов(kind="translate", model="gpt-6-luna", inspection_ref="run-1", telegram_id=7)
    _вызов(ok=False, input_tokens=None, output_tokens=None)

    for кто in ("super", "hq_admin"):
        строки = model_usage.read(токены[кто])
        срезы = {r.dim for r in строки}
        assert срезы == {"day", "kind", "person", "inspection"}
        итог = [r for r in строки if r.dim == "day"]
        assert sum(r.calls for r in итог) == 3
        assert sum(r.failed for r in итог) == 1
        assert sum(r.input_tokens for r in итог) == 200


@pytest.mark.parametrize("кто", ["partner_admin", "auditor"])
def test_остальным_расход_не_отдаётся(токены: dict[str, str], кто: str) -> None:
    _вызов()

    assert model_usage.read(токены[кто]) == ()


def test_без_живой_сессии_пусто(токены: dict[str, str]) -> None:
    _вызов()

    assert model_usage.read("не-токен") == ()


def test_период_режет_по_времени(токены: dict[str, str]) -> None:
    _вызов()
    завтра = datetime.now(UTC) + timedelta(days=1)

    assert model_usage.read(токены["super"], start=завтра) == ()
    assert model_usage.read(токены["super"], end=завтра) != ()


def test_у_роли_приложения_нет_права_читать_таблицу_напрямую(
    токены: dict[str, str], db_env: str
) -> None:
    from src.db.web_access import _connected

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with _connected("проверка прав") as conn, conn.cursor() as cur:
            cur.execute("select * from model_usage")


def test_проверка_названа_пиццерией_и_датой_а_бот_до_сдачи_подписью_вызова(
    токены: dict[str, str],
) -> None:
    _вызов(inspection_ref="run-77", inspection_label="Тбилиси-1 · 2026-10-02")
    _вызов(inspection_ref="run-78")

    строки = {r.key: r.label for r in model_usage.read(токены["super"]) if r.dim == "inspection"}

    assert строки == {"run-77": "Тбилиси-1 · 2026-10-02", "run-78": ""}


def test_telegram_id_превращается_в_учётку_по_привязке_бота(
    токены: dict[str, str],
) -> None:
    from src.db import bot_links

    учётка = authenticate("dev", ПАРОЛЬ)
    assert учётка is not None
    bot_links.redeem(bot_links.issue_link(учётка.id).token, telegram_id=4711)
    _вызов(telegram_id=4711)
    _вызов(telegram_id=4712)

    люди = {r.key: r.label for r in model_usage.read(токены["super"]) if r.dim == "person"}

    # 4711 назван логином и сведён с учёткой; 4712 привязки не имеет и остаётся номером.
    assert люди[учётка.id] == "dev"
    assert люди["tg:4712"] == ""
