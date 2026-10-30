"""Письмо не теряет замечания, когда в одной зоне их больше трёх."""

from collections.abc import Callable

import pytest
from conftest import Run


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("level", ["D1", "D2"])
def test_all_findings_in_a_zone_reach_the_letter(
    started: Callable[..., Run], report: Callable[..., Run], lang: str, level: str
) -> None:
    remarks = [
        f"Recorded observation {n}: complete wording with a distinct ending END-{n}"
        for n in range(1, 5)
    ]
    for code, remark in zip(("PRD01", "PRD05", "PRD09", "PRD10"), remarks, strict=True):
        result = started(
            "add",
            "--qid",
            code,
            "--level",
            level,
            "--zone",
            "fridge",
            "--evidence",
            remark,
        )
        assert result.code == 0, result.text
    result = report("letter", "--lang", lang)
    assert result.code == 0, result.text
    for remark in remarks:
        assert remark in result.out, f"Letter omitted a recorded finding: {remark}"
    assert " …" not in result.out
