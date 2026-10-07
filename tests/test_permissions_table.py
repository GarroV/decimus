# tests/test_permissions_table.py
"""Таблица «роль × действие × пространство человека × пространство объекта × автор → да/нет».

Таблица ролей переписана здесь руками из спеки с поправками D310 и D311, а не
взята из кода: иначе тест сверял бы `DEFAULT_MATRIX` с самим собой. Проверка
таблицы прогоняется и на заведомо сломанной матрице, и на заведомо сломанном
`can` — она обязана покраснеть и назвать нарушенное правило (`testing.md`).

Оракул `ожидание()` — копия правил спеки, а не кода: его сходство с
`permissions._boundary` ожидаемо, а расхождение — дефект одного из двух.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from src.domain.permissions import (
    DEFAULT_MATRIX,
    ROLE_SCOPES,
    RULE_MATRIX,
    RULE_OK,
    Actor,
    Decision,
    can,
    canonical_role,
    validate_matrix,
)

ВСЕ = frozenset(
    {
        "inspection.conduct",
        "inspection.retract",
        "inspection.move",
        "inspection.accept",
        "inspection.revise",
        "inspection.letter",
        "prescription.manage",
        "prescription.reply",
        "plan.manage",
        "plan.submit",
        "checklist.edit",
        "checklist.publish",
        "checklist.manage",
        "phrases.manage",
        "people.manage",
        "mcp.connect",
        "unit.create",
        "space.manage",
        "roles.manage",
    }
)
ТОЛЬКО_УК = frozenset({"unit.create", "space.manage", "roles.manage"})
НАД_ПРОВЕРКОЙ = frozenset(
    {
        "inspection.retract",
        "inspection.move",
        "inspection.accept",
        "inspection.revise",
        "inspection.letter",
    }
)


def _все(коды: frozenset[str]) -> dict[str, str]:
    return {код: "all" for код in коды}


СВОИ = {код: "own" for код in НАД_ПРОВЕРКОЙ}
СПЕКА: dict[str, dict[str, str]] = {
    "hq_admin": _все(ВСЕ),
    # D310: unit.create у сотрудника УК остаётся; D311: над проверкой — свои.
    "hq_staff": {**_все(ВСЕ - {"people.manage", "space.manage", "roles.manage"}), **СВОИ},
    "country_admin": _все(ВСЕ - ТОЛЬКО_УК),
    "country_staff": {
        **_все(
            frozenset({"inspection.conduct", "prescription.reply", "plan.submit", "mcp.connect"})
        ),
        **СВОИ,
    },
}
ПРОСТРАНСТВО = {"hq_admin": "HQ", "hq_staff": "HQ", "country_admin": "GE", "country_staff": "GE"}
ОБЪЕКТЫ = ("HQ", "GE", "AM")
АВТОРЫ = ("я", "другой", "неизвестен")

Решатель = Callable[..., Decision]


def _учётка(роль: str) -> str:
    return f"u-{роль}"


def _автор(роль: str, кто: str) -> str | None:
    return {"я": _учётка(роль), "другой": "u-other", "неизвестен": None}[кто]


def ожидание(роль: str, действие: str, объект: str, автор: str) -> tuple[bool, str]:
    кто = ПРОСТРАНСТВО[роль]
    if кто != "HQ":
        if действие in ТОЛЬКО_УК:
            return False, "hq_only"
        if объект == "HQ":
            return False, "hq_object"
        if объект != кто:
            return False, "foreign_space"
    охват = СПЕКА[роль].get(действие)
    if охват is None:
        return False, "matrix"
    if охват == "own" and автор != "я":
        return False, "not_author"
    return True, "ok"


def _строки(действие: str) -> tuple[str, ...]:
    return АВТОРЫ if действие in НАД_ПРОВЕРКОЙ else ("—",)


def сверить(решать: Решатель, матрица: Mapping[str, Mapping[str, str]]) -> list[str]:
    нарушения: list[str] = []
    for роль, кто in ПРОСТРАНСТВО.items():
        человек = Actor(tenant=кто, role=роль, grants=матрица[роль], user_id=_учётка(роль))
        for действие in sorted(ВСЕ):
            for объект in ОБЪЕКТЫ:
                for автор in _строки(действие):
                    можно, правило = ожидание(роль, действие, объект, автор)
                    if действие in НАД_ПРОВЕРКОЙ:
                        вышло = решать(человек, действие, объект, object_author=_автор(роль, автор))
                    else:
                        вышло = решать(человек, действие, объект)
                    if вышло.allowed != можно:
                        нарушения.append(
                            f"{роль} × {действие} × {объект} × {автор}: ожидалось "
                            f"{'да' if можно else 'нет'} ({правило}), вышло "
                            f"{'да' if вышло.allowed else 'нет'} ({вышло.rule})"
                        )
    return нарушения


def _сломать(роль: str, **права: str) -> dict[str, Mapping[str, str]]:
    return {**DEFAULT_MATRIX, роль: {**DEFAULT_MATRIX[роль], **права}}


def test_матрица_по_умолчанию_равна_таблице_спеки() -> None:
    assert {р: dict(п) for р, п in DEFAULT_MATRIX.items()} == СПЕКА
    assert dict(ROLE_SCOPES) == {
        "hq_admin": "hq",
        "hq_staff": "hq",
        "country_admin": "country",
        "country_staff": "country",
    }


def test_таблица_прав_ролей_по_умолчанию() -> None:
    assert сверить(can, DEFAULT_MATRIX) == []


def test_сломанная_матрица_не_пробивает_границу() -> None:
    сломанная = _сломать("country_staff", **{"checklist.edit": "all"})
    assert сверить(can, сломанная) == [
        "country_staff × checklist.edit × GE × —: ожидалось нет (matrix), вышло да (ok)"
    ]


def test_сломанный_охват_свои_называет_каждую_чужую_проверку() -> None:
    сломанная = _сломать("hq_staff", **{"inspection.retract": "all"})
    assert сверить(can, сломанная) == [
        f"hq_staff × inspection.retract × {объект} × {автор}: ожидалось нет (not_author), "
        f"вышло да (ok)"
        for объект in ОБЪЕКТЫ
        for автор in ("другой", "неизвестен")
    ]


def test_проверка_таблицы_ловит_can_без_автора() -> None:
    def автор_всегда_свой(человек: Actor, действие: str, объект: str, **_: object) -> Decision:
        return can(человек, действие, объект, object_author=человек.user_id)

    нарушения = сверить(автор_всегда_свой, DEFAULT_MATRIX)
    assert (
        "country_staff × inspection.move × GE × неизвестен: ожидалось нет (not_author), "
        "вышло да (ok)" in нарушения
    )


def test_проверка_таблицы_ловит_снятую_границу() -> None:
    def без_границы(человек: Actor, действие: str, _объект: str, **_: object) -> Decision:
        if действие in человек.grants:
            return Decision(True, RULE_OK)
        return Decision(False, RULE_MATRIX)

    нарушения = сверить(без_границы, _сломать("country_staff", **{"checklist.edit": "all"}))
    assert (
        "country_staff × checklist.edit × HQ × —: ожидалось нет (hq_object), вышло да (ok)"
        in нарушения
    )
    assert any("(foreign_space)" in н for н in нарушения)


def test_матрица_по_умолчанию_годна() -> None:
    assert validate_matrix(DEFAULT_MATRIX, ROLE_SCOPES) == []


def test_проверка_матрицы_называет_только_уК_у_роли_страны() -> None:
    assert validate_matrix(_сломать("country_admin", **{"unit.create": "all"}), ROLE_SCOPES) == [
        "country_admin: unit.create — действие только УК (hq_only)"
    ]


def test_проверка_матрицы_называет_свои_не_над_проверкой() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"checklist.edit": "own"}), ROLE_SCOPES) == [
        "hq_staff: checklist.edit — охват «own» только у действий над проверкой"
    ]


def test_проверка_матрицы_называет_незнакомый_охват() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"mcp.connect": "some"}), ROLE_SCOPES) == [
        "hq_staff: mcp.connect — охват «some» не из own/all"
    ]


def test_проверка_матрицы_называет_код_не_из_каталога() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"inspection.delete": "all"}), ROLE_SCOPES) == [
        "hq_staff: inspection.delete — нет в каталоге действий"
    ]


def test_проверка_матрицы_называет_роль_без_охвата() -> None:
    assert validate_matrix({"ghost": {}}, ROLE_SCOPES) == ["ghost: у роли нет охвата"]


@pytest.mark.parametrize(
    ("старая", "пространство", "новая"),
    [
        ("admin", "HQ", "hq_admin"),
        ("auditor", "HQ", "hq_staff"),
        ("auditor", "default", "hq_staff"),
        ("admin", "GE", "country_admin"),
        ("auditor", "GE", "country_staff"),
        ("hq_staff", "HQ", "hq_staff"),
        ("country_auditor_plus", "GE", "country_auditor_plus"),
    ],
)
def test_старая_роль_переводится_по_пространству(
    старая: str, пространство: str, новая: str
) -> None:
    assert canonical_role(старая, пространство) == новая


def test_пустая_роль_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="роль"):
        canonical_role(" ", "HQ")
