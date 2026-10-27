"""D665: Claude видит сохранённое письмо проверки и может сохранить доработанное.

Проверяется то, ради чего инструменты заведены: правки людей не теряются при
пересборке (`inspection_letter` отдаёт сохранённое, а не заготовку), сохранение идёт
тем же путём, что кнопка на сайте (та же очистка разметки, новая версия с автором),
и граница та же, что у сайта: чужая проверка отвечает как несуществующая, роль без
права `inspection.letter` инструмента не получает.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import accept_pushed, пространства_для_теста, точка_пространства

pytest.importorskip("psycopg")

from src.db import letters as letters_store
from src.db.push import push_inspection
from src.domain import add_finding, start_inspection
from src.mcp.errors import ToolError
from src.mcp.letter_save import save_inspection_letter
from src.mcp.rpc import LETTER_CLOSED, handle
from src.mcp.tools import inspection_letter
from src.report import letter_markup

АРЕНДАТОР_А = "GE"
АРЕНДАТОР_Б = "AM"
ЛОГИН = "web:anna"


def _проверка(chat_id: int, *, арендатор: str, точка: str = "Белград-1") -> str:
    точка_пространства(точка, tenant=арендатор)
    start_inspection(
        chat_id, unit=точка, kind="planned", report_lang="ru", tenant=арендатор, date="2026-08-15"
    )
    add_finding(chat_id, code="CLN03", level="D1", zone="hot_kitchen", text="грязь на полу")
    ident = push_inspection(chat_id)
    accept_pushed(ident)
    return ident


@pytest.fixture
def _пространства(request: pytest.FixtureRequest) -> None:
    пространства_для_теста(request, АРЕНДАТОР_А, АРЕНДАТОР_Б)


def _сохранить(ident: str, text: str, **kw: Any) -> dict[str, object]:
    return save_inspection_letter(tenant=АРЕНДАТОР_А, actor=ЛОГИН, id=ident, text=text, **kw)


@requires_db
@pytest.mark.usefixtures("_пространства")
class TestСДобавленнойБазой:
    def test_сохранённое_письмо_отдаётся_вместо_заготовки(
        self, domain_env: Path, db_env: str
    ) -> None:
        ident = _проверка(930_001, арендатор=АРЕНДАТОР_А)
        _сохранить(ident, "Правленое людьми письмо\nвторая строка")

        ответ = inspection_letter(tenant=АРЕНДАТОР_А, id=ident)

        assert ответ["source"] == "saved"
        assert ответ["letter"] == "Правленое людьми письмо\nвторая строка"
        assert ответ["lang"] == "ru"
        assert ответ["version"] == 1
        assert ответ["saved_by"] == "anna"
        assert ответ["saved_at"]

    def test_fresh_даёт_заготовку_и_сохранённое_не_трогает(
        self, domain_env: Path, db_env: str
    ) -> None:
        ident = _проверка(930_002, арендатор=АРЕНДАТОР_А)
        _сохранить(ident, "Правленое людьми письмо")

        свежее = inspection_letter(tenant=АРЕНДАТОР_А, id=ident, fresh=True)
        снова = inspection_letter(tenant=АРЕНДАТОР_А, id=ident)

        assert свежее["source"] == "template"
        assert свежее["score_verified"] is True
        assert "грязь на полу" in str(свежее["letter"])
        assert снова["source"] == "saved", "fresh=true ничего не пишет"
        assert снова["letter"] == "Правленое людьми письмо"

    def test_без_сохранённого_письма_это_заготовка(self, domain_env: Path, db_env: str) -> None:
        ident = _проверка(930_003, арендатор=АРЕНДАТОР_А)

        ответ = inspection_letter(tenant=АРЕНДАТОР_А, id=ident)

        assert ответ["source"] == "template"
        assert ответ["score_verified"] is True

    def test_язык_отбирает_версию_а_без_языка_берётся_последняя(
        self, domain_env: Path, db_env: str
    ) -> None:
        ident = _проверка(930_004, арендатор=АРЕНДАТОР_А)
        _сохранить(ident, "русское письмо", lang="ru")
        _сохранить(ident, "english letter", lang="en")

        без_языка = inspection_letter(tenant=АРЕНДАТОР_А, id=ident)
        русское = inspection_letter(tenant=АРЕНДАТОР_А, id=ident, lang="ru")

        assert без_языка["letter"] == "english letter"
        assert без_языка["lang"] == "en"
        assert русское["letter"] == "русское письмо"

    def test_сохранение_кладёт_новую_версию_с_автором(self, domain_env: Path, db_env: str) -> None:
        ident = _проверка(930_005, арендатор=АРЕНДАТОР_А)

        первая = _сохранить(ident, "первая редакция")
        вторая = _сохранить(ident, "вторая редакция")

        assert первая["version"] == 1
        assert вторая["version"] == 2
        assert вторая["saved_by"] == "anna"
        последнее = letters_store.latest_letter(ident)
        assert последнее is not None
        assert последнее.body == "вторая редакция"
        assert последнее.saved_by == "anna"
        assert letters_store.count_letters(ident) == 2, "прежняя версия осталась в истории"
        assert inspection_letter(tenant=АРЕНДАТОР_А, id=ident)["version"] == 2

    def test_очистка_разметки_та_же_что_на_сайте(self, domain_env: Path, db_env: str) -> None:
        ident = _проверка(930_006, арендатор=АРЕНДАТОР_А)
        грязное = 'Привет <b onclick="x()">жирный</b> <script>alert(1)</script> a & b <u>под</u>'

        _сохранить(ident, грязное)
        записано = letters_store.latest_letter(ident)

        assert записано is not None
        assert записано.body == letter_markup.sanitize(грязное)
        assert "<script" not in записано.body and "onclick" not in записано.body
        assert "<b>жирный</b>" in записано.body

    def test_пустой_текст_отказ_и_ничего_не_записано(self, domain_env: Path, db_env: str) -> None:
        ident = _проверка(930_007, арендатор=АРЕНДАТОР_А)

        for пустое in ("", "   \n ", "<b></b>"):
            with pytest.raises(ToolError):
                _сохранить(ident, пустое)

        assert letters_store.count_letters(ident) == 0

    def test_чужая_проверка_отказ_как_у_несуществующей(self, domain_env: Path, db_env: str) -> None:
        чужая = _проверка(930_008, арендатор=АРЕНДАТОР_Б, точка="Ниш-9")

        with pytest.raises(ToolError) as чужая_отказ:
            _сохранить(чужая, "письмо в чужую проверку")
        with pytest.raises(ToolError) as нет_такой:
            _сохранить("00000000-0000-0000-0000-000000000009", "письмо в никуда")

        assert str(чужая_отказ.value) == str(нет_такой.value)
        assert letters_store.count_letters(чужая) == 0

    def test_неизвестный_язык_отказ(self, domain_env: Path, db_env: str) -> None:
        ident = _проверка(930_009, арендатор=АРЕНДАТОР_А)

        with pytest.raises(ToolError):
            _сохранить(ident, "текст", lang="xx")

        assert letters_store.count_letters(ident) == 0


def _вызов(роль: str | None, actor: str, имя: str, args: dict[str, Any]) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": args},
        },
        tenant="HQ",
        role=роль,
        actor=actor,
    )
    assert ответ is not None
    return ответ


_АРГУМЕНТЫ = {"id": "00000000-0000-0000-0000-000000000001", "text": "письмо"}


@pytest.mark.parametrize("роль", ["guest", "auditor", "control", None])
def test_роль_без_права_письма_не_сохраняет_и_не_видит_инструмент(роль: str | None) -> None:
    ответ = _вызов(роль, ЛОГИН, "save_inspection_letter", _АРГУМЕНТЫ)

    assert ответ["result"]["isError"] is True  # type: ignore[index]

    список = handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tenant="HQ", role=роль, actor=ЛОГИН
    )
    assert list_names(список) & {"save_inspection_letter"} == set()


def list_names(ответ: dict[str, Any] | None) -> set[str]:
    assert ответ is not None
    return {т["name"] for т in ответ["result"]["tools"]}


def test_админ_видит_инструмент_и_без_автора_не_сохраняет() -> None:
    список = handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tenant="HQ", role="admin", actor=ЛОГИН
    )
    assert "save_inspection_letter" in list_names(список)

    ответ = _вызов("admin", "", "save_inspection_letter", _АРГУМЕНТЫ)

    assert ответ["result"]["isError"] is True
    assert LETTER_CLOSED in ответ["result"]["content"][0]["text"]
