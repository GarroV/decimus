"""D199: между обходом и историей сети стоит человек.

Почему это ядро, а не экран. Слитая проверка до вычитки — ещё не факт: её
записи правятся, зона и пункт могут оказаться перепутаны. Пока такая проверка
считается историей, она (1) стоит в отчётности партнёра как результат,
(2) становится «предыдущей» для подсказки о повторе, а повтор стоит вдвое
(D191). То есть невычитанная запись способна удвоить вычет в следующей
проверке — это деньги, и ошибка здесь молчит.

Поэтому проверяется ровно граница: что считается историей, что правится и что
запечатано.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.review import accept_inspection  # noqa: E402

from src.db.errors import DbError  # noqa: E402 — после importorskip намеренно
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import list_inspections, previous_codes  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"
ТОЧКА = "Белград-1"


def _слить(chat_id: int, *, дата: str, код: str = "CLN05", зона: str = "hot_kitchen") -> str:
    """Проверка, доведённая до слива официальным контрактом домена."""
    start_inspection(
        chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant=ТЕНАНТ, date=дата
    )
    add_finding(chat_id, code=код, level="D1", zone=зона, text="нагар на печи")
    return push_inspection(chat_id)


def _статус(dsn: str, inspection_id: str) -> str:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select status from inspections where id = %s", (inspection_id,))
        return str(cur.fetchone()[0])  # type: ignore[index]


# --- что считается историей -----------------------------------------------------


def test_слитая_проверка_ждёт_вычитки_а_не_попадает_в_историю(
    domain_env: Path, db_env: str
) -> None:
    # Arrange / Act
    ид = _слить(4001, дата="2026-09-25")

    # Assert — строка в базе есть, историей она ещё не стала.
    assert _статус(db_env, ид) == "review"
    assert [i.id for i in list_inspections(tenant=ТЕНАНТ)] == []


def test_принятая_проверка_становится_историей(domain_env: Path, db_env: str) -> None:
    # Arrange
    ид = _слить(4002, дата="2026-09-25")

    # Act
    accept_inspection(ид, tenant=ТЕНАНТ, author="director")

    # Assert
    assert _статус(db_env, ид) == "finalized"
    assert [i.id for i in list_inspections(tenant=ТЕНАНТ)] == [ид]


def test_невычитанная_проверка_не_становится_предыдущей_для_подсказки_о_повторе(
    domain_env: Path, db_env: str
) -> None:
    """Повтор стоит вдвое (D191) — считать его по невычитанной записи нельзя."""
    # Arrange — принятая проверка с одним кодом и свежая непринятая с другим.
    принятая = _слить(4003, дата="2026-09-20", код="CLN05")
    accept_inspection(принятая, tenant=ТЕНАНТ, author="director")
    _слить(4004, дата="2026-09-24", код="CLN02", зона="dishwashing")

    # Act
    коды = previous_codes(tenant=ТЕНАНТ, unit=ТОЧКА)

    # Assert — подсказка опирается на принятую, а не на ту, что ещё вычитывают.
    assert коды == {"CLN05"}


# --- что правится, а что запечатано ---------------------------------------------


def test_запись_проверки_на_приёмке_правится(domain_env: Path, db_env: str) -> None:
    """Ошибка аудитора чинится на приёмке — ради этого этап и заводился."""
    # Arrange
    ид = _слить(4005, дата="2026-09-25")

    # Act
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("update findings set zone = 'hall' where inspection_id = %s", (ид,))
        тронуто = cur.rowcount

    # Assert
    assert тронуто == 1


def test_принятая_проверка_запечатана(domain_env: Path, db_env: str) -> None:
    """Заслон миграции 0004 стоит на finalized и после приёмки.

    Проверяется ФАКТ, а не исключение: построчная политика не отказывает
    громко — она прячет строку от правки, и `update` возвращает «тронуто 0».
    Тест на `raises` был бы зелёным и при снятой защите.
    """
    # Arrange
    ид = _слить(4006, дата="2026-09-25")
    accept_inspection(ид, tenant=ТЕНАНТ, author="director")

    # Act
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("update findings set zone = 'hall' where inspection_id = %s", (ид,))
        тронуто = cur.rowcount
        cur.execute("select zone from findings where inspection_id = %s", (ид,))
        зона = cur.fetchone()[0]  # type: ignore[index]

    # Assert
    assert тронуто == 0, "запечатанная проверка поддалась правке"
    assert зона == "hot_kitchen", "зона записи изменилась у принятой проверки"


def test_принять_дважды_нельзя(domain_env: Path, db_env: str) -> None:
    """Переход односторонний: второй раз — отказ, а не тихое «уже принято».

    Отказ даёт ПОЛИТИКА базы (принятая строка спрятана от правки), а не
    условие `status = 'review'` в запросе приёмки: проверено порчей — с
    выброшенным условием тест остаётся зелёным. Условие оставлено второй
    линией, но защита живёт в базе, и это правильное место.
    """
    # Arrange
    ид = _слить(4007, дата="2026-09-25")
    accept_inspection(ид, tenant=ТЕНАНТ, author="director")

    # Act / Assert
    with pytest.raises(DbError):
        accept_inspection(ид, tenant=ТЕНАНТ, author="director")
