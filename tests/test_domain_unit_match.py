"""Сопоставление точек `units` с эталоном `unit_profiles` (#316, #909): ядро — ошибка тут тиха.

Привязка к неверной строке эталона переименует живую пиццерию в чужую и молча сольёт
историю, поэтому проверяется и то, что связывается, и то, что связываться НЕ должно.
"""

from __future__ import annotations

from dataclasses import replace

from src.domain.unit_match import (
    HIGH,
    MEDIUM,
    Ref,
    RefIndex,
    UnitRow,
    Usage,
    address_key,
    clean_ref_name,
    match_unit,
    plan,
)

CODE_1 = "a" * 32
CODE_8 = "b" * 32

REFS = [
    Ref("KG", "Bishkek-8", CODE_8, "Bishkek", "Бишкек, проспект Манаса, 7"),
    Ref("KG", "Bishkek-1", "c" * 32, "Bishkek", "Бишкек, ул. Шопокова, 101/1"),
    Ref("KG", "Bishkek-12", None, "Bishkek", "Бишкек, проспект Чынгыза Айтматова, 3"),
    Ref("KG", "Bishkek-6", None, "Bishkek", "Бишкек, проспект Чынгыза Айтматова, 3/1"),
    Ref("AM", "Yerevan-1", CODE_1, "Yerevan", "11 Vardanants st., Yerevan 0010"),
    Ref("AM", "Yerevan-2", None, "Yerevan", "Azatytian street , 23 Arabkir, Yerevan"),
    Ref("GE", "Tbilisi-1", "d" * 32, "Tbilisi", "Pekini Ave 17, Tbilisi, Georgia"),
    Ref("RS", "Belgrade-1", None, "Belgrade", "Угриновачка 39, Београд 11080"),
    Ref("ME", "Budva-1", None, "Budva", "bb, Mediteranska, Budva 85310, Montenegro"),
    Ref("ME", "Podgorica-1", None, "Podgorica", "Ankara Blvd. 22, Podgorica"),
    Ref("ME", "Podgorica-2", None, "Podgorica", "Aerodromska bb, Podgorica"),
    Ref("RO", "Bucharest-(5)", None, "Bucharest", "Calea Floreasca 1, București"),
    Ref("PL", "Warsaw-1", None, "Warsaw", "al. Jana Pawła II 18, Warszawa"),
]
INDEX = RefIndex(REFS)


def unit(name: str, **kw: object) -> UnitRow:
    return UnitRow(id=kw.pop("id", name), name=name, **kw)  # type: ignore[arg-type]


def found(u: UnitRow) -> tuple[str, str, str]:
    m = match_unit(u, INDEX)
    return (m.status, m.refs[0].name if m.status == "matched" else "", m.rule)


def test_code_beats_everything_else() -> None:
    assert found(unit("Что угодно", code=CODE_8, country="KG")) == ("matched", "Bishkek-8", "code")


def test_same_name_ignores_case_and_diacritics() -> None:
    assert found(unit("bishkek-8", country="KG"))[:2] == ("matched", "Bishkek-8")


def test_same_name_in_other_country_is_not_a_match() -> None:
    assert found(unit("Bishkek-8", country="AM"))[0] == "unmatched"


def test_numbered_name_in_other_alphabet() -> None:
    m = match_unit(unit("Тбилиси-1", country="GE"), INDEX)
    assert (m.refs[0].name, m.rule, m.confidence) == ("Tbilisi-1", "numbered", HIGH)


def test_numbered_name_without_country_is_only_medium() -> None:
    m = match_unit(unit("Белград-1"), INDEX)
    assert (m.refs[0].name, m.confidence) == ("Belgrade-1", MEDIUM)


def test_number_is_not_dropped() -> None:
    assert match_unit(unit("Тбилиси-2", country="GE"), INDEX).status == "unmatched"


def test_reference_name_noise_is_cleaned() -> None:
    assert clean_ref_name("Bucharest-(5)") == "Bucharest-5"
    assert clean_ref_name("Iasi - 1") == "Iasi-1"
    assert found(unit("Бухарест-5", country="RO"))[:2] == ("matched", "Bucharest-(5)")


def test_website_name_matches_by_street_and_house() -> None:
    m = match_unit(unit("Bishkek — 7 Manas Ave", country="KG", city="bishkek"), INDEX)
    assert (m.refs[0].name, m.rule, m.confidence) == ("Bishkek-8", "address", HIGH)


def test_cyrillic_street_matches_latin_one() -> None:
    u = unit("Bishkek — улица Шопокова 101/1", country="KG")
    assert found(u)[:2] == ("matched", "Bishkek-1")


def test_armenian_district_found_in_reference_address() -> None:
    m = match_unit(unit("Վարդանանց", country="AM"), INDEX)
    assert (m.refs[0].name, m.confidence) == ("Yerevan-1", MEDIUM)


def test_wrong_house_number_does_not_match() -> None:
    assert found(unit("Bishkek — 99 Manas Ave", country="KG"))[0] == "unmatched"


def test_street_of_other_country_does_not_match() -> None:
    assert found(unit("Manas Ave 7", country="AM"))[0] == "unmatched"


def test_two_candidates_are_ambiguous_and_nothing_is_picked() -> None:
    m = match_unit(unit("Bishkek — Chyngyza Aytmatova Ave", country="KG"), INDEX)
    assert m.status == "ambiguous"
    assert {r.name for r in m.refs} == {"Bishkek-12", "Bishkek-6"}


def test_city_name_with_one_point_matches_but_with_two_is_ambiguous() -> None:
    assert found(unit("Budva", country="ME"))[:2] == ("matched", "Budva-1")
    assert match_unit(unit("Podgorica", country="ME"), INDEX).status == "ambiguous"


def test_unknown_name_stays_unmatched() -> None:
    assert match_unit(unit("Mokotów", country="PL"), INDEX).status == "unmatched"


def test_address_key_ignores_street_type_and_splits_house() -> None:
    a = address_key("Бишкек, проспект Манаса, 7")
    assert a.houses == ("7",)
    assert "prospekt" not in "".join(a.words) and "7" not in a.words


# --- план ------------------------------------------------------------------------------------


def test_rename_fills_code_city_and_keeps_old_name_to_become_alias() -> None:
    (a,) = plan([unit("Bishkek — 7 Manas Ave", country="KG")], INDEX)
    assert (a.kind, a.new_name, a.new_code, a.new_city) == (
        "rename",
        "Bishkek-8",
        CODE_8,
        "bishkek",
    )


def test_country_is_taken_from_reference_when_missing() -> None:
    (a,) = plan([unit("Тбилиси-1")], INDEX)
    assert (a.kind, a.new_name, a.new_country) == ("rename", "Tbilisi-1", "GE")


def test_empty_duplicate_is_merged_into_the_point_with_code() -> None:
    real = unit("Yerevan-1", code=CODE_1, country="AM", city="yerevan")
    dup = unit("Վարդանանց", country="AM", city="yerevan")
    result = {a.unit.name: a for a in plan([dup, real], INDEX)}
    assert result["Վարդանանց"].kind == "merge" and result["Վարդանանց"].target is real
    assert result["Yerevan-1"].kind == "keep"


def test_duplicate_with_history_is_blocked_not_merged() -> None:
    real = unit("Tbilisi-1", code="d" * 32, country="GE", city="tbilisi", usage=Usage(2, 0, 0))
    dup = unit("Тбилиси-1", usage=Usage(0, 3, 0))
    result = {a.unit.name: a for a in plan([real, dup], INDEX)}
    assert result["Тбилиси-1"].kind == "blocked"
    assert "3 записей истории" in result["Тбилиси-1"].note


def test_duplicate_with_other_code_is_blocked() -> None:
    real = unit("Yerevan-1", code=CODE_1, country="AM", city="yerevan")
    dup = unit("Վարդանանց", code="e" * 32, country="AM")
    assert {a.unit.name: a.kind for a in plan([real, dup], INDEX)}["Վարդանանց"] == "blocked"


def test_point_with_inspections_survives_over_empty_one_without_code() -> None:
    old = unit("Yerevan-1", country="AM", city="yerevan", usage=Usage(1, 0, 0))
    web = unit("Vardanants", country="AM")
    result = {a.unit.name: a for a in plan([old, web], INDEX)}
    assert result["Vardanants"].kind == "merge" and result["Vardanants"].target is old


def test_point_already_named_like_the_reference_wins_over_website_duplicate() -> None:
    named = unit("bishkek-8", id="x", country="KG")
    web = unit("Bishkek — 7 Manas Ave", country="KG")
    result = {a.unit.id: a for a in plan([web, named], INDEX)}
    assert result["x"].kind == "fill" and result[web.id].kind == "merge"


def test_below_threshold_is_not_touched() -> None:
    (a,) = plan([unit("Վարդանանց", country="AM")], INDEX, min_confidence=HIGH)
    assert a.kind == "skipped" and not a.writes


def test_plan_is_idempotent_after_applying() -> None:
    first = plan([unit("Bishkek — 7 Manas Ave", country="KG", city="bishkek")], INDEX)[0]
    done = unit(
        first.new_name or "", id="1", code=first.new_code, country="KG", city="bishkek",
        aliases=("Bishkek — 7 Manas Ave",),
    )  # fmt: skip
    assert plan([done], INDEX)[0].kind == "keep"
    assert plan([replace(done, aliases=())], INDEX)[0].kind == "keep"


def test_unmatched_and_ambiguous_never_write() -> None:
    acts = plan([unit("Mokotów", country="PL"), unit("Podgorica", country="ME")], INDEX)
    assert [a.kind for a in acts] == ["unmatched", "ambiguous"]
    assert not any(a.writes for a in acts)
