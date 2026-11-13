"""D739: общее письмо на экране страны — вход, выбор, окно, фиксация, права.

Правило выбора и сборку проверяет `tests/test_batch_letter.py`; здесь — что экран и двери
не обходят его и не пускают чужое: сервер отказывает так же, как показывает окно, а письмо
чужой страны или чужого пространства не собирается и не записывается.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_batch_letter import _проверка, _часть
from test_web_country_partner import _партнёр, чтения  # noqa: F401 — фикстура `чтения`

from src.db import batch_letters as store
from src.db import queries
from src.db.models import InspectionDetail
from src.report import batch_letter as core
from src.web import batch_letter as web
from src.web import inspections as data

СВОЙ = {"Origin": "http://localhost"}
ТЕНАНТ = "GE"


def _п(n: int, **kw: Any) -> InspectionDetail:
    kw.setdefault("tenant_code", ТЕНАНТ)
    kw.setdefault("unit_country", "GE")
    return _проверка(n, **kw)


@pytest.fixture
def стенд(
    monkeypatch: pytest.MonkeyPatch,
    чтения: dict[str, list[str]],  # noqa: F811
) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    """Партнёр страны GE с тремя проверками; сборку слов проверок и запись подменяют границы."""
    базa = {
        1: _п(1, day=date(2026, 11, 2)),
        2: _п(2, day=date(2026, 11, 4)),
        3: _п(3, day=date(2026, 10, 1)),  # прошлый выезд
        4: _п(4, day=date(2026, 11, 3), tenant_code="чужой"),
    }
    по_id = {d.inspection.id: d for d in базa.values()}
    журнал: dict[str, list[Any]] = {"saved": []}
    monkeypatch.setattr(data, "load_card", lambda i, **_: по_id.get(i))
    monkeypatch.setattr(
        queries,
        "list_inspections",
        lambda **_: [
            d.inspection
            for d in sorted(базa.values(), key=lambda d: d.inspection.inspection_date, reverse=True)
        ],
    )
    monkeypatch.setattr(
        core,
        "piece_for",
        lambda detail, **_: core.Piece(
            detail=detail, parts=_часть(counts={"D1": 1, "D2": 0, "D3": 0}), caveats=()
        ),
    )
    monkeypatch.setattr(store, "latest_for_set", lambda *_a, **_k: None)

    def save(ids: Any, **поля: Any) -> store.SavedBatchLetter:
        журнал["saved"].append((tuple(ids), поля))
        from datetime import datetime

        return store.SavedBatchLetter(
            id="b" * 8 + "-0000-0000-0000-000000000000",
            country=поля["country"],
            body=поля["body"],
            lang=поля["lang"],
            saved_by=поля["saved_by"],
            created_at=datetime(2026, 11, 9, 12, 0),
            inspection_ids=tuple(ids),
        )

    monkeypatch.setattr(store, "save_batch_letter", save)
    monkeypatch.setattr(
        "src.web.batch_letter.letter_sources",
        lambda: __import__("src.report.letters", fromlist=["x"]).Papers(live=None, store=None),
    )
    for клиент in _партнёр(monkeypatch, "GE"):
        yield клиент, журнал


def _id(n: int) -> str:
    return f"{n:08d}-1111-1111-1111-111111111111"


def test_на_экране_страны_нет_кнопки_общего_письма(стенд: tuple[FlaskClient, Any]) -> None:
    # D766: вход убран, панель по адресу ?batch=1 жива (тесты ниже).
    клиент, _ = стенд
    страница = клиент.get("/country/GE").get_data(as_text=True)
    assert "batch=1" not in страница
    assert "Сформировать общее письмо" not in страница


def test_выбор_показывает_принятые_проверки_страны_свои_свежие_сверху(
    стенд: tuple[FlaskClient, Any],
) -> None:
    клиент, _ = стенд
    страница = клиент.get("/country/GE?batch=1").get_data(as_text=True)
    имена = re.findall(r'name="ids" value="([^"]+)"', страница)
    # Чужого пространства в выборе нет; порядок — по дате, свежие сверху.
    assert имена == [_id(2), _id(1), _id(3)]


def test_окно_письма_собрано_кодом_и_правится(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, _ = стенд
    страница = клиент.get(f"/country/GE?batch=1&ids={_id(1)}&ids={_id(2)}").get_data(as_text=True)
    assert "data-letter-editor" in страница
    assert "Результаты проверок" in страница
    assert "Белград-1 |" in страница and "Белград-2 |" in страница  # строки таблицы


def test_разброс_больше_семи_дней_окно_отказывает_словами_без_письма(
    стенд: tuple[FlaskClient, Any],
) -> None:
    клиент, _ = стенд
    страница = клиент.get(f"/country/GE?batch=1&ids={_id(1)}&ids={_id(3)}").get_data(as_text=True)
    assert "data-letter-editor" not in страница
    assert "01.10.2026" in страница and "02.11.2026" in страница
    assert "не больше 7" in страница


def test_английский_интерфейс_отказ_на_английском(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, _ = стенд
    страница = клиент.get(f"/country/GE?batch=1&lang=en&ids={_id(1)}&ids={_id(3)}").get_data(
        as_text=True
    )
    assert "allows at most 7" in страница


def test_проверка_чужого_пространства_в_выборе_отказ(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, _ = стенд
    страница = клиент.get(f"/country/GE?batch=1&ids={_id(1)}&ids={_id(4)}").get_data(as_text=True)
    assert "data-letter-editor" not in страница
    assert "другому пространству" in страница


def _сохранить(клиент: FlaskClient, ids: list[int], *, страна: str = "GE") -> Any:
    return клиент.post(
        f"/country/{страна}/batch-letter/save",
        data={"ids": ",".join(_id(i) for i in ids), "text": "Текст письма", "letter_lang": "ru"},
        headers=СВОЙ,
    )


def test_сохранение_пишет_письмо_и_возвращает_в_окно(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, журнал = стенд
    ответ = _сохранить(клиент, [1, 2])
    assert ответ.status_code == 303
    assert "saved=ok" in ответ.headers["Location"]
    ((ids, поля),) = журнал["saved"]
    assert set(ids) == {_id(1), _id(2)}
    assert поля["country"] == "GE" and поля["body"] == "Текст письма" and поля["lang"] == "ru"


def test_сохранение_с_разбросом_больше_недели_не_пишет_ничего(
    стенд: tuple[FlaskClient, Any],
) -> None:
    клиент, журнал = стенд
    ответ = _сохранить(клиент, [1, 3])
    assert "saved=refused" in ответ.headers["Location"]
    assert журнал["saved"] == []


def test_сохранение_с_чужой_проверкой_не_пишет_ничего(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, журнал = стенд
    ответ = _сохранить(клиент, [1, 4])
    assert "saved=refused" in ответ.headers["Location"]
    assert журнал["saved"] == []


def test_чужая_страна_404_и_в_окне_и_в_сохранении(стенд: tuple[FlaskClient, Any]) -> None:
    клиент, журнал = стенд
    assert клиент.get("/country/AM?batch=1").status_code == 404
    assert _сохранить(клиент, [1, 2], страна="AM").status_code == 404
    assert журнал["saved"] == []


def test_черновик_без_реквизитов_google_сохраняет_письмо_и_говорит_что_почты_нет(
    стенд: tuple[FlaskClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    клиент, журнал = стенд
    monkeypatch.delenv("GOOGLE_MAIL_REDIRECT_URI", raising=False)
    ответ = клиент.post(
        "/country/GE/batch-letter/draft",
        data={"ids": f"{_id(1)},{_id(2)}", "text": "Текст", "letter_lang": "ru"},
        headers=СВОЙ,
    )
    assert ответ.status_code == 303
    assert "gmail=unavailable" in ответ.headers["Location"]
    assert len(журнал["saved"]) == 1


def test_адресаты_объединяются_без_повторов(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    a = _п(1, contact="a@x.com, B@x.com")
    b = _п(2, contact="b@x.com; c@x.com")
    monkeypatch.setattr(web.auth, "current_reach", lambda: None)
    assert web._addresses([a, b]) == "a@x.com, B@x.com, c@x.com"
    assert replace  # импорт нужен только для ясности набора


def test_строка_карточки_ссылается_на_письмо(
    monkeypatch: pytest.MonkeyPatch, стенд: tuple[FlaskClient, Any]
) -> None:
    from datetime import datetime

    письмо = store.SavedBatchLetter(
        id="x", country="GE", body="т", lang="ru", saved_by="u",
        created_at=datetime(2026, 11, 9, 12, 0), inspection_ids=(_id(1), _id(2)),
    )  # fmt: skip
    monkeypatch.setattr(store, "letters_of_inspection", lambda *_a, **_k: (письмо,))
    with стенд[0].application.test_request_context("/country/GE"):
        строки = web.card_lines(_id(1), ТЕНАНТ, "GE", "ru")
    assert строки[0]["date"] == "09.11.2026"
    assert "batch=1" in строки[0]["href"] and _id(2) in строки[0]["href"]


def test_ids_из_адреса_мусор_отбрасывается() -> None:
    assert web.parse_ids(f"{_id(1)}, не-id ,{_id(2)}") == (_id(1), _id(2))
