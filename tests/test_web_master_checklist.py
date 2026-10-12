"""D440: метка «Главный» на чек-листе — кто правит главный и кто неглавные.

Ядро (права доступа): ошибка молчит. Бизнес-девелопер, которому открыта правка
главного чек-листа, молча меняет оценку всей сети; админ, у которого метка не
снимается, не может передать главный. Поэтому проверяется настоящее хранилище
(файлы на `tmp_path`, движок — подпроцессом), а не двойники: заслон и отказ
решает дверь методики (`method.store_for`), и подменить её значило бы проверять
оснастку.

Таблица на «главный» / «неглавный» × роль: админ и главный админ правят оба;
бизнес-девелопер — только неглавный, главный видит и получает отказ словами;
гость и контроль не пишут вовсе; метку и указатель прода — только админы.
Умолчание: `hq/bizdev` главный, пока в карточке нет решения, — так метка держится
на проде без миграции.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import methodology as method

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ГЛАВНЫЙ = "bizdev"
СВОЙ_ЧЕКЛИСТ = "rnd"
ПРАВКА = {"question_ru": "Пол чистый и сухой"}
#: Отказ правки, а не плашка «только чтение» на странице: страница несёт тот же текст.
ОТКАЗ = "Правка не принята: Главный чек-лист правят только админы"


@pytest.fixture
def настроено(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    методика = tmp_path / "живая-методика"
    build_edition(методика, name="imf", day="2026-09-01")
    хранилище = tmp_path / "хранилище"
    monkeypatch.setenv(method.STORE_VAR, str(хранилище))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    return хранилище


Вход = Callable[[str], FlaskClient]


@pytest.fixture
def как(monkeypatch: pytest.MonkeyPatch, настроено: Path) -> Iterator[Вход]:
    """Вход под ролью УК: `как("developer")` — клиент с настоящим хранилищем."""

    def _войти(роль: str) -> FlaskClient:
        # Роль подменяется на границе модуля и действует на ВСЕХ клиентов сразу:
        # клиента из прошлого вызова держать нельзя — он стал бы этой ролью.
        подменить_двери(monkeypatch, tenant="HQ", role=роль)
        клиент = собрать(tenant="HQ").test_client()
        assert войти(клиент).status_code == 302
        return клиент

    yield _войти


def _версия(код: str) -> str:
    состояние = method.load_store()
    assert состояние.store is not None
    склад = method.store_for(
        состояние.store, код, tenant="HQ", space=None, write=False, lang="ru", role="admin"
    )
    return method.latest_version(склад)


def _завести(клиент: FlaskClient) -> None:
    ответ = клиент.post(
        "/admin/checklists",
        data={"code": СВОЙ_ЧЕКЛИСТ, "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers=ЗАГОЛОВКИ,
    )
    assert ответ.status_code == 200, ответ.get_data(as_text=True)[:300]


НОВЫЙ_ПУНКТ = {
    "process": "Проба",
    "question_ru": "Проба пера",
    "levels": "D1",
    "zones": "*",
    "days": "5",
    "criteria": "D1: проба",
    "version_name": "rnd-1",
}


# --- главный чек-лист ----------------------------------------------------------


@pytest.mark.parametrize(("роль", "можно"), [("superadmin", True), ("admin", True)])
def test_главный_правят_админы(как: Вход, роль: str, можно: bool) -> None:
    клиент = как(роль)
    до = _версия(ГЛАВНЫЙ)

    ответ = клиент.post(f"/admin/items/CLN01?checklist={ГЛАВНЫЙ}", data=ПРАВКА, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    assert (_версия(ГЛАВНЫЙ) != до) is можно, "правка админа не записалась"


@pytest.mark.parametrize("адрес", ["/admin/items/CLN01", f"/admin/items/CLN01?checklist={ГЛАВНЫЙ}"])
def test_девелопер_главный_не_правит_и_получает_отказ_словами(как: Вход, адрес: str) -> None:
    """Без `?checklist=` правится применённый к проду — а это главный, и отказ тот же."""
    клиент = как("developer")
    до = _версия(ГЛАВНЫЙ)

    ответ = клиент.post(адрес, data=ПРАВКА, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    assert ОТКАЗ in ответ.get_data(as_text=True)
    assert _версия(ГЛАВНЫЙ) == до, "бизнес-девелопер записал версию главного чек-листа"


ПРАВКИ_ГЛАВНОГО = [
    (
        "/admin/items",
        {
            "process": "Проба",
            "question_ru": "Проба пера",
            "levels": "D1",
            "zones": "fridge",
            "days": "5",
            "criteria": "D1: проба",
        },
    ),
    ("/admin/items/CLN01/disable", {}),
    ("/admin/zones/fridge/rename", {"name_ru": "Холодильник-2", "name_en": "Fridge 2"}),
    ("/admin/scoring", {"start_pct": "100", "d1": "0.7"}),
]


@pytest.mark.parametrize("правка", ПРАВКИ_ГЛАВНОГО)
def test_админ_те_же_правки_главного_принимаются(
    как: Вход, правка: tuple[str, dict[str, str]]
) -> None:
    """Контроль к тесту ниже: без него «отказ» мог быть отказом негодной формы."""
    до = _версия(ГЛАВНЫЙ)
    путь, форма = правка

    ответ = как("admin").post(f"{путь}?checklist={ГЛАВНЫЙ}", data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    assert _версия(ГЛАВНЫЙ) != до, ответ.get_data(as_text=True)[-600:]


@pytest.mark.parametrize("правка", ПРАВКИ_ГЛАВНОГО)
def test_девелопер_не_пишет_в_главный_ни_одним_маршрутом(
    как: Вход, правка: tuple[str, dict[str, str]]
) -> None:
    до = _версия(ГЛАВНЫЙ)
    путь, форма = правка

    ответ = как("developer").post(f"{путь}?checklist={ГЛАВНЫЙ}", data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    assert _версия(ГЛАВНЫЙ) == до
    assert ОТКАЗ in ответ.get_data(as_text=True)


def test_девелопер_главный_видит_без_кнопок_правки(как: Вход) -> None:
    клиент = как("developer")

    страница = клиент.get(f"/admin?checklist={ГЛАВНЫЙ}").get_data(as_text=True)

    assert "Главный" in страница
    assert "Главный чек-лист: только чтение" in страница
    assert 'action="/admin/items?' not in страница
    assert "/master" not in страница, "метка «Главный» показана не админу"


def test_админу_видна_метка_и_кнопка_снять(как: Вход) -> None:
    клиент = как("admin")

    страница = клиент.get(f"/admin?checklist={ГЛАВНЫЙ}").get_data(as_text=True)

    assert "Главный" in страница
    assert f"/admin/checklists/{ГЛАВНЫЙ}/master" in страница
    assert "Снять метку" in страница


# --- неглавный чек-лист --------------------------------------------------------


def test_девелопер_заводит_чек_лист_и_правит_его(как: Вход) -> None:
    клиент = как("developer")
    _завести(клиент)
    до = _версия(СВОЙ_ЧЕКЛИСТ)

    ответ = клиент.post(
        f"/admin/items?checklist={СВОЙ_ЧЕКЛИСТ}", data=НОВЫЙ_ПУНКТ, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert ОТКАЗ not in ответ.get_data(as_text=True)
    assert _версия(СВОЙ_ЧЕКЛИСТ) != до, "правка неглавного чек-листа не записалась"


def test_админ_отметил_чек_лист_главным_девелопер_больше_не_правит(как: Вход) -> None:
    _завести(как("developer"))
    ответ = как("admin").post(
        f"/admin/checklists/{СВОЙ_ЧЕКЛИСТ}/master", data={"on": "1"}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 302
    до = _версия(СВОЙ_ЧЕКЛИСТ)

    отказ = как("developer").post(
        f"/admin/items?checklist={СВОЙ_ЧЕКЛИСТ}", data=НОВЫЙ_ПУНКТ, headers=ЗАГОЛОВКИ
    )

    assert ОТКАЗ in отказ.get_data(as_text=True)
    assert _версия(СВОЙ_ЧЕКЛИСТ) == до


def test_админ_снял_метку_с_первого_девелопер_правит_его(как: Вход) -> None:
    как("admin").post(f"/admin/checklists/{ГЛАВНЫЙ}/master", data={"on": "0"}, headers=ЗАГОЛОВКИ)
    до = _версия(ГЛАВНЫЙ)

    как("developer").post(f"/admin/items/CLN01?checklist={ГЛАВНЫЙ}", data=ПРАВКА, headers=ЗАГОЛОВКИ)

    assert _версия(ГЛАВНЫЙ) != до


# --- метка и указатель прода — только админы -----------------------------------


def test_девелопер_метку_не_ставит_и_не_снимает(как: Вход) -> None:
    клиент = как("developer")
    ответ = клиент.post(f"/admin/checklists/{ГЛАВНЫЙ}/master", data={"on": "0"}, headers=ЗАГОЛОВКИ)

    assert "ставят и снимают только админы" in ответ.get_data(as_text=True)
    страница = как("admin").get(f"/admin?checklist={ГЛАВНЫЙ}").get_data(as_text=True)
    assert "Снять метку" in страница, "метка главного снята бизнес-девелопером"


def test_девелопер_свой_чек_лист_к_проду_применяет(как: Вход) -> None:
    клиент = как("developer")
    _завести(клиент)

    ответ = клиент.post(f"/admin/checklists/{СВОЙ_ЧЕКЛИСТ}/apply", data={}, headers=ЗАГОЛОВКИ)

    # Применить пустой чек-лист дверь не даст — это другой отказ, не отказ главного.
    assert "Главный чек-лист правят только админы" not in ответ.get_data(as_text=True)


def test_девелопер_главный_к_проду_не_применяет(как: Вход) -> None:
    ответ = как("developer").post(f"/admin/checklists/{ГЛАВНЫЙ}/apply", data={}, headers=ЗАГОЛОВКИ)

    assert "Главный чек-лист правят только админы" in ответ.get_data(as_text=True)


@pytest.mark.parametrize("роль", ["guest", "control"])
@pytest.mark.parametrize(
    "путь",
    [
        f"/admin/items/CLN01?checklist={ГЛАВНЫЙ}",
        "/admin/checklists",
        f"/admin/checklists/{ГЛАВНЫЙ}/master",
    ],
)
def test_гость_и_контроль_в_методику_не_пишут(как: Вход, роль: str, путь: str) -> None:
    клиент = как(роль)
    до = _версия(ГЛАВНЫЙ)

    ответ = клиент.post(путь, data={"on": "0", **ПРАВКА}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403
    assert _версия(ГЛАВНЫЙ) == до


# --- умолчание хранилища: метка держится на проде без миграции -----------------


def test_без_решения_в_карточке_главный_только_первый(настроено: Path) -> None:
    from src.domain.checklist_store import Meta, master_of

    безрешения = Meta(code="x", name_ru="x", name_en="x", state="active")

    assert master_of(None, "hq", "bizdev") is True
    assert master_of(безрешения, "hq", "bizdev") is True
    assert master_of(безрешения, "hq", "rnd") is False
    assert master_of(Meta("x", "x", "x", "active", master=False), "hq", "bizdev") is False
    assert master_of(Meta("x", "x", "x", "active", master=True), "hq", "rnd") is True


# --- индикатор неопубликованных правок -----------------------------------------


def test_после_правки_есть_индикатор_и_нет_жёлтой_плашки(как: Вход) -> None:
    клиент = как("admin")
    клиент.post("/admin/items/CLN01", data=ПРАВКА, headers=ЗАГОЛОВКИ)

    страница = клиент.get("/admin").get_data(as_text=True)

    assert "Есть неопубликованные правки" in страница
    assert "Записаны правки, которые ещё не действуют" not in страница


def test_без_правок_индикатора_нет(как: Вход) -> None:
    страница = как("admin").get("/admin").get_data(as_text=True)

    assert "Есть неопубликованные правки" not in страница
