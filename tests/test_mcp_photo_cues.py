"""T144: карта слов правится через агента, версиями (issue #115).

У чек-листа есть и инструмент правки, и версии; у карты слов
(`data/photo-cues.md`) не было ни того, ни другого — управляющей компании
править её было нечем, а откат делался копией файла вне git.

Карта решает, что записывается БЕЗ подтверждения аудитора (быстрый путь,
T113), то есть её правка меняет то, что уезжает партнёру. Поэтому правится она
ровно так же, как чек-лист: снимок версии → правка копии → проверка → новая
версия рядом, публикация отдельным действием. С 04.09.2026 карта входит в
отпечаток версии, поэтому механизм версий её уже видит.

Проверяется здесь не «файл записался», а наблюдаемый результат: правку видит
ТОТ ЖЕ разборщик, что работает в продукте (`src.recognize.cues.load_cues`).
Своя проверка формата означала бы, что тест согласен сам с собой.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp import photo_cues
from src.mcp.checklist import CUES_FILE, VERSION_FILE, Store, _version_dir, current_version
from src.mcp.errors import ChecklistError
from src.recognize.config import NO_CHAT
from src.recognize.cues import load_cues

АРЕНДАТОР = "укашка"
РАЗДЕЛ = "Чистота"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "живая"))


@pytest.fixture
def изданный(tmp_path: Path) -> Store:
    """Хранилище над методикой, изданной СЕГОДНЯ.

    Дата издания входит в идентификатор версии, поэтому «завели строку и тут
    же убрали» упирается в уже занятое имя версии ровно тогда, когда обе
    правки сделаны в один день, — то есть в тот самый день, когда управляющая
    компания правит карту. Общая оснастка `store` этого не показывает: её
    методику никто не издавал, и нулевая версия там `local-…`.
    """
    живая = build_methodology(tmp_path / "живая-изданная")
    (живая / VERSION_FILE).write_text(f"imf {date.today().isoformat()}\n", encoding="utf-8")
    return Store(root=tmp_path / "хранилище-изданное", live=живая)


def _карта(store: Store, version: str) -> tuple:
    """Карта версии глазами продукта, а не глазами теста."""
    # `NO_CHAT`: карта читается по названному каталогу версии хранилища, живой
    # проверки за ней нет (T226).
    return load_cues(_version_dir(store, version) / CUES_FILE, chat_id=NO_CHAT)


def _фразы(store: Store, version: str) -> list[str]:
    return [cue.phrase for cue in _карта(store, version)]


def _md5(каталог: Path) -> dict[str, str]:
    return {
        str(f.relative_to(каталог)): hashlib.md5(f.read_bytes()).hexdigest()  # noqa: S324
        for f in sorted(каталог.rglob("*"))
        if f.is_file()
    }


# --- чтение -------------------------------------------------------------------


def test_карта_читается_разделами_и_строками(store: Store) -> None:
    ответ = photo_cues.read(store)

    разделы = {раздел["section"]: раздел for раздел in ответ["sections"]}
    assert РАЗДЕЛ in разделы
    фразы = [строка["phrase"] for строка in разделы[РАЗДЕЛ]["cues"]]
    assert "Стена в подтёках" in фразы


def test_пороги_классов_подсказками_не_считаются(store: Store) -> None:
    """В разделе порогов коды стоят в ПЕРВОЙ ячейке, и разборщик продукта
    пропускает его целиком. Показать его как подсказки значило бы предложить
    управляющей компании править то, что картой не является."""
    ответ = photo_cues.read(store)
    названия = [раздел["section"] for раздел in ответ["sections"]]
    assert not any("Пороги" in имя for имя in названия)


# --- добавление ---------------------------------------------------------------


def test_добавленную_строку_видит_разборщик_продукта(store: Store) -> None:
    было = current_version(store)

    итог = photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Нагар на печи, копоть",
        codes=["CLN02"],
        version_name="imf",
    )

    assert итог.accepted is True, итог.refusal
    assert итог.version is not None and итог.version != было
    строки = {cue.phrase: cue.codes for cue in _карта(store, итог.version)}
    assert строки["Нагар на печи, копоть"] == ("CLN02",)


def test_правка_карты_меняет_идентификатор_версии(store: Store) -> None:
    """Свежее и важное: карта вошла в отпечаток версии — механизм версий её
    уже видит. Если бы не видел, правка карты давала бы ту же версию, и в
    хранилище лежали бы два разных набора под одним именем."""
    было = current_version(store)
    итог = photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Лёд на стенках морозильника",
        codes=["CLN01"],
        version_name="imf",
    )
    assert итог.version != было


def test_действующая_версия_после_правки_не_меняется(store: Store) -> None:
    """Публикация — отдельное действие (D049): правка кладёт версию рядом."""
    было = current_version(store)
    photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Пыль на полке",
        codes=["CLN01"],
        version_name="imf",
    )
    assert current_version(store) == было


def test_снимок_прежней_версии_не_меняется_ни_одним_байтом(store: Store) -> None:
    было = current_version(store)
    до = _md5(_version_dir(store, было))
    photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Скол плитки",
        codes=["CLN02"],
        version_name="imf",
    )
    assert _md5(_version_dir(store, было)) == до


def test_боевая_методика_не_открывается_на_запись(store: Store) -> None:
    до = _md5(store.live)
    photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Ржавчина на кромке",
        codes=["CLN01"],
        version_name="imf",
    )
    assert _md5(store.live) == до


def test_код_которого_нет_в_методике_отказ(store: Store) -> None:
    """Подсказка на несуществующий пункт вывела бы модели код, которого в
    чек-листе нет, — и быстрый путь записал бы его без подтверждения."""
    with pytest.raises(ChecklistError, match="ZZZ99"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Что-то не то",
            codes=["ZZZ99"],
            version_name="imf",
        )


def test_неизвестный_раздел_отказ_а_не_новый_раздел(store: Store) -> None:
    """Опечатка в названии раздела завела бы раздел-двойник, и половина карты
    молча разъехалась бы по двум местам."""
    with pytest.raises(ChecklistError, match="Чистата"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section="Чистата",
            phrase="Пятно",
            codes=["CLN01"],
            version_name="imf",
        )


def test_такая_фраза_уже_есть_отказ(store: Store) -> None:
    """Две строки с одной фразой — это правка, сделанная мимо цели: работать
    будет первая, а править человек будет вторую."""
    with pytest.raises(ChecklistError, match="Стена в подтёках"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Стена в подтёках",
            codes=["CLN01"],
            version_name="imf",
        )


def test_число_колонок_проверяется(store: Store) -> None:
    """Таблица раздела двухколоночная; строка на три колонки разъехалась бы,
    и разборщик прочитал бы её иначе, чем задумывал человек."""
    with pytest.raises(ChecklistError, match="колон"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Две колонки",
            codes=["CLN01", "CLN02"],
            version_name="imf",
        )


# --- правка -------------------------------------------------------------------


def test_правка_меняет_коды_строки(store: Store) -> None:
    итог = photo_cues.edit(
        store, tenant=АРЕНДАТОР, phrase="Стена в подтёках", codes=["CLN01"], version_name="imf"
    )

    assert итог.accepted is True, итог.refusal
    assert итог.version is not None
    строки = {cue.phrase: cue.codes for cue in _карта(store, итог.version)}
    assert строки["Стена в подтёках"] == ("CLN01",)


def test_правка_меняет_саму_фразу(store: Store) -> None:
    итог = photo_cues.edit(
        store,
        tenant=АРЕНДАТОР,
        phrase="Стена в подтёках",
        new_phrase="Стена в подтёках и разводах",
        version_name="imf",
    )
    assert итог.version is not None
    фразы = _фразы(store, итог.version)
    assert "Стена в подтёках и разводах" in фразы
    assert "Стена в подтёках" not in фразы


def test_правка_несуществующей_строки_отказ_а_не_молчаливая_вставка(store: Store) -> None:
    with pytest.raises(ChecklistError, match="Стена в потёках"):
        photo_cues.edit(
            store, tenant=АРЕНДАТОР, phrase="Стена в потёках", codes=["CLN01"], version_name="imf"
        )


def test_правка_без_единого_изменения_отказ(store: Store) -> None:
    with pytest.raises(ChecklistError):
        photo_cues.edit(
            store, tenant=АРЕНДАТОР, phrase="Стена в подтёках", codes=["CLN02"], version_name="imf"
        )


# --- снятие -------------------------------------------------------------------


def test_снятая_строка_исчезает_из_карты_продукта(store: Store) -> None:
    итог = photo_cues.remove(store, tenant=АРЕНДАТОР, phrase="Стена в подтёках", version_name="imf")

    assert итог.accepted is True, итог.refusal
    assert итог.version is not None
    assert "Стена в подтёках" not in _фразы(store, итог.version)
    assert "Пол в разводах, лужа на полу" in _фразы(store, итог.version)


def test_снятие_несуществующей_строки_отказ(store: Store) -> None:
    with pytest.raises(ChecklistError, match="Потолок"):
        photo_cues.remove(store, tenant=АРЕНДАТОР, phrase="Потолок", version_name="imf")


# --- журнал -------------------------------------------------------------------


def test_правка_карты_попадает_в_журнал_хранилища(store: Store) -> None:
    from src.mcp.checklist import read_journal

    photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Мусор у порога",
        codes=["CLN01"],
        version_name="imf",
    )
    события = read_journal(store)
    assert события, "правка карты обязана быть видна в журнале, как и правка чек-листа"
    assert события[-1]["tool"] == "add_photo_cue"
    assert события[-1]["tenant"] == АРЕНДАТОР


def test_правка_записанная_не_так_возвращается_отказом_а_не_успехом(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Формат карты свободный, и строка, записанная чуть не так, тихо
    перестаёт быть строкой: файл изменился, отпечаток изменился, версия легла в
    хранилище — а продукт новой подсказки не видит. Поэтому наблюдаемый
    результат сверяется разборщиком продукта, а не доверием к своей записи."""
    monkeypatch.setattr(photo_cues, "_line", lambda cells: " ".join(cells))

    with pytest.raises(ChecklistError, match=r"не так, как задумано|осталась"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Разбитое стекло",
            codes=["CLN01"],
            version_name="imf",
        )


# --- отказы разбора аргументов ------------------------------------------------


@pytest.mark.parametrize(
    ("фраза", "почему"),
    [
        ("", "пустая фраза срабатывала бы на любой комментарий или ни на одном"),
        ("Пол | лужа", "лишняя черта разъезжает строку на колонки"),
        ("Пол CLN01 грязный", "код в первой ячейке — это раздел порогов, а не подсказка"),
    ],
)
def test_негодная_фраза_отказ(store: Store, фраза: str, почему: str) -> None:
    with pytest.raises(ChecklistError):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase=фраза,
            codes=["CLN01"],
            version_name="imf",
        )
    assert почему


def test_подсказка_без_кодов_отказ(store: Store) -> None:
    """Строка без кодов — это заголовок таблицы: разборщик продукта прочитает
    её именно так, и подсказкой она не станет."""
    with pytest.raises(ChecklistError, match="ни одного кода"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Пустая строка",
            codes=[],
            version_name="imf",
        )


def test_колонка_без_кода_отказ(store: Store) -> None:
    with pytest.raises(ChecklistError, match="нет ни одного кода"):
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=РАЗДЕЛ,
            phrase="Колонка словами",
            codes=["грязный пол"],
            version_name="imf",
        )


def test_правка_без_названного_изменения_отказ(store: Store) -> None:
    with pytest.raises(ChecklistError, match="что менять"):
        photo_cues.edit(store, tenant=АРЕНДАТОР, phrase="Стена в подтёках", version_name="imf")


def test_новая_фраза_занята_другой_строкой_отказ(store: Store) -> None:
    with pytest.raises(ChecklistError, match="уже есть"):
        photo_cues.edit(
            store,
            tenant=АРЕНДАТОР,
            phrase="Стена в подтёках",
            new_phrase="Пол в разводах, лужа на полу",
            version_name="imf",
        )


def test_версии_без_карты_слов_отказ_а_не_молчание(store: Store, tmp_path: Path) -> None:
    """Карта — необязательный файл методики. Версия без неё законна, но
    править в ней нечего, и сказать об этом надо словами."""
    (_version_dir(store, current_version(store)) / CUES_FILE).unlink()
    with pytest.raises(ChecklistError, match=CUES_FILE):
        photo_cues.read(store)


def test_снятие_не_подействовавшее_возвращается_отказом(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обратная половина сверки: строку сняли, а продукт её всё ещё видит.
    Так выглядит карта с задвоенной строкой — снялась одна, работает вторая, и
    без сверки разборщиком продукта правка вернулась бы успехом."""
    настоящий = photo_cues._text

    def _с_дублем(каталог: Path) -> str:
        текст = настоящий(каталог)
        return текст + "| Стена в подтёках | CLN02 |\n"

    monkeypatch.setattr(photo_cues, "_text", _с_дублем)

    with pytest.raises(ChecklistError, match="осталась в карте"):
        photo_cues.remove(store, tenant=АРЕНДАТОР, phrase="Стена в подтёках", version_name="imf")


# --- откат правки не выдаётся за повтор (T218) --------------------------------


def test_снятие_только_что_заведённой_строки_повтором_не_называется(изданный: Store) -> None:
    """T218 (#166): строку карты завели и тут же попросили убрать.

    Снятие возвращает методику к прежнему отпечатку, и хранилище упирается в
    имя версии, которая у него уже есть. Прежний отказ говорил «ровно эта
    правка от этого же набора и этой же датой уже сделана» — и это неверно
    дважды: правка НЕ сделана (строка на месте), а совпавшая версия получилась
    не ею. Агент управляющей компании прочитал бы отказ как «убрано, повторять
    нечего», и строка осталась бы в карте, по которой быстрый путь пишет в
    отчёт партнёру без подтверждения аудитора.
    """
    прежняя = current_version(изданный)
    заведено = photo_cues.add(
        изданный,
        tenant=АРЕНДАТОР,
        section=РАЗДЕЛ,
        phrase="Мусор у входа",
        codes=["CLN02"],
    )
    assert "Мусор у входа" in _фразы(изданный, заведено.version)

    with pytest.raises(ChecklistError) as отказ:
        photo_cues.remove(изданный, tenant=АРЕНДАТОР, phrase="Мусор у входа")

    текст = str(отказ.value)
    assert "уже сделан" not in текст, f"снятие названо повтором правки: {текст!r}"
    assert прежняя in текст, "не названа версия, состоянием которой это стало"
    assert "publish_checklist_version" in текст, "не сказано, чем откатываются"
    assert "Мусор у входа" in _фразы(изданный, заведено.version), (
        "строка обязана остаться на месте: отказ описывает то, чего не случилось"
    )


# --- колонки таблицы: зона, колонки УК, прочерк (T289) ------------------------
#
# Колонок в таблице карты больше, чем колонок с кодами, и так было всегда:
# управляющая компания держит рядом свои («Откуда» — кем строка заведена), а с
# T262 к ним прибавилась колонка «Зона», которую продукт читает ПО ЗАГОЛОВКУ.
# Правка же считала колонки ЧИСЛОМ (`len(заголовок) - 1`) и требовала кода в
# каждой — то есть отказывала на любой строке боевой карты. Ниже — свойства,
# которыми это держится теперь.

ОБОРУДОВАНИЕ = "Оборудование"


def _строка(store: Store, version: str, phrase: str):
    (нужная,) = [cue for cue in _карта(store, version) if cue.phrase == phrase]
    return нужная


def test_зона_строки_правкой_не_называется_и_остаётся_прежней(store: Store) -> None:
    """Колонка «Зона» кодов не несёт и в вызове не называется вовсе: её ставит
    управляющая компания в карте, а правка обязана вернуть её на место — иначе
    правка кодов молча снимала бы зону объекта."""
    итог = photo_cues.edit(
        store,
        tenant=АРЕНДАТОР,
        phrase="Печь",
        codes=["CLN02", "CLN01", "вопрос"],
        version_name="imf",
    )

    assert итог.accepted is True, итог.refusal
    строка = _строка(store, итог.version, "Печь")
    assert строка.codes == ("CLN02", "CLN01")
    assert строка.zone == "fridge", "зона объекта потеряна правкой кодов"


def test_колонка_управляющей_компании_записывается_как_есть(store: Store) -> None:
    """«Откуда» кодов не несёт ни у одной строки таблицы — это колонка УК, и
    правка принимает её словами, а не требует кода."""
    итог = photo_cues.edit(
        store, tenant=АРЕНДАТОР, phrase="Печь", codes=["CLN02", "CLN01", "УК"], version_name="imf"
    )

    assert итог.accepted is True, итог.refusal
    текст = (_version_dir(store, итог.version) / CUES_FILE).read_text(encoding="utf-8")
    assert "| Печь | CLN02 | CLN01 | fridge | УК |" in текст


def test_прочерк_в_кодовой_колонке_законен(store: Store) -> None:
    """У объекта бывает вопрос про грязь и не бывает про поломку. Продукт такую
    ячейку просто пропускает, а правка требовала кода в каждой — то есть
    запрещала записать то, что в карте уже лежит."""
    итог = photo_cues.edit(
        store,
        tenant=АРЕНДАТОР,
        phrase="Стеллаж",
        codes=["CLN02", "—", "УК"],
        version_name="imf",
    )

    assert итог.accepted is True, итог.refusal
    assert _строка(store, итог.version, "Стеллаж").codes == ("CLN02",)


def test_формулировка_вместо_кода_отказ_и_называет_колонку(store: Store) -> None:
    """Колонка, у которой коды есть у других строк таблицы, — кодовая, и
    формулировка в ней остаётся отказом: сущности связываются кодами."""
    with pytest.raises(ChecklistError, match="Грязь") as отказ:
        photo_cues.edit(
            store,
            tenant=АРЕНДАТОР,
            phrase="Печь",
            codes=["грязный пол", "CLN01", "вопрос"],
            version_name="imf",
        )

    assert "грязный пол" in str(отказ.value)


def test_ширина_строки_считается_по_заголовку_без_колонки_зоны(store: Store) -> None:
    """Названа ячейка и для зоны — отказ, и он говорит, какие колонки называть."""
    with pytest.raises(ChecklistError, match="колон") as отказ:
        photo_cues.add(
            store,
            tenant=АРЕНДАТОР,
            section=ОБОРУДОВАНИЕ,
            phrase="Тестомес",
            codes=["CLN01", "CLN02", "fridge", "УК"],
            version_name="imf",
        )

    текст = str(отказ.value)
    assert "Откуда" in текст and "Зона" in текст, f"отказ не называет колонки: {текст!r}"


def test_заведённая_строка_получает_пустую_зону_а_не_съезжает(store: Store) -> None:
    """Зоны у новой строки нет (её проставит управляющая компания), но ячейка
    под неё обязана быть: строка другой ширины разъехалась бы по колонкам."""
    итог = photo_cues.add(
        store,
        tenant=АРЕНДАТОР,
        section=ОБОРУДОВАНИЕ,
        phrase="Тестомес",
        codes=["CLN01", "CLN02", "УК"],
        version_name="imf",
    )

    assert итог.accepted is True, итог.refusal
    строка = _строка(store, итог.version, "Тестомес")
    assert строка.codes == ("CLN01", "CLN02")
    assert строка.zone == ""


def test_ответ_карты_называет_зону_отдельно_от_называемых_ячеек(store: Store) -> None:
    """Из ответа собирается вызов правки, поэтому ячейки в нём — ровно те, что
    правка принимает, а зона названа своим полем: иначе агент подставит её в
    `codes` и получит отказ по ширине."""
    ответ = photo_cues.read(store)

    раздел = {r["section"]: r for r in ответ["sections"]}[ОБОРУДОВАНИЕ]
    assert раздел["columns"] == ["Грязь", "Поломка", "Откуда"]
    печь = {c["phrase"]: c for c in раздел["cues"]}["Печь"]
    assert печь["cells"] == ["CLN01", "CLN02", "вопрос"]
    assert печь["zone"] == "fridge"
