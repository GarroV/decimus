"""Сверка хранилища файлов с таблицами (#496): классификация расхождений.

Ошибка здесь тихая: сверка, назвавшая расхождение там, где его нет, учит
людей не верить отчёту, а пропустившая — оставляет версию плана, которую
партнёр видит в истории, а скачать нельзя. Поэтому классификация — чистой
функцией и с тестами до кода; хранилище и база подставляются.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from src.db.errors import StorageError
from src.db.storage import StoredObject
from src.db.storage_reconcile import (
    AREAS,
    Area,
    StoredRow,
    classify,
    reconcile,
)

СЕЙЧАС = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ПОРОГ = timedelta(minutes=10)
ПРЕФИКС = "action-plans/"


def _объект(key: str, *, минут_назад: int = 60) -> StoredObject:
    return StoredObject(key=key, size=100, modified=СЕЙЧАС - timedelta(minutes=минут_назад))


def _строка(ident: str, key: str) -> StoredRow:
    return StoredRow(id=ident, storage_path=f"s3://decimus/{key}")


def _сверить(objects: Sequence[StoredObject], rows: Sequence[StoredRow]):  # type: ignore[no-untyped-def]
    return classify(ПРЕФИКС, objects=objects, rows=rows, now=СЕЙЧАС, grace=ПОРОГ)


def test_matching_object_and_row_is_clean() -> None:
    итог = _сверить([_объект("action-plans/r1/f1")], [_строка("f1", "action-plans/r1/f1")])

    assert итог.clean
    assert (итог.objects, итог.rows, итог.matched) == (1, 1, 1)


def test_object_without_row_is_orphan() -> None:
    итог = _сверить(
        [_объект("action-plans/r1/f1"), _объект("action-plans/r1/f2")],
        [_строка("f1", "action-plans/r1/f1")],
    )

    assert not итог.clean
    assert [o.key for o in итог.orphan_objects] == ["action-plans/r1/f2"]
    assert итог.missing_objects == ()


def test_row_without_object_is_missing() -> None:
    итог = _сверить([], [_строка("f1", "action-plans/r1/f1")])

    assert not итог.clean
    assert [r.id for r in итог.missing_objects] == ["f1"]
    assert итог.orphan_objects == ()


def test_fresh_object_without_row_is_not_counted_but_shown() -> None:
    """Загрузка в эту минуту: объект лёг, строка ещё не закоммичена."""
    итог = _сверить([_объект("action-plans/r1/f1", минут_назад=3)], [])

    assert итог.clean
    assert [o.key for o in итог.fresh_skipped] == ["action-plans/r1/f1"]
    assert итог.orphan_objects == ()


def test_object_exactly_at_grace_boundary_is_orphan() -> None:
    итог = _сверить([_объект("action-plans/r1/f1", минут_назад=10)], [])

    assert [o.key for o in итог.orphan_objects] == ["action-plans/r1/f1"]


def test_bucket_in_link_is_ignored_like_everywhere_else() -> None:
    """Корзину называет конфигурация, а не строка (D054): переезд не ломает сверку."""
    итог = _сверить(
        [_объект("action-plans/r1/f1")],
        [StoredRow(id="f1", storage_path="s3://old-bucket/action-plans/r1/f1")],
    )

    assert итог.clean


@pytest.mark.parametrize(
    "path",
    ["", "action-plans/r1/f1", "https://x/action-plans/r1/f1", "s3://decimus"],
)
def test_unparseable_link_is_bad_link_not_missing(path: str) -> None:
    итог = _сверить([], [StoredRow(id="f1", storage_path=path)])

    assert not итог.clean
    assert [r.id for r in итог.bad_links] == ["f1"]
    assert итог.missing_objects == ()


def test_link_outside_area_prefix_is_bad_link() -> None:
    итог = _сверить([], [_строка("f1", "inspections/i1/p1.jpg")])

    assert [r.id for r in итог.bad_links] == ["f1"]
    assert итог.missing_objects == ()


def test_prefix_is_a_folder_not_a_word_start() -> None:
    """`action-plans-old/...` не лежит под `action-plans/`."""
    итог = _сверить([], [_строка("f1", "action-plans-old/r1/f1")])

    assert [r.id for r in итог.bad_links] == ["f1"]


def test_all_three_cases_together_are_counted_separately() -> None:
    итог = _сверить(
        [
            _объект("action-plans/r1/ok"),
            _объект("action-plans/r1/lost-row"),
            _объект("action-plans/r1/fresh", минут_назад=1),
        ],
        [
            _строка("ok", "action-plans/r1/ok"),
            _строка("no-object", "action-plans/r2/no-object"),
        ],
    )

    assert (итог.objects, итог.rows, итог.matched) == (3, 2, 1)
    assert [o.key for o in итог.orphan_objects] == ["action-plans/r1/lost-row"]
    assert [r.id for r in итог.missing_objects] == ["no-object"]
    assert [o.key for o in итог.fresh_skipped] == ["action-plans/r1/fresh"]
    assert итог.discrepancies == 2


def test_areas_cover_action_plans_and_prescriptions_with_their_prefixes() -> None:
    """Префиксы берутся у модулей, которые кладут файлы, а не пишутся второй раз."""
    from src.db.action_plans import object_key as plan_key
    from src.db.prescriptions_write import object_key as reply_key

    по_имени = {a.name: a for a in AREAS}

    assert plan_key("r", "f").startswith(по_имени["action-plans"].prefix)
    assert reply_key("p", "r").startswith(по_имени["prescriptions"].prefix)
    assert all(a.prefix.endswith("/") for a in AREAS)


# ── Сквозной ход без сети: строки читаются ДО списка объектов ───────────────


class _Порядок:
    def __init__(self) -> None:
        self.шаги: list[str] = []


def test_reconcile_reads_rows_before_listing_objects() -> None:
    """Обратный порядок дал бы ложное «строки без объекта» на загрузке в эту минуту.

    Строка коммитится только после того, как объект лёг, поэтому строка,
    прочитанная раньше списка, гарантированно находит свой объект в списке.
    """
    порядок = _Порядок()
    участок = Area(name="action-plans", prefix=ПРЕФИКС, sql="select")

    def строки(area: Area) -> list[StoredRow]:
        порядок.шаги.append(f"rows:{area.name}")
        return [_строка("f1", "action-plans/r1/f1")]

    def объекты(prefix: str) -> list[StoredObject]:
        порядок.шаги.append(f"list:{prefix}")
        return [_объект("action-plans/r1/f1")]

    итоги = reconcile((участок,), read_rows=строки, list_objects=объекты, now=СЕЙЧАС, grace=ПОРОГ)

    assert порядок.шаги == ["rows:action-plans", f"list:{ПРЕФИКС}"]
    assert [и.clean for и in итоги] == [True]


def test_reconcile_lets_storage_failure_through() -> None:
    """Хранилище не ответило — это отказ сверки, а не «объектов нет» и не «сходится»."""

    def объекты(prefix: str) -> list[StoredObject]:
        raise StorageError("не ответило")

    with pytest.raises(StorageError):
        reconcile(
            AREAS,
            read_rows=lambda area: [],
            list_objects=объекты,
            now=СЕЙЧАС,
            grace=ПОРОГ,
        )
