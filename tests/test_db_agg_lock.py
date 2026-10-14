"""#788: замок сборщика агрегаторов — второй держатель его не получает."""

from __future__ import annotations

import pytest
from conftest import requires_db

pytest.importorskip("psycopg")

from src.db import agg_store

pytestmark = requires_db


def test_второй_сборщик_замок_не_получает(db_env: str) -> None:
    with agg_store.collector_lock() as первый:
        assert первый is True
        with agg_store.collector_lock() as второй:
            assert второй is False, "два сборщика собирают одновременно"


def test_замок_отпускается_после_сбора(db_env: str) -> None:
    with agg_store.collector_lock() as первый:
        assert первый
    with agg_store.collector_lock() as снова:
        assert снова is True, "замок остался висеть после сбора"
