"""D218: справка карточки называет сборку чек-листа датой первой проверки по ней.

Молчащая ошибка здесь одна: дата от снятой проверки или от чужой сборки
выглядит так же правдоподобно, как верная.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import accept_pushed, set_retraction_env

pytest.importorskip("psycopg")

from src.db.push import push_inspection
from src.db.queries import edition_first_used, get_inspection
from src.db.reach import own_reach
from src.db.retract import retract_inspection
from src.domain import start_inspection

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _сданная(chat_id: int) -> str:
    start_inspection(chat_id, unit="Белград-1", kind="planned", report_lang="ru", tenant="default")
    ident = push_inspection(chat_id)
    accept_pushed(ident)  # D199: слив оставляет на приёмке
    return ident


def test_дата_сборки_без_снятой_и_без_чужой(domain_env: Path, admin_env: str) -> None:
    # Arrange
    ид = _сданная(911)
    проверка = get_inspection(ид, reach=own_reach("default"))
    assert проверка is not None
    сборка = проверка.inspection.checklist_version

    # Act / Assert — своя сборка: день её проверки.
    assert (
        edition_first_used(reach=own_reach("default"), version=сборка)
        == проверка.inspection.inspection_date
    )
    # Чужая сборка дня не получает.
    assert edition_first_used(reach=own_reach("default"), version="local-000000000000") is None

    # Снятая проверка в счёт не идёт: других по сборке нет — дня нет. Держит
    # это прежде всего роль чтения — снятых она не видит вовсе; фильтр в
    # запросе — второй замок (порча фильтра этот тест не роняет, проверено).
    retract_inspection(ид, tenant="default", reason="дубль")
    assert edition_first_used(reach=own_reach("default"), version=сборка) is None
