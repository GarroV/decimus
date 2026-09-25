"""D197: отбор, группировка и соседи пункта на экране чек-листа — без базы и хранилища."""

from __future__ import annotations

from src.web import methodology_view as mv

ПУНКТЫ = (
    {
        "id": "CLN01",
        "process_ru": "Чистота",
        "question_ru": "Пол сухой",
        "levels": "D1;D2",
        "zones": "kitchen",
    },
    {"id": "CLN02", "process_ru": "Чистота", "question_ru": "Стены", "levels": "D1", "zones": "*"},
    {
        "id": "TEH01",
        "process_ru": "Техника",
        "question_ru": "Печь",
        "levels": "D3",
        "zones": "hall,kitchen",
    },
    {
        "id": "OLD01",
        "process_ru": "Техника",
        "question_ru": "Касса",
        "levels": "D1",
        "zones": "hall",
        "kind": "off",
    },
)


def коды(items: tuple[mv.Item, ...]) -> list[str]:
    return [i["id"] for i in items]


def test_выключенные_скрыты_пока_не_попросили() -> None:
    assert "OLD01" not in коды(mv.select(ПУНКТЫ, mv.ItemFilter()))
    assert "OLD01" in коды(mv.select(ПУНКТЫ, mv.ItemFilter(off=True)))


def test_отбор_по_зоне_оставляет_и_пункты_всех_зон() -> None:
    # Пункт «все зоны» проверяется и в зале: спрятать его — показать зону беднее.
    assert коды(mv.select(ПУНКТЫ, mv.ItemFilter(zone="hall"))) == ["CLN02", "TEH01"]


def test_отбор_по_классу_и_поиск() -> None:
    assert коды(mv.select(ПУНКТЫ, mv.ItemFilter(level="D2"))) == ["CLN01"]
    assert коды(mv.select(ПУНКТЫ, mv.ItemFilter(q="печь"))) == ["TEH01"]


def test_пункт_нескольких_зон_стоит_в_каждой_группе() -> None:
    группы = {g.key: коды(g.items) for g in mv.group(mv.select(ПУНКТЫ, mv.ItemFilter()), "zone")}
    assert группы == {"kitchen": ["CLN01", "TEH01"], "*": ["CLN02"], "hall": ["TEH01"]}


def test_соседи_в_порядке_видимого_списка() -> None:
    видимые = mv.select(ПУНКТЫ, mv.ItemFilter())
    assert mv.neighbours(видимые, "CLN02") == ("CLN01", "TEH01")
    assert mv.neighbours(видимые, "CLN01") == (None, "CLN02")
    assert mv.neighbours(видимые, "OLD01") == (None, None)


def test_незнакомая_группировка_это_умолчание() -> None:
    assert mv.parse_filter({"group": "evil"}).group == "process"
