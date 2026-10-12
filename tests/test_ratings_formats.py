"""Разбор трёх выгрузок Dodo IS (ядро рейтингов, спека «Источники»).

Каждый случай — пара: целый файл разобран верно, испорченная копия того же
файла дала понятный отказ или строку журнала, а не тихую потерю.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ratings_samples import (
    C1,
    C3,
    P_RKO,
    P_RS,
    RKO_VIOLATIONS_HEADER,
    U1,
    kb,
    rko_evaluations,
    rko_violations,
    rs_checkups,
    to_csv,
)

from src.ratings.countries import country_code
from src.ratings.formats import (
    detect_format,
    parse_rko_evaluations,
    parse_rko_violations,
    parse_rs_checkups,
)
from src.ratings.links import backoffice_checkup_id, hex_id, parse_rating_link, unit_rating_url
from src.ratings.model import (
    CATEGORY_OTHER,
    CATEGORY_VIOLATION,
    ERR_BAD_CSV,
    ERR_EMPTY,
    ERR_MISSING_COLUMNS,
    ERR_NOT_UTF8,
    ERR_UNKNOWN_FORMAT,
    ISSUE_BAD_ROW,
    ISSUE_COUNTRY_UNKNOWN,
    RKO,
    RS,
    RatingsFormatError,
)

# --- ссылки ------------------------------------------------------------------


def test_ссылка_на_рейтинг_разбирается() -> None:
    link = parse_rating_link(kb(U1, 2, C1, P_RS))
    assert link is not None
    assert (link.unit_id, link.rating_type, link.checkup_id, link.period_id) == (U1, RS, C1, P_RS)


def test_испорченная_ссылка_не_разбирается() -> None:
    assert parse_rating_link(kb(U1, 2, C1, P_RS).replace(U1, "не-id")) is None
    assert parse_rating_link("https://evil.example/rating#/" + U1 + "/2") is None
    new_host = kb(U1, 2, C1, P_RS).replace("dodopizza.info", "knowledgebase.dodois.io")
    assert parse_rating_link(new_host) == parse_rating_link(kb(U1, 2, C1, P_RS))
    assert backoffice_checkup_id("https://control.dodois.io/backoffice/checkups/xyz") is None


def test_id_с_дефисами_и_заглавными_приводится() -> None:
    assert hex_id("AA000000-0000-0000-0000-000000000001") == U1
    assert hex_id(12345) is None


def test_ссылка_на_страницу_пиццерии() -> None:
    assert unit_rating_url(U1, RKO) == f"https://knowledgebase.dodois.io/rating#/{U1}/1"


# --- страны ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("имя", "код"),
    [
        ("Serbia", "RS"),
        ("Беларусь", "BY"),
        ("Turkey", "TR"),
        ("Кыргызстан", "KG"),
        ("  россия ", "RU"),
        ("Narnia", None),
    ],
)
def test_страна_по_имени_на_двух_языках(имя: str, код: str | None) -> None:
    assert country_code(имя) == код


# --- rko-violations ------------------------------------------------------------


def test_нарушения_ркО_разобраны() -> None:
    parsed = parse_rko_violations(rko_violations())
    assert parsed.skipped == 1  # Россия отброшена по стране (D318)
    assert parsed.issues == ()
    first, second = parsed.checkups
    assert (first.rating_type, first.dodo_id, first.unit.dodo_id, first.unit.country) == (
        RKO,
        C1,
        U1,
        "RS",
    )
    assert first.channel == "delivery" and second.channel == "restaurant"
    assert first.period_dodo_id == P_RKO
    assert first.occurred_at == datetime(2026, 10, 6, 10, 14, 19, tzinfo=UTC)
    texts = {(v.text, v.category, v.auto_detected, v.amount) for v in first.violations}
    assert texts == {
        ("Ингредиенты на бортах", CATEGORY_VIOLATION, False, 2),
        ("Пицца деформирована (ML)", CATEGORY_VIOLATION, True, 1),
    }
    assert [(v.text, v.category) for v in second.violations] == [
        ("Пиццу привезли холодной", CATEGORY_OTHER)
    ]
    assert second.unit.country == "BY"


def test_нарушения_ркО_битая_ссылка_строкой_журнала() -> None:
    parsed = parse_rko_violations(
        rko_violations(KnowledgeBaseLink="https://dodopizza.info/rating#/xx/1")
    )
    assert len(parsed.checkups) == 1
    assert [(i.row_no, i.reason) for i in parsed.issues] == [(2, ISSUE_BAD_ROW)]


def test_нарушения_ркО_тип_рейтинга_в_ссылке_чужой() -> None:
    parsed = parse_rko_violations(rko_violations(KnowledgeBaseLink=kb(U1, 2, C1, P_RKO)))
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_нарушения_ркО_незнакомая_страна_не_теряется() -> None:
    parsed = parse_rko_violations(rko_violations(Страна="Narnia"))
    assert [(i.reason, i.detail["country"]) for i in parsed.issues] == [
        (ISSUE_COUNTRY_UNKNOWN, "Narnia")
    ]


def test_нарушения_ркО_неизвестный_тип_проверки() -> None:
    parsed = parse_rko_violations(rko_violations(CheckupType="Самовывоз"))
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_нарушения_ркО_без_колонки_отказ_целиком() -> None:
    header = [h if h != "KnowledgeBaseLink" else "KBLink" for h in RKO_VIOLATIONS_HEADER]
    with pytest.raises(RatingsFormatError, match="KnowledgeBaseLink") as exc:
        parse_rko_violations(to_csv(header, [["x"] * len(header)]))
    assert exc.value.code == ERR_MISSING_COLUMNS
    assert exc.value.params["columns"] == "KnowledgeBaseLink"


# --- rko-evaluations -----------------------------------------------------------


def test_приёмка_ркО_разобрана() -> None:
    parsed = parse_rko_evaluations(rko_evaluations())
    assert parsed.skipped == 1
    assert [(e.dodo_id, e.country, e.acceptance) for e in parsed.evaluations] == [
        (C1, "RS", "accepted"),
        (C3, "KG", "rejected"),
    ]


def test_приёмка_ркО_с_припиской_в_заголовке() -> None:
    data = rko_evaluations().replace(
        "Результат оценки".encode(), "Результат оценки(Принято/Отклонено)".encode()
    )
    assert len(parse_rko_evaluations(data).evaluations) == 2


def test_приёмка_ркО_незнакомый_результат() -> None:
    data = rko_evaluations().replace("Принято".encode(), "Может быть".encode(), 1)
    parsed = parse_rko_evaluations(data)
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


# --- rs-checkups -----------------------------------------------------------------


def test_проверки_рС_разобраны() -> None:
    parsed = parse_rs_checkups(rs_checkups())
    assert parsed.skipped == 1
    first, second = parsed.checkups
    assert (
        first.rating_type,
        first.dodo_id,
        first.unit.dodo_id,
        first.channel,
        first.duration_min,
    ) == (
        RS,
        C1,
        U1,
        "inspection",
        42,
    )
    assert (second.channel, second.duration_min, second.unit.country) == ("online", None, "SI")
    assert first.violations == ()


# --- узнавание формата -------------------------------------------------------------


def test_формат_узнаётся_по_заголовку_а_не_по_имени() -> None:
    assert detect_format(rko_violations()) == "rko-violations"
    assert detect_format(rko_evaluations()) == "rko-evaluations"
    assert detect_format(rs_checkups()) == "rs-checkups"
    assert detect_format(b'  {"version": 1}') == "snapshot"


def test_сохранённый_в_excel_с_точкой_с_запятой_читается() -> None:
    from ratings_samples import RS_CHECKUPS_HEADER

    data = to_csv(
        RS_CHECKUPS_HEADER,
        [
            [
                "Testville-1",
                "https://control.dodois.io/backoffice/checkups/" + C1,
                kb(U1, 2, C1, P_RS),
                "06.10.2026 15:15",
                "",
                "",
                "IMF",
                "Serbia",
                "",
                "Инспекция",
                "42",
            ]
        ],
        delimiter=";",
    )
    assert detect_format(data) == "rs-checkups"
    parsed = parse_rs_checkups(data)
    assert parsed.issues == ()
    assert parsed.checkups[0].occurred_at == datetime(2026, 10, 6, 15, 15, tzinfo=UTC)


def test_дата_excel_с_секундами() -> None:
    data = rs_checkups().replace(b"2026-10-06 15:15:00", b"06.10.2026 15:15:07")
    parsed = parse_rs_checkups(data)
    assert parsed.issues == ()
    assert parsed.checkups[0].occurred_at == datetime(2026, 10, 6, 15, 15, 7, tzinfo=UTC)


def test_дата_не_по_образцу_строкой_журнала() -> None:
    parsed = parse_rs_checkups(rs_checkups().replace(b"2026-10-06 15:15:00", b"06/10/2026"))
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]


def test_продолжительность_надстрочная_цифра_строкой_журнала() -> None:
    data = rs_checkups().replace(b",42\r\n", ",".encode() + "²".encode() + b"\r\n")
    parsed = parse_rs_checkups(data)
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]
    assert len(parsed.checkups) == 1  # вторая строка принята, РФ отброшена


def test_файл_без_bom_и_с_lf_читается() -> None:
    data = rs_checkups().removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
    parsed = parse_rs_checkups(data)
    assert len(parsed.checkups) == 2 and parsed.issues == ()


def test_ячейка_длиннее_лимита_csv_отказ_а_не_падение() -> None:
    data = rs_checkups().replace("Тест Тестов".encode(), b"x" * 200_000, 1)
    with pytest.raises(RatingsFormatError, match="повреждён") as exc:
        parse_rs_checkups(data)
    assert exc.value.code == ERR_BAD_CSV


def test_не_utf8_отказ_с_подсказкой() -> None:
    data = "Пиццерия,Страна\r\nТест,Сербия\r\n".encode("cp1251")
    with pytest.raises(RatingsFormatError, match="UTF-8") as exc:
        detect_format(data)
    assert exc.value.code == ERR_NOT_UTF8


def test_незнакомый_файл_отказ_с_перечнем() -> None:
    with pytest.raises(RatingsFormatError, match="rko-violations") as exc:
        detect_format(to_csv(["a", "b"], [["1", "2"]]))
    assert exc.value.code == ERR_UNKNOWN_FORMAT


def test_пустой_файл_отказ() -> None:
    with pytest.raises(RatingsFormatError, match="пуст") as exc:
        detect_format(b"")
    assert exc.value.code == ERR_EMPTY


# --- ссылки из файла недоверенные: в результат идёт только собранный заново URL ---


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        f"https://evil.example/backoffice/checkups/{C1}",
        f"https://control.dodois.io@evil.example/backoffice/checkups/{C1}",
        f"https://a@b/backoffice/checkups/{C1}",
    ],
)
def test_чужая_ссылка_бэкофиса_строка_отвергается(link: str) -> None:
    parsed = parse_rko_violations(rko_violations(Link=link))
    assert [i.reason for i in parsed.issues] == [ISSUE_BAD_ROW]
    assert len(parsed.checkups) == 1


@pytest.mark.parametrize("field", ["Link", "KnowledgeBaseLink"])
def test_ссылки_в_результате_собраны_заново_а_не_из_ячейки(field: str) -> None:
    evil = '"><script>alert(1)</script>'
    link = {
        "Link": f"https://control.dodois.io/backoffice/checkups/{C1}?x={evil}",
        "KnowledgeBaseLink": kb(U1, 1, C1, P_RKO) + "&x=" + evil,
    }[field]
    first = parse_rko_violations(rko_violations(**{field: link})).checkups[0]
    assert first.backoffice_url == f"https://control.dodois.io/backoffice/checkups/{C1}"
    assert first.rating_url == (
        f"https://knowledgebase.dodois.io/rating#/{U1}/1?selectedRemarkType=0&openRemarkDetails=1"
        f"&checkupId={C1}&ratingPeriodId={P_RKO}"
    )
    assert "script" not in first.backoffice_url + first.rating_url
