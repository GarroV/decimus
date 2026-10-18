"""Имена одноразовых тестовых баз и уборка сирот после оборванных прогонов (#565).

Каждый тест с базой заводит свою `dodo_audit_test_*` и удаляет её в `finally`.
Убитый прогон (обрыв туннеля, `kill`, лимит) до `finally` не доходит, и база
остаётся на тестовом сервере навсегда: к 14.10.2026 их накопилось больше сотни.

Поэтому в имени лежит время создания, и прогон перед стартом удаляет базы
старше `ORPHAN_AGE_S`, к которым никто не подключён. Чужой идущий прогон их не
теряет: его базы моложе порога, а занятая база не удаляется (без `force`).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterable

PREFIX = "dodo_audit_test_"

#: Самый долгий полный прогон через туннель — около часа (#530); база,
#: прожившая шесть, заведомо брошена.
ORPHAN_AGE_S = 6 * 3600

_STAMPED = re.compile(rf"^{PREFIX}(\d{{10}})_[0-9a-f]+$")


def new_name(now: float | None = None) -> str:
    """Имя новой тестовой базы: время создания и случайный хвост."""
    stamp = int(time.time() if now is None else now)
    return f"{PREFIX}{stamp}_{uuid.uuid4().hex[:8]}"


def orphans(names: Iterable[str], busy: Iterable[str], *, now: float) -> list[str]:
    """Какие базы удалить: с отметкой времени, старше порога и без подключений.

    Базы старого вида (без отметки) не трогаются: возраст у них не узнать, и
    такая база может принадлежать идущему прогону со старым кодом.
    """
    занятые = set(busy)
    выбор = []
    for имя in names:
        метка = _STAMPED.match(имя)
        if метка is None or имя in занятые:
            continue
        if now - int(метка.group(1)) > ORPHAN_AGE_S:
            выбор.append(имя)
    return sorted(выбор)


def sweep(maintenance_dsn: str) -> list[str]:
    """Удалить сиротские тестовые базы на сервере; вернуть, что удалено.

    Отказ удалить одну базу (к ней подключились между выборкой и удалением)
    не мешает остальным и не роняет прогон: уборка — попутная работа.
    """
    import psycopg
    from psycopg import sql

    удалено: list[str] = []
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        имена = [
            r[0]
            for r in conn.execute(
                "select datname from pg_database where datname like %s", (PREFIX + "%",)
            )
        ]
        занятые = [
            r[0]
            for r in conn.execute(
                "select distinct datname from pg_stat_activity where datname like %s",
                (PREFIX + "%",),
            )
        ]
        for имя in orphans(имена, занятые, now=time.time()):
            try:
                conn.execute(sql.SQL("drop database if exists {}").format(sql.Identifier(имя)))
            except psycopg.Error:
                continue
            удалено.append(имя)
    return удалено
