"""Уборка тестовых баз, брошенных оборванными прогонами (#565): что удаляется."""

from __future__ import annotations

import db_names

СЕЙЧАС = 2_000_000_000.0
СТАРАЯ = f"{db_names.PREFIX}{int(СЕЙЧАС) - db_names.ORPHAN_AGE_S - 1}_aaaa0001"
СВЕЖАЯ = f"{db_names.PREFIX}{int(СЕЙЧАС) - 60}_aaaa0002"
ЗАНЯТАЯ = f"{db_names.PREFIX}{int(СЕЙЧАС) - db_names.ORPHAN_AGE_S - 1}_aaaa0003"
БЕЗ_МЕТКИ = f"{db_names.PREFIX}0123456789ab"


def test_удаляется_только_старая_и_свободная_с_меткой_времени() -> None:
    выбор = db_names.orphans(
        [СТАРАЯ, СВЕЖАЯ, ЗАНЯТАЯ, БЕЗ_МЕТКИ, "dodo_audit_service"], [ЗАНЯТАЯ], now=СЕЙЧАС
    )
    assert выбор == [СТАРАЯ]


def test_новое_имя_несёт_время_и_узнаётся_уборкой() -> None:
    имя = db_names.new_name(now=СЕЙЧАС - db_names.ORPHAN_AGE_S - 10)
    assert len(имя) <= 63
    assert db_names.orphans([имя], [], now=СЕЙЧАС) == [имя]
    assert db_names.orphans([db_names.new_name(now=СЕЙЧАС)], [], now=СЕЙЧАС) == []
