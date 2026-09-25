"""T320: экраны раздела «Методика» — вход, состав, правка, публикация, языки.

Разметку и тексты глазами не сторожим здесь тестами (это дело сверки с
эталоном), но у раздела «Методика» есть свойства, чья ошибка молчит, и они —
предмет этого набора:

* без входа раздел не открывается — как и весь остальной набор экранов
  (T323), но проверено здесь ещё раз именно на нём, потому что это отдельный
  реестр маршрутов, который легко забыть вписать в заслон;
* правка с экрана — это НОВАЯ версия, а не правка действующей: экран обязан
  сказать «записано», а не «опубликовано» (D049);
* публикация — отдельная кнопка, и она либо переставляет указатель, либо
  честно отказывает;
* отказ движка попадает на страницу текстом, а не пятисоткой;
* оба языка интерфейса отвечают ключами `methodology.*`, а не заглушкой.

Хранилище здесь настоящее (файлы на `tmp_path`, движок — подпроцессом),
подменена только пара дверей опознания (`web_harness.подменить_двери`) —
так же, как во всех остальных экранных наборах блока `web`. Боевая методика
уже ИЗДАНА (`build_edition`): дверь `web/methodology.py` не умеет придумывать
имя набора самостоятельно (D050) — на неизданной первая же правка отказала бы
с «нет имени набора», и это был бы отказ оснастки, а не того, что проверяется.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import auth
from src.web import methodology as method

ТЕНАНТ = "default"
АВТОР = "director"


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    return подменить_двери(monkeypatch, tenant=ТЕНАНТ)


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    """Боевая методика — уже изданная, как и в наборе двери (`test_web_methodology.py`)."""
    where = tmp_path / "живая-методика"
    build_edition(where, name="imf", day="2026-09-01")
    return where


@pytest.fixture
def хранилище_путь(tmp_path: Path) -> Path:
    return tmp_path / "хранилище"


@pytest.fixture
def настроено(monkeypatch: pytest.MonkeyPatch, хранилище_путь: Path, методика: Path) -> Path:
    """Переменные окружения хранилища указывают на настоящее хранилище на `tmp_path`."""
    monkeypatch.setenv(method.STORE_VAR, str(хранилище_путь))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    return хранилище_путь


@pytest.fixture
def клиент(
    monkeypatch: pytest.MonkeyPatch, двери: dict[str, list[Any]], настроено: Path
) -> Iterator[FlaskClient]:
    """Приложение с настоящим хранилищем методики. Никто ещё не вошёл."""
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        yield client


@pytest.fixture
def клиент_без_хранилища(
    monkeypatch: pytest.MonkeyPatch, двери: dict[str, list[Any]]
) -> Iterator[FlaskClient]:
    """То же приложение, но переменные хранилища НЕ заданы (снимаются явно —
    мало ли что уже стоит в окружении прогона)."""
    monkeypatch.delenv(method.STORE_VAR, raising=False)
    monkeypatch.delenv(method.DATA_VAR, raising=False)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        yield client


# --- вход обязателен -----------------------------------------------------------


def test_без_входа_методика_не_открывается(клиент: FlaskClient) -> None:
    ответ = клиент.get("/admin")
    assert ответ.status_code == 302
    assert auth.LOGIN_PATH in (ответ.headers.get("Location") or "")


# --- раздел показывает состав ---------------------------------------------------


def test_раздел_открывается_и_показывает_состав(клиент: FlaskClient) -> None:
    войти(клиент)

    страница = клиент.get("/admin").get_data(as_text=True)

    assert "CLN01" in страница
    assert "CLN02" in страница
    assert "fridge" in страница


# --- ненастроенное хранилище называет переменные --------------------------------


def test_ненастроенное_хранилище_называет_переменные(
    клиент_без_хранилища: FlaskClient,
) -> None:
    войти(клиент_без_хранилища)

    страница = клиент_без_хранилища.get("/admin").get_data(as_text=True)

    assert method.STORE_VAR in страница
    assert method.DATA_VAR in страница
    # Пустой таблицы здесь тоже быть не должно: она прочиталась бы как «чек-лист
    # пуст», хотя дело в ненастроенном стенде.
    assert "CLN01" not in страница


# --- правка с экрана: новая версия, не публикует --------------------------------


def test_правка_с_экрана_даёт_версию_и_не_публикует(клиент: FlaskClient) -> None:
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None
    действующая_до = method.published_version(состояние.store)

    ответ = клиент.post(
        "/admin/items/CLN01",
        data={"question_ru": "Пол чистый и сухой"},
        headers={"Origin": СВОЙ},
    )
    страница = ответ.get_data(as_text=True)

    assert ответ.status_code == 200
    свежая = method.latest_version(состояние.store)
    assert свежая in страница, "номер новой версии не показан"
    assert method.published_version(состояние.store) == действующая_до, (
        "правка с экрана опубликовала версию сама"
    )


# --- отказ движка виден на экране ------------------------------------------------


def test_отказ_движка_виден_на_экране_а_не_пятисоткой(клиент: FlaskClient) -> None:
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None
    свежая_до = method.latest_version(состояние.store)

    ответ = клиент.post(
        "/admin/items/CLN01",
        data={"levels": "D9"},
        headers={"Origin": СВОЙ},
    )
    страница = ответ.get_data(as_text=True)

    assert ответ.status_code == 200
    assert "D9" in страница, "слова отказа движка не попали на страницу"
    assert method.latest_version(состояние.store) == свежая_до, (
        "отклонённая правка всё равно записала версию"
    )


# --- публикация отдельной кнопкой ------------------------------------------------


def test_публикация_отдельной_кнопкой(
    клиент: FlaskClient, хранилище_путь: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None
    правка = method.add_item(
        состояние.store,
        tenant=ТЕНАНТ,
        author=АВТОР,
        process="Проба",
        question_ru="Проба пера",
        levels="D1",
        zones="fridge",
        days="5",
        criteria="D1: проба",
    )
    # Чтобы публикацию УВИДЕЛ сам движок, `AUDIT_DATA_DIR` обязан быть самим
    # указателем хранилища (`test_web_methodology.py`,
    # `test_публикация_на_обычный_каталог_отказывает`). Первая правка выше
    # сделана на обычном каталоге намеренно — именно так и бутстрапится
    # хранилище; указатель `current` уже готов, и здесь окружение стенда
    # переставляется на него — так же, как это делает настоящий деплой,
    # закончив разовую настройку хранилища.
    monkeypatch.setenv(method.DATA_VAR, str(хранилище_путь / "current"))

    ответ = клиент.post(
        "/admin/publish",
        data={"version": правка.version},
        headers={"Origin": СВОЙ},
    )
    страница = ответ.get_data(as_text=True)

    assert ответ.status_code == 200
    assert "не принята" not in страница, страница
    рабочее = method.load_store()
    assert рабочее.store is not None
    assert method.published_version(рабочее.store) == правка.version
    assert правка.version in страница


# --- чужое происхождение отвергается ---------------------------------------------


def test_чужое_происхождение_отвергается(клиент: FlaskClient) -> None:
    войти(клиент)

    for заголовки in ({}, {"Origin": "http://зло.example"}):
        ответ = клиент.post(
            "/admin/items/CLN01", data={"question_ru": "чужой запрос"}, headers=заголовки
        )
        assert ответ.status_code == 403, заголовки


# --- старая версия — без форм правки ---------------------------------------------


def test_старая_версия_показывается_без_форм_правки(клиент: FlaskClient) -> None:
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None
    исходная = method.published_version(состояние.store)
    method.add_item(
        состояние.store,
        tenant=ТЕНАНТ,
        author=АВТОР,
        process="Проба",
        question_ru="Проба пера",
        levels="D1",
        zones="fridge",
        days="5",
        criteria="D1: проба",
    )

    страница = клиент.get(f"/admin?version={исходная}").get_data(as_text=True)

    # Форма правки шлёт на `/admin/items?lang=...` — точного `action="/admin/items"`
    # в разметке не бывает вовсе (там всегда есть хвост языка), поэтому сторожим
    # префикс, а не буквальную строку, которая была бы верна на любой странице.
    assert 'action="/admin/items?' not in страница, "форма правки видна на старой версии"
    assert "Старая версия" in страница


# --- оба языка --------------------------------------------------------------------


def test_оба_языка_интерфейса(клиент: FlaskClient) -> None:
    войти(клиент)

    английская = клиент.get("/admin?lang=en").get_data(as_text=True)
    русская = клиент.get("/admin?lang=ru").get_data(as_text=True)

    assert "Versions" in английская
    assert "Версии" in русская


# --- экран в три колонки (D197) -------------------------------------------------


def test_пункт_открывается_панелью_по_адресу(клиент: FlaskClient) -> None:
    # Arrange
    войти(клиент)

    # Act — адрес панели можно переслать: он сам открывает пункт.
    страница = клиент.get("/admin?item=CLN01").get_data(as_text=True)

    # Assert — панель с правкой этого пункта, листание к соседу, закрытие.
    assert 'class="mx-panel__code mono">CLN01<' in страница
    assert 'action="/admin/items/CLN01?' in страница
    assert "data-mx-next" in страница
    assert "data-mx-close" in страница


def test_старый_адрес_пункта_ведёт_в_панель(клиент: FlaskClient) -> None:
    войти(клиент)
    ответ = клиент.get("/admin/items/CLN02?lang=en")
    assert ответ.status_code == 302
    assert "item=CLN02" in (ответ.headers.get("Location") or "")


def test_поиск_сужает_список(клиент: FlaskClient) -> None:
    # Arrange
    войти(клиент)

    # Act
    страница = клиент.get("/admin?q=CLN02").get_data(as_text=True)

    # Assert
    assert 'data-mx-item="CLN02"' in страница
    assert 'data-mx-item="CLN01"' not in страница


def test_правка_плашками_классов_пишет_их_через_точку_с_запятой(клиент: FlaskClient) -> None:
    # Arrange — плашки приходят несколькими значениями одного поля.
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None

    # Act
    ответ = клиент.post(
        "/admin/items/CLN01", data={"levels": ["D1", "D2"]}, headers={"Origin": СВОЙ}
    )

    # Assert — записано в формате методики, а не одним первым значением.
    assert ответ.status_code == 200
    пункт = method.load_item(состояние.store, tenant=ТЕНАНТ, code="CLN01")["item"]
    assert пункт["levels"] == "D1;D2"


def test_панель_показывает_как_часто_пункт_нарушают(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    from datetime import date

    from src.db.models import ItemUsage
    from src.web import inspections as data

    сводка = ItemUsage(
        code="CLN01",
        records=3,
        units=2,
        inspections=2,
        last_date=date(2026, 9, 23),
        by_level=(("D1", 3),),
        top_units=(("Tbilisi-1", "u-1", 2), ("Batumi-1", "u-2", 1)),
    )
    monkeypatch.setattr(data, "load_item_usage", lambda **_: сводка)
    войти(клиент)

    # Act
    страница = клиент.get("/admin?item=CLN01").get_data(as_text=True)

    # Assert
    assert "Записей: 3 · точек: 2 · проверок: 2" in страница
    assert 'href="/units/u-1' in страница


def test_без_базы_панель_говорит_что_сводки_нет(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import inspections as data

    monkeypatch.setattr(data, "load_item_usage", lambda **_: None)
    войти(клиент)
    страница = клиент.get("/admin?item=CLN01").get_data(as_text=True)
    assert "Сводка недоступна" in страница
    assert 'action="/admin/items/CLN01?' in страница, "без сводки пропала и правка"


def test_разница_перед_публикацией_видит_правку_критериев(клиент: FlaskClient) -> None:
    """Критерии лежат отдельным файлом и в состав не входят: разница без них
    назвала бы правку критериев «изменений нет»."""
    # Arrange — записать версию, где изменены ТОЛЬКО критерии.
    войти(клиент)
    клиент.post(
        "/admin/items/CLN01",
        data={"criteria": "Новый критерий: ни одной лужи."},
        headers={"Origin": СВОЙ},
    )

    # Act
    страница = клиент.get("/admin?diff=1").get_data(as_text=True)

    # Assert
    assert "mx-change--changed" in страница
    assert "<ins>Новый критерий: ни одной лужи.</ins>" in страница


# --- зоны: правятся с экрана, и только на последней версии (T348) ----------------


def test_на_старой_версии_зоны_не_правятся(клиент: FlaskClient) -> None:
    """Старая версия читается, но не правится — то же правило, что у пунктов.

    Правка старой версии либо промах, либо откат; неотличимыми их делать нельзя.
    """
    войти(клиент)
    состояние = method.load_store()
    assert состояние.store is not None
    исходная = method.published_version(состояние.store)
    method.add_zone(
        состояние.store,
        tenant=ТЕНАНТ,
        author=АВТОР,
        code="terrace",
        name_ru="Терраса",
        equal_shares=True,
    )

    страница = клиент.get(f"/admin?version={исходная}").get_data(as_text=True)

    assert 'action="/admin/zones?' not in страница
    assert 'action="/admin/zones/shares?' not in страница


def test_несошедшиеся_доли_возвращают_отказ_на_экран(клиент: FlaskClient) -> None:
    """Отказ движка обязан доехать до человека словами, а не тихим успехом."""
    войти(клиент)

    ответ = клиент.post(
        "/admin/zones/shares",
        data={"share_fridge": "10", "share_hall": "10"},
        headers={"Origin": "http://localhost"},
    )

    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    # Сторожим БЛОК отказа, а не слово «100»: сотня есть на этой странице всегда
    # (доли действующих зон), и проверка на неё была зелёной даже с выброшенным
    # отказом — проверено внесением порчи 25.09.
    assert 'class="note note--error' in страница, "отказ не доехал до экрана"


# --- развесовка в панели: доли, порядок обхода, зона (T348) -----------------------

ПОСЛАНО = {"Origin": "http://localhost"}


def _зоны_последней() -> dict[str, str]:
    состояние = method.load_store()
    assert состояние.store is not None
    версия = method.latest_version(состояние.store)
    зоны = method.zones_of_version(состояние.store, tenant=ТЕНАНТ, version=версия)
    return {z["code"]: z["share_pct"] for z in зоны}


def _обход() -> list[str]:
    состояние = method.load_store()
    assert состояние.store is not None
    return [z["code"] for z in method.load_route(состояние.store, tenant=ТЕНАНТ)["zones"]]


def test_доли_из_панели_записываются_новой_версией(клиент: FlaskClient) -> None:
    """Доли неравные (51/49): обмен равных долей не отличил бы запись от пустой правки."""
    войти(клиент)

    ответ = клиент.post(
        "/admin/zones/shares", data={"share_fridge": "51", "share_dough": "49"}, headers=ПОСЛАНО
    )

    assert 'class="note note--error' not in ответ.get_data(as_text=True)
    assert {к: float(v) for к, v in _зоны_последней().items()} == {"fridge": 51.0, "dough": 49.0}


def test_порядок_обхода_из_панели_переставляет_зоны(клиент: FlaskClient) -> None:
    войти(клиент)
    было = _обход()
    assert было == ["fridge", "dough"]

    клиент.post(
        "/admin/route",
        data={"zone": было, "order_fridge": "2", "order_dough": "1"},
        headers=ПОСЛАНО,
    )

    assert _обход() == ["dough", "fridge"]


def test_панель_зоны_открывается_по_адресу(клиент: FlaskClient) -> None:
    войти(клиент)

    страница = клиент.get("/admin?zone_card=dough").get_data(as_text=True)

    assert 'action="/admin/zones/dough/rename?' in страница
    assert 'action="/admin/zones/dough/remove?' in страница


def test_у_неизданной_методики_формы_развесовки_спрашивают_имя_набора(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Без имени набора хранилище откажет первой же правке (D050) — поле обязано быть
    в каждой форме развесовки, а не только у пунктов."""
    from mcp_checklist_harness import build_methodology

    monkeypatch.setenv(method.DATA_VAR, str(build_methodology(tmp_path / "неизданная")))
    monkeypatch.setenv(method.STORE_VAR, str(tmp_path / "хранилище-неизданной"))
    войти(клиент)

    for адрес in ("/admin", "/admin?zone_card=dough"):
        страница = клиент.get(адрес).get_data(as_text=True)
        формы = [
            ф
            for ф in страница.split("<form")[1:]
            if "/admin/zones" in ф.split(">")[0] or "/admin/scoring" in ф.split(">")[0]
        ]
        assert формы, f"{адрес}: форм развесовки нет"
        for форма in формы:
            тело = форма.split("</form>")[0]
            assert 'name="version_name"' in тело, f"{адрес}: без имени набора: {тело[:80]}"
