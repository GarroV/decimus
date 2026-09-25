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


def test_разница_называет_новый_выключенный_изменённый_и_убранный() -> None:
    # Arrange
    было = (
        {"id": "A1", "question_ru": "Пол", "days": "5"},
        {"id": "A2", "question_ru": "Стены"},
        {"id": "A3", "question_ru": "Печь"},
    )
    стало = (
        {"id": "A1", "question_ru": "Пол сухой", "days": "5"},
        {"id": "A2", "question_ru": "Стены", "kind": "off"},
        {"id": "B1", "question_ru": "Касса"},
    )

    # Act
    разница = {(c.code, c.kind): c.fields for c in mv.diff_items(было, стало)}

    # Assert
    assert разница == {
        ("A1", "changed"): (("question_ru", "Пол", "Пол сухой"),),
        ("A2", "disabled"): (),
        ("B1", "added"): (),
        ("A3", "removed"): (),
    }


def test_одинаковые_версии_разницы_не_дают() -> None:
    assert mv.diff_items(ПУНКТЫ, ПУНКТЫ) == ()
    assert (
        mv.diff_zones([{"code": "hall", "share_pct": "10"}], [{"code": "hall", "share_pct": "10"}])
        == ()
    )


def test_разница_зон_видит_долю() -> None:
    [c] = mv.diff_zones(
        [{"code": "hall", "share_pct": "10"}], [{"code": "hall", "share_pct": "12"}]
    )
    assert (c.code, c.kind, c.fields) == ("hall", "zone", (("share_pct", "10", "12"),))


def test_порядок_обхода_по_номерам_а_без_номера_следом() -> None:
    # Arrange — сейчас: hall, kitchen, dough, facade.
    сейчас = ["hall", "kitchen", "dough", "facade"]

    # Act — кухню первой, зал вторым; тесто и фасад без номера.
    порядок = mv.route_order({"kitchen": "1", "hall": "2", "dough": "", "facade": "x"}, сейчас)

    # Assert
    assert порядок == ["kitchen", "hall", "dough", "facade"]


def test_равные_номера_сохраняют_прежний_порядок() -> None:
    assert mv.route_order({"a": "1", "b": "1"}, ["b", "a"]) == ["b", "a"]
