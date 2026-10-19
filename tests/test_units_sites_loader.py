"""Загрузка точек с сайтов стран читает JSON-данные страницы, а не вёрстку (D538)."""

from __future__ import annotations

import pytest

from tools.units import СайтОтказал, разобрать_точки

КОД = "11ef86db87a715db6d73bb371cda19b0"
СТРАНИЦА = (
    '{"localities":[{"id":"00000001-0000-0000-0000-000000000000","name":"Bucharest"}],'
    f'"pizzerias":[{{"id":"{КОД}","localityId":"abc","name":"Bucharest-12",'
    '"alias":"Bulevardul 1 Decembrie 1918, 36","translitAlias":"x"},'
    '{"id":"000d3a2bf1aba94e11e8706186278715","localityId":"abc","name":"Bucharest-3",'
    '"alias":"' + "юридический текст " * 10 + '","translitAlias":"y"},'
    f'{{"id":"{КОД}","localityId":"abc","name":"Bucharest-12","alias":"дубль"}}]}}'
)


def test_точки_читаются_по_коду_dodo_и_без_повторов() -> None:
    точки = разобрать_точки(СТРАНИЦА, страна="RO", город="bucuresti")

    assert [(т.dodo_id, т.name) for т in точки] == [
        (КОД, "Bucharest-12"),
        ("000d3a2bf1aba94e11e8706186278715", "Bucharest-3"),
    ]
    assert точки[0].alias == "Bulevardul 1 Decembrie 1918, 36"
    assert точки[1].alias == "", "юридический текст не станет синонимом"


def test_страница_без_данных_и_без_пиццерий_громкий_отказ() -> None:
    # 403 и страницы без JSON не должны выглядеть городом без пиццерий.
    with pytest.raises(СайтОтказал):
        разобрать_точки("<html>403 Forbidden</html>", страна="KG", город="bishkek")


def test_город_с_данными_но_без_пиццерий_не_отказ() -> None:
    assert разобрать_точки('{"pizzerias":[],"localityId":"x"}', страна="RO", город="x") == []
