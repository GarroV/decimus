"""Снимок рейтинга Dodo IS (ядро рейтингов): JSON, который собирает Claude в браузере.

Части самостоятельны; пиццерия с битым элементом целиком уходит в журнал;
замечания периодов РКО отбрасываются — нарушения РКО идут из выгрузки.
Снимок — недоверенный вход: любое поле может быть не тем типом, огромным или
отсутствовать, и это никогда не необработанное исключение.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest
from ratings_samples import P_RS, U1, U2, snapshot, snapshot_doc

from src.ratings.model import (
    CATEGORY_REMARK,
    ERR_BAD_JSON,
    ERR_BAD_SNAPSHOT,
    ERR_BAD_VERSION,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    RKO,
    RS,
    RatingsFormatError,
)
from src.ratings.snapshot import parse_snapshot

HUGE = "я" * 100_000


def _with_neighbour(**unit_override: object) -> bytes:
    """Снимок с испорченной пиццерией и здоровой соседкой — соседка не должна пострадать."""
    # Замена истории без замечаний: иначе замечания к исчезнувшему периоду уводят
    # пиццерию в журнал по другой причине, и проверка поля истории ничего не доказывает.
    if "history" in unit_override:
        unit_override = {"remarks": [], **unit_override}
    doc = snapshot_doc(**unit_override)
    neighbour = copy.deepcopy(snapshot_doc()["units"][0])  # type: ignore[index]
    neighbour.update({"dodo_id": U2, "name": "Testville-2"})
    doc["units"].append(neighbour)  # type: ignore[attr-defined]
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def _period(**override: object) -> dict[str, Any]:
    period: dict[str, Any] = {
        "id": P_RS,
        "rating_type": 2,
        "begin": "2026-09-16",
        "end": "2026-09-30",
        "alias": "Сентябрь 2",
    }
    period.update(override)
    return period


def _history(score: object = 90, status: object = "1", **period: object) -> list[dict[str, Any]]:
    return [{"score": score, "status": status, "period": _period(**period)}]


def test_снимок_разобран() -> None:
    parsed = parse_snapshot(snapshot())
    assert parsed.label == "часть 2 из 3"
    assert [(c.code, c.dodo_id) for c in parsed.countries] == [("RS", 12)]
    assert parsed.skipped == 2  # пиццерия России и замечания периода РКО
    scores = {
        (s.period.rating_type, s.period.begin_on): (s.score, s.checkups_count)
        for s in parsed.scores
    }
    assert scores == {(RS, date(2026, 9, 16)): (97.5, 4), (RKO, date(2026, 9, 29)): (91.0, None)}
    assert {s.unit.dodo_id for s in parsed.scores} == {U1}
    (remark,) = parsed.remarks
    assert (
        remark.period.dodo_id,
        remark.violation.text,
        remark.violation.category,
        remark.violation.amount,
        remark.violation.parent_name,
    ) == (P_RS, "Грязный пол", CATEGORY_REMARK, 2, "D1")
    assert parsed.issues == ()


def test_не_json_отказ_с_кодом() -> None:
    with pytest.raises(RatingsFormatError, match="JSON") as caught:
        parse_snapshot(b"{not json")
    assert caught.value.code == ERR_BAD_JSON


def test_чужая_версия_отказ_с_кодом() -> None:
    with pytest.raises(RatingsFormatError, match="version") as caught:
        parse_snapshot(json.dumps({"version": 2, "countries": [], "units": []}).encode())
    assert caught.value.code == ERR_BAD_VERSION


def test_битый_период_уводит_пиццерию_в_журнал() -> None:
    parsed = parse_snapshot(
        snapshot(history=[{"score": 90, "period": {"id": "x", "rating_type": 2}}])
    )
    assert [(i.row_no, i.reason) for i in parsed.issues] == [(1, ISSUE_BAD_ROW)]
    assert parsed.scores == () and parsed.remarks == ()


def test_замечание_к_неизвестному_периоду_в_журнал() -> None:
    parsed = parse_snapshot(
        snapshot(remarks=[{"period_id": "ee" * 16, "checkups": 1, "items": []}])
    )
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_страна_без_справочника_в_журнал() -> None:
    parsed = parse_snapshot(snapshot(country_id=777))
    assert [i.reason for i in parsed.issues] == [ISSUE_COUNTRY_UNKNOWN]


def test_wow_не_замечание() -> None:
    parsed = parse_snapshot(snapshot())
    assert all(r.violation.text != "Улыбка" for r in parsed.remarks)


# --- недоверенный вход: плохая пиццерия уходит в журнал, файл жив ---

_BAD_UNITS: list[tuple[str, dict[str, Any]]] = [
    ("history не список", {"history": 5}),
    ("history словарь", {"history": {"a": 1}}),
    ("remarks не список", {"remarks": "x"}),
    ("элемент истории не словарь", {"history": [7]}),
    ("период не словарь", {"history": [{"score": 1, "period": "x"}]}),
    ("не-hex id периода", {"history": _history(id="zz" * 16)}),
    ("id периода с хвостом", {"history": _history(id=P_RS + "0")}),
    ("id периода числом", {"history": _history(id=123)}),
    ("тип рейтинга списком", {"history": _history(rating_type=[2])}),
    ("тип рейтинга неизвестный", {"history": _history(rating_type=9)}),
    ("дата числом", {"history": _history(begin=20260916)}),
    ("дата мусором", {"history": _history(begin="вчера")}),
    ("дата с мусором в хвосте", {"history": _history(begin="2026-09-16garbage")}),
    ("конец раньше начала", {"history": _history(begin="2026-09-30", end="2026-09-16")}),
    ("балл строкой", {"history": _history(score="97")}),
    ("балл булевый", {"history": _history(score=True)}),
    ("балл выше 100", {"history": _history(score=100.5)}),
    ("балл ниже 0", {"history": _history(score=-1)}),
    ("балл NaN", {"history": _history(score=float("nan"))}),
    ("балл бесконечность", {"history": _history(score=float("inf"))}),
    ("балл огромное целое", {"history": _history(score=10**400)}),
    ("статус словарём", {"history": _history(status={"a": 1})}),
    ("alias списком", {"history": _history(alias=["x"])}),
    ("alias огромный", {"history": _history(alias=HUGE)}),
    ("период повторён", {"history": _history() + _history()}),
    ("замечания блок не словарь", {"remarks": [1]}),
    ("period_id замечаний списком", {"remarks": [{"period_id": [P_RS], "items": []}]}),
    ("items не список", {"remarks": [{"period_id": P_RS, "checkups": 1, "items": 3}]}),
    ("item не словарь", {"remarks": [{"period_id": P_RS, "checkups": 1, "items": ["x"]}]}),
    (
        "item без названия",
        {"remarks": [{"period_id": P_RS, "checkups": 1, "items": [{"amount": 1}]}]},
    ),
    ("название числом", {"remarks": [{"period_id": P_RS, "items": [{"name": 5}]}]}),
    ("название огромное", {"remarks": [{"period_id": P_RS, "items": [{"name": HUGE}]}]}),
    ("amount строкой", {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "amount": "2"}]}]}),
    ("amount ноль", {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "amount": 0}]}]}),
    (
        "amount огромный",
        {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "amount": 10**12}]}]},
    ),
    ("amount дробный", {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "amount": 1.5}]}]}),
    (
        "deduction строкой",
        {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "deduction": "-1"}]}]},
    ),
    (
        "deduction огромный",
        {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "deduction": 10**400}]}]},
    ),
    (
        "criterion_id словарём",
        {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "criterion_id": {}}]}]},
    ),
    (
        "parent огромный",
        {"remarks": [{"period_id": P_RS, "items": [{"name": "x", "parent": HUGE}]}]},
    ),
    ("checkups огромное", {"remarks": [{"period_id": P_RS, "checkups": 10**12, "items": []}]}),
    ("checkups строкой", {"remarks": [{"period_id": P_RS, "checkups": "4", "items": []}]}),
    (
        "блок замечаний повторён",
        {"remarks": [{"period_id": P_RS, "items": []}, {"period_id": P_RS, "items": []}]},
    ),
    ("название пиццерии огромное", {"name": HUGE}),
    ("название пиццерии числом", {"name": 5}),
    ("название пиццерии пустое", {"name": "  "}),
    ("id пиццерии не hex", {"dodo_id": "not-a-hex-id"}),
    ("id пиццерии числом", {"dodo_id": 12345}),
    ("id пиццерии пропал", {"dodo_id": None}),
]


def test_эталонная_история_без_замечаний_принимается() -> None:
    """Опора для таблицы испорченных пиццерий: исправный вариант той же формы не в журнале."""
    parsed = parse_snapshot(_with_neighbour(history=_history()))
    assert parsed.issues == ()
    assert {s.unit.dodo_id for s in parsed.scores} == {U1, U2}


@pytest.mark.parametrize("override", [o for _, o in _BAD_UNITS], ids=[n for n, _ in _BAD_UNITS])
def test_испорченная_пиццерия_в_журнал_соседка_цела(override: dict[str, Any]) -> None:
    parsed = parse_snapshot(_with_neighbour(**override))
    assert [i.row_no for i in parsed.issues] == [1]
    assert parsed.issues[0].reason == ISSUE_BAD_ROW
    assert all(len(v) <= 200 for v in parsed.issues[0].detail.values())
    assert {s.unit.dodo_id for s in parsed.scores} == {U2}
    assert {r.unit.dodo_id for r in parsed.remarks} == {U2}


@pytest.mark.parametrize("country_id", ["12", None, [12], {"a": 1}, True, 1.5, 10**30])
def test_страна_пиццерии_не_числом_в_журнал(country_id: object) -> None:
    parsed = parse_snapshot(_with_neighbour(country_id=country_id))
    assert [(i.row_no, i.reason) for i in parsed.issues] == [(1, ISSUE_COUNTRY_UNKNOWN)]
    assert {s.unit.dodo_id for s in parsed.scores} == {U2}
    assert all(len(v) <= 200 for v in parsed.issues[0].detail.values())


def test_строка_units_не_словарь_в_журнал() -> None:
    doc = snapshot_doc()
    doc["units"] = [5, None, "x", [1], *doc["units"]]  # type: ignore[misc]
    parsed = parse_snapshot(json.dumps(doc).encode())
    assert [i.row_no for i in parsed.issues] == [1, 2, 3, 4]
    assert {s.unit.dodo_id for s in parsed.scores} == {U1}


def test_замечания_без_wow_и_неизвестные_поля_терпятся() -> None:
    parsed = parse_snapshot(
        snapshot(
            remarks=[
                {
                    "period_id": P_RS.upper(),
                    "extra": [1],
                    "items": [
                        {"name": "Грязный пол", "wow": None, "ссылка": "https://evil.example/x"}
                    ],
                }
            ]
        )
    )
    assert parsed.issues == ()
    assert [r.violation.text for r in parsed.remarks] == ["Грязный пол"]


def test_ссылки_из_снимка_не_берутся() -> None:
    parsed = parse_snapshot(
        snapshot(
            history=_history(url="https://evil.example/x", alias="ok"),
            remarks=[
                {"period_id": P_RS, "items": [{"name": "x", "url": "https://evil.example/y"}]}
            ],
        )
    )
    dumped = repr(parsed)
    assert "evil.example" not in dumped


_BAD_DOCS: list[tuple[str, Any, str]] = [
    ("корень массив", [], ERR_BAD_VERSION),
    ("корень число", 5, ERR_BAD_VERSION),
    ("корень null", None, ERR_BAD_VERSION),
    ("version булевый", {"version": True, "countries": [], "units": []}, ERR_BAD_VERSION),
    ("version строкой", {"version": "1", "countries": [], "units": []}, ERR_BAD_VERSION),
    ("нет списков", {"version": 1}, ERR_BAD_SNAPSHOT),
    ("countries словарь", {"version": 1, "countries": {}, "units": []}, ERR_BAD_SNAPSHOT),
    ("units строкой", {"version": 1, "countries": [], "units": "x"}, ERR_BAD_SNAPSHOT),
    ("страна не словарь", {"version": 1, "countries": [5], "units": []}, ERR_BAD_SNAPSHOT),
    (
        "страна без id",
        {"version": 1, "countries": [{"name": "Serbia"}], "units": []},
        ERR_BAD_SNAPSHOT,
    ),
    (
        "id страны булевый",
        {"version": 1, "countries": [{"id": True, "name": "Serbia"}], "units": []},
        ERR_BAD_SNAPSHOT,
    ),
    (
        "id страны строкой",
        {"version": 1, "countries": [{"id": "1", "name": "Serbia"}], "units": []},
        ERR_BAD_SNAPSHOT,
    ),
]


@pytest.mark.parametrize(
    ("doc", "code"), [(d, c) for _, d, c in _BAD_DOCS], ids=[n for n, _, _ in _BAD_DOCS]
)
def test_испорченный_документ_отказ_с_кодом_а_не_исключение(doc: Any, code: str) -> None:
    with pytest.raises(RatingsFormatError) as caught:
        parse_snapshot(json.dumps(doc).encode())
    assert caught.value.code == code


_GARBAGE: list[tuple[str, bytes]] = [
    ("пусто", b""),
    ("не utf-8", b"\xff\xfe\x00{"),
    ("бинарщина", bytes(range(256))),
    ("обрыв", b'{"version": 1, "units": ['),
    ("вложенность 100000", b"[" * 100_000 + b"]" * 100_000),
    ("огромное целое", b'{"version": 1, "x": ' + b"9" * 6000 + b"}"),
    ("csv вместо json", "Страна,Пиццерия\r\nSerbia,Testville-1\r\n".encode()),
]


@pytest.mark.parametrize("data", [d for _, d in _GARBAGE], ids=[n for n, _ in _GARBAGE])
def test_мусор_вместо_json_отказ_с_кодом(data: bytes) -> None:
    with pytest.raises(RatingsFormatError) as caught:
        parse_snapshot(data)
    assert caught.value.code in {ERR_BAD_JSON, ERR_BAD_VERSION}


def test_огромная_строка_в_журнале_обрезана() -> None:
    parsed = parse_snapshot(snapshot(name=HUGE))
    assert len(str(parsed.issues[0].detail["unit"])) <= 200


def test_подпись_части_из_мусора_не_падает() -> None:
    doc = snapshot_doc()
    doc["chunk"] = {"index": HUGE, "of": [3]}
    assert parse_snapshot(json.dumps(doc).encode()).label is None
    doc["chunk"] = "x"
    assert parse_snapshot(json.dumps(doc).encode()).label is None
