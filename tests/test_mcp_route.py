"""T317: порядок обхода точки через агента — что задаётся, чем отказывается, что переживает.

Маршрут (`route.csv`) на цифру оценки не влияет вовсе, но решает, в каком
порядке аудитор физически идёт по пиццерии. Цена ошибки здесь выше, чем кажется:
разбор маршрута строгий (код, которого в методике нет, — отказ), а проверка
кандидата движком про этот файл не знает ВООБЩЕ — `manage.py validate` его не
читает. То есть заслон между опечаткой в коде зоны и вставшим обходом на точке
ровно один, и он здесь.

Второе, что проверяется тестами: в боевом `route.csv` живут строки-пометки
человека управляющей компании (`#`). Команда, переписывающая файл, обязана их
сохранить — молчаливая потеря чужого текста на этом проекте уже случалась.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.domain.checklist import _zones as продуктовые_зоны
from src.domain.config import Settings
from src.mcp import checklist_tools as инструменты
from src.mcp.checklist import Store, _version_dir, current_version, read_journal, versions
from src.mcp.errors import ChecklistError

АРЕНДАТОР = "укашка"

#: Маршрут с пометками человека — той же формы, что боевой: шапка, блок пометок,
#: строки зон, пометка про пункты в конце.
МАРШРУТ_С_ПОМЕТКАМИ = (
    "entity,code,order\n"
    "# Маршрут обхода точки. Порядок — данные, а не код: строку правит человек\n"
    "# управляющей компании.\n"
    "#\n"
    "zone,fridge,10\n"
    "zone,dough,20\n"
    "#\n"
    "# Порядок пунктов внутри зоны управляющая компания пока не задавала.\n"
)


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    return build_methodology(tmp_path / "живая-методика")


@pytest.fixture
def store(tmp_path: Path, методика: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=методика)


def _файл_маршрута(store: Store, version: str) -> str:
    return (_version_dir(store, version) / "route.csv").read_text(encoding="utf-8")


def _как_видит_продукт(store: Store, version: str) -> list[str]:
    """Коды зон в том порядке, в котором их выстроит ПРОДУКТ, а не этот блок.

    Тот же вызов, которым зоны читает бот на точке (`src.domain.checklist`):
    свой разборщик проверял бы согласие блока с самим собой.
    """
    каталог = _version_dir(store, version)
    настройки = Settings(data_dir=каталог, state_dir=каталог, audit_script=каталог / "audit.py")
    return [зона.code for зона in продуктовые_зоны(настройки)]


# --- правка -------------------------------------------------------------------


def test_порядок_зон_задан_и_продукт_видит_его_тем_же_порядком(store: Store) -> None:
    """Главный тест файла: порядок, названный в разговоре, — это тот порядок, в
    котором зоны придут аудитору на точку."""
    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    assert _как_видит_продукт(store, ответ["version"]) == ["dough", "fridge"]


def test_позиции_идут_с_шагом_десять(store: Store) -> None:
    """Шаг оставлен намеренно: вставить зону между двумя соседними человек
    должен уметь без перенумерации всего файла."""
    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    строки = _файл_маршрута(store, ответ["version"]).splitlines()

    assert "zone,dough,10" in строки
    assert "zone,fridge,20" in строки


def test_правка_приходит_новой_версией_и_сама_не_публикуется(store: Store) -> None:
    действующая = current_version(store)

    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    assert ответ["base_version"] == действующая
    assert ответ["version"] != действующая
    assert ответ["published"] is False
    assert current_version(store) == действующая


def test_правка_записана_в_журнал_своим_именем(store: Store) -> None:
    инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    запись = read_journal(store)[-1]

    assert запись["tool"] == "set_route"
    assert запись["outcome"] == "accepted"
    assert запись["tenant"] == АРЕНДАТОР


def test_код_уходит_в_маршрут_в_написании_методики(store: Store) -> None:
    """Маршрут сверяется со справочником кодом в код: чужое написание продукт
    отбросил бы отказом уже на точке, а не в разговоре."""
    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["FRIDGE", "Dough"], version_name="imf"
    )

    assert "zone,fridge,10" in _файл_маршрута(store, ответ["version"]).splitlines()
    assert _как_видит_продукт(store, ответ["version"]) == ["fridge", "dough"]


def test_порядок_пунктов_задаётся_тем_же_вызовом(store: Store) -> None:
    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, items=["CLN02", "CLN01"], version_name="imf"
    )

    строки = _файл_маршрута(store, ответ["version"]).splitlines()

    assert "item,CLN02,10" in строки
    assert "item,CLN01,20" in строки


# --- чужой текст и соседняя половина маршрута ---------------------------------


def test_пометки_человека_переживают_перезапись(методика: Path, store: Store) -> None:
    """Пометки — единственное, что в этом файле объясняет ПОЧЕМУ порядок такой.
    Переписать файл, потеряв их, значит стереть работу человека молча."""
    (методика / "route.csv").write_text(МАРШРУТ_С_ПОМЕТКАМИ, encoding="utf-8")

    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    стало = _файл_маршрута(store, ответ["version"])
    for пометка in [
        строка for строка in МАРШРУТ_С_ПОМЕТКАМИ.splitlines() if строка.startswith("#")
    ]:
        assert пометка in стало.splitlines(), пометка


def test_правка_зон_не_трогает_порядок_пунктов(методика: Path, store: Store) -> None:
    """Половины маршрута независимы: названы зоны — пункты остаются как были."""
    (методика / "route.csv").write_text(
        МАРШРУТ_С_ПОМЕТКАМИ + "item,CLN02,10\nitem,CLN01,20\n", encoding="utf-8"
    )

    ответ = инструменты.set_route(
        tenant=АРЕНДАТОР, store=store, zones=["dough", "fridge"], version_name="imf"
    )

    строки = _файл_маршрута(store, ответ["version"]).splitlines()

    assert "item,CLN02,10" in строки
    assert "item,CLN01,20" in строки


# --- отказы -------------------------------------------------------------------


def test_неизвестный_код_зоны_отказ_и_версии_не_появилось(store: Store) -> None:
    """Тот самый заслон, которого нет больше нигде: движок этот файл не читает,
    и код-опечатка дошёл бы до точки, где обход просто встанет."""
    было = len(versions(store))

    with pytest.raises(ChecklistError) as отказ:
        инструменты.set_route(
            tenant=АРЕНДАТОР, store=store, zones=["dough", "terrace"], version_name="imf"
        )

    assert "terrace" in str(отказ.value)
    assert "fridge" in str(отказ.value), "отказ обязан назвать зоны, которые в методике есть"
    assert len(versions(store)) == было


def test_неизвестный_код_пункта_отказ(store: Store) -> None:
    """Отказ обязан сказать, ГДЕ смотреть годные коды: «такого кода нет» без
    этого отправляет агента угадывать, а пунктов в боевой методике 136."""
    with pytest.raises(ChecklistError) as отказ:
        инструменты.set_route(
            tenant=АРЕНДАТОР, store=store, items=["CLN01", "ZZZ99"], version_name="imf"
        )

    assert "ZZZ99" in str(отказ.value)
    assert "checklist_items" in str(отказ.value)


def test_код_названный_дважды_отказ_про_вызов_а_не_про_методику(store: Store) -> None:
    """Дубль в маршруте — не порядок: одно из двух мест заведомо ошибка.

    Отказ обязан говорить о ВЫЗОВЕ. Разбор продукта такой файл тоже читать
    откажется — но уже написанный, и его отказ звучит «маршрут этой версии не
    читается», то есть отправляет чинить методику вместо того, чтобы поправить
    свой же список.
    """
    with pytest.raises(ChecklistError) as отказ:
        инструменты.set_route(
            tenant=АРЕНДАТОР, store=store, zones=["dough", "dough"], version_name="imf"
        )

    assert "dough" in str(отказ.value)
    assert "не читается" not in str(отказ.value)


def test_негодный_код_отказ_до_записи(store: Store) -> None:
    with pytest.raises(ChecklistError) as отказ:
        инструменты.set_route(tenant=АРЕНДАТОР, store=store, zones=["тесто"], version_name="imf")

    assert "код" in str(отказ.value).lower()


def test_не_названо_ни_зон_ни_пунктов_отказ(store: Store) -> None:
    """Молчаливое «готово» на вызове, который ничего не задаёт, агент перескажет
    человеку как выполненную работу."""
    with pytest.raises(ChecklistError) as отказ:
        инструменты.set_route(tenant=АРЕНДАТОР, store=store, version_name="imf")

    assert "zones" in str(отказ.value)
    assert "items" in str(отказ.value)


# --- чтение -------------------------------------------------------------------


def test_маршрут_читается_вместе_с_неназванными_зонами(методика: Path, store: Store) -> None:
    """Читается порядок ОБХОДА, а не файл: зоны, которых маршрут не называет,
    идут следом — именно так их получит аудитор."""
    (методика / "route.csv").write_text("entity,code,order\nzone,dough,10\n", encoding="utf-8")

    ответ = инструменты.route(tenant=АРЕНДАТОР, store=store)

    assert [зона["code"] for зона in ответ["zones"]] == ["dough", "fridge"]
    assert ответ["zones"][0]["order"] == 10
    assert ответ["zones"][1]["order"] is None
    assert ответ["zones"][0]["name_ru"] == "Тесто"


def test_маршрут_которого_нет_читается_пустым_а_не_отказом(store: Store) -> None:
    """Файла нет — законное состояние методики, а не сбой: порядок остаётся тем,
    в котором пункты и зоны лежат в методике."""
    ответ = инструменты.route(tenant=АРЕНДАТОР, store=store)

    assert ответ["items"] == []
    assert all(зона["order"] is None for зона in ответ["zones"])
    assert ответ["status"]


def test_чтение_называет_версию_и_не_врёт_про_чужую(store: Store) -> None:
    ответ = инструменты.route(tenant=АРЕНДАТОР, store=store)

    assert ответ["version"] == current_version(store)

    with pytest.raises(ChecklistError):
        инструменты.route(tenant=АРЕНДАТОР, store=store, version="imf-2026-09-03-000000000000")
