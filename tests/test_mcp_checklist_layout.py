"""T341: хранилище несёт много чек-листов — пространство, код, издания внутри.

Ядро здесь — миграция и указатели. Ошибка в них выходит наружу не отказом, а
правдоподобной цифрой: продукт продолжает считать, но по другой методике, и
узнаётся это из отчёта партнёру. Поэтому проверяется не «функция не упала», а
что именно читает движок после переноса.

Методика синтетическая и крошечная (`mcp_checklist_harness`): её достаточно,
чтобы движок по ней посчитал, а прогон не зависит от `data/` — она лежит вне
git (D002).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition, build_methodology

from src.mcp.checklist import Store, current_version, read_journal, versions
from src.mcp.checklist_layout import (
    ACTIVE,
    CURRENT_LINK,
    DEFAULT_CODE,
    DEFAULT_SPACE,
    JOURNAL_FILE,
    META_FILE,
    applied,
    known,
    read_meta,
)
from src.mcp.errors import ChecklistError
from src.report.engine_call import VERSIONS_DIR


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    return build_methodology(tmp_path / "живая-методика")


def _однослойное(корень: Path, *, издание: str | None = None) -> str:
    """Разложить хранилище ТОЙ формы, что была до множественности.

    Руками, а не прежним кодом: прежнего кода уже нет, а проверять миграцию
    надо с того, что в самом деле лежит на площадке.
    """
    корень.mkdir(parents=True, exist_ok=True)
    (корень / VERSIONS_DIR).mkdir()
    имя = издание or build_edition(корень / VERSIONS_DIR / "черновик")
    os.replace(корень / VERSIONS_DIR / "черновик", корень / VERSIONS_DIR / имя)
    os.symlink(os.path.join(VERSIONS_DIR, имя), корень / CURRENT_LINK)
    (корень / JOURNAL_FILE).write_text(
        json.dumps({"at": "2026-09-01T00:00:00+00:00", "tool": "bootstrap"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return имя


def test_однослойное_хранилище_переезжает_в_чеклист_по_умолчанию(
    tmp_path: Path, методика: Path
) -> None:
    """Издания и журнал переезжают в `<пространство>/<код>/`, а не копируются.

    Код при переезде — `bizdev` (D181): существующая методика это чек-лист
    проверки бизнес-девелопера, и код уедет в базу к каждой уже проведённой
    проверке.
    """
    корень = tmp_path / "хранилище"
    издание = _однослойное(корень)
    store = Store(root=корень, live=корень / CURRENT_LINK)

    assert current_version(store) == издание

    дом = корень / DEFAULT_SPACE / DEFAULT_CODE
    assert (дом / VERSIONS_DIR / издание).is_dir()
    assert (дом / JOURNAL_FILE).is_file()
    assert not (корень / VERSIONS_DIR).exists()
    assert not (корень / JOURNAL_FILE).exists()
    assert known(корень) == [(DEFAULT_SPACE, DEFAULT_CODE)]


def test_миграция_не_меняет_издание_которое_читает_движок(tmp_path: Path, методика: Path) -> None:
    """Главное свойство переноса: `AUDIT_DATA_DIR` смотрит туда же, куда смотрел.

    Площадка настроена на `<store>/current` и перенастраивать её не надо —
    поменялось лишь то, куда этот указатель ведёт. Разойдись это хоть на одно
    издание, проверки пошли бы по другой методике молча.
    """
    корень = tmp_path / "хранилище"
    издание = _однослойное(корень)
    читает = корень / CURRENT_LINK
    было = (читает / "checklist.csv").read_text(encoding="utf-8")

    current_version(Store(root=корень, live=читает))

    # Каталог переехал — это и есть перенос; не измениться обязано ИЗДАНИЕ,
    # которое читает движок, и его содержимое.
    assert Path(os.path.realpath(читает)).name == издание
    assert (читает / "checklist.csv").read_text(encoding="utf-8") == было
    assert (читает / "checklist.csv").is_file()
    assert applied(корень) == (DEFAULT_SPACE, DEFAULT_CODE)


def test_миграция_идемпотентна(tmp_path: Path, методика: Path) -> None:
    """Второй проход ничего не переносит и ничего не ломает: миграция стоит на
    каждом обращении к хранилищу, и «уже перенесено» — обычное её состояние."""
    корень = tmp_path / "хранилище"
    издание = _однослойное(корень)
    store = Store(root=корень, live=корень / CURRENT_LINK)

    assert current_version(store) == издание
    assert current_version(store) == издание
    assert [v.version for v in versions(store)] == [издание]


def test_миграция_обратима_перемещением_назад(tmp_path: Path, методика: Path) -> None:
    """Обратный ход — перемещение назад, а не восстановление из копии.

    Это и есть цена отката, если на площадке что-то пойдёт не так: два `mv` и
    ссылка. Проверяется тем, что после возврата хранилище читается прежним
    однослойным способом, а повторный перенос даёт то же издание.
    """
    корень = tmp_path / "хранилище"
    издание = _однослойное(корень)
    store = Store(root=корень, live=корень / CURRENT_LINK)
    current_version(store)

    дом = корень / DEFAULT_SPACE / DEFAULT_CODE
    (корень / CURRENT_LINK).unlink()
    os.replace(дом / VERSIONS_DIR, корень / VERSIONS_DIR)
    os.replace(дом / JOURNAL_FILE, корень / JOURNAL_FILE)
    shutil.rmtree(корень / DEFAULT_SPACE)
    os.symlink(os.path.join(VERSIONS_DIR, издание), корень / CURRENT_LINK)

    assert (корень / CURRENT_LINK / "checklist.csv").is_file()
    assert current_version(store) == издание


def test_наполовину_перенесённое_хранилище_это_отказ(tmp_path: Path, методика: Path) -> None:
    """Издания и в старом месте, и в новом — слить их молча нельзя: какое из
    двух читать, знает только человек, который это устроил."""
    корень = tmp_path / "хранилище"
    _однослойное(корень)
    (корень / DEFAULT_SPACE / DEFAULT_CODE / VERSIONS_DIR).mkdir(parents=True)

    with pytest.raises(ChecklistError) as отказ:
        current_version(Store(root=корень, live=корень / CURRENT_LINK))

    assert "перенесённым" in str(отказ.value)


def test_свежее_хранилище_заводится_сразу_двухуровневым(tmp_path: Path, методика: Path) -> None:
    """Хранилища не было вовсе: нулевое издание ложится в чек-лист по
    умолчанию, и он же становится применённым к проду — иначе `AUDIT_DATA_DIR`
    указывал бы в пустоту."""
    store = Store(root=tmp_path / "хранилище", live=методика)

    издание = current_version(store)

    assert (store.home / VERSIONS_DIR / издание).is_dir()
    assert applied(store.root) == (DEFAULT_SPACE, DEFAULT_CODE)
    assert os.path.realpath(store.root / CURRENT_LINK) == str(
        (store.home / VERSIONS_DIR / издание).resolve()
    )


def test_карточка_заводится_рядом_с_изданиями_а_не_внутри(tmp_path: Path, методика: Path) -> None:
    """Состояние чек-листа не входит в отпечаток методики: пометка «в работе»
    не меняет ни одного вопроса и нового издания порождать не должна."""
    store = Store(root=tmp_path / "хранилище", live=методика)
    издание = current_version(store)

    карточка = read_meta(store)

    assert карточка is not None
    assert (карточка.code, карточка.state) == (DEFAULT_CODE, ACTIVE)
    assert карточка.name_ru and карточка.name_en
    assert (store.home / META_FILE).is_file()
    assert not (store.home / VERSIONS_DIR / издание / META_FILE).exists()


def test_чеклиста_которого_нет_хранилище_не_выдумывает(tmp_path: Path, методика: Path) -> None:
    """Снимком боевой методики заводится только ПЕРВЫЙ чек-лист.

    Второй, названный неизвестным кодом, обязан получить отказ: молчаливая
    копия чужого эталона под своим кодом — это две методики, расходящиеся с
    первой же правки, и обнаружилось бы это на точке у аудитора.
    """
    Store(root=tmp_path / "хранилище", live=методика)
    основной = Store(root=tmp_path / "хранилище", live=методика)
    current_version(основной)

    with pytest.raises(ChecklistError) as отказ:
        current_version(Store(root=tmp_path / "хранилище", live=методика, code="rnd"))

    сказано = str(отказ.value)
    assert "rnd" in сказано and "create_checklist" in сказано


def test_журнал_у_каждого_чеклиста_свой(tmp_path: Path, методика: Path) -> None:
    """«Кто и что правил» читается по тому чек-листу, который смотрят, и не
    тонет в соседних."""
    основной = Store(root=tmp_path / "хранилище", live=методика)
    current_version(основной)
    соседний = Store(root=tmp_path / "хранилище", live=методика, code="rnd")
    build_edition(соседний.home / VERSIONS_DIR / "издание-rnd", name="rnd")

    assert read_journal(основной)
    assert read_journal(соседний) == []
