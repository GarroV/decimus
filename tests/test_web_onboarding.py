"""«Начало работы» (D756, D759 п.6) — ядро: какие шаги у роли и что из них сделано.

Шаги говорят человеку, что делать самому, а что ждёт управляющую компанию: страны,
пиццерии и чек-лист партнёр завести не может. «Не знаю» (база молчит) шаг не
показывает и «сделано» не считает: напоминать по непрочитанному — ложь.
"""

from __future__ import annotations

from src.web import onboarding as ob

ВСЁ_НЕТ = ob.Facts(
    bot_bound=False,
    claude_connected=False,
    people_added=False,
    first_inspection=False,
    space=ob.SpaceFacts(countries=False, units=False, checklist=False),
)
ВСЁ_ЕСТЬ = ob.Facts(
    bot_bound=True,
    claude_connected=True,
    people_added=True,
    first_inspection=True,
    space=ob.SpaceFacts(countries=True, units=True, checklist=True),
)


def ключи(steps: tuple[ob.Step, ...]) -> list[str]:
    return [s.key for s in steps]


def состояния(steps: tuple[ob.Step, ...]) -> dict[str, str]:
    return {s.key: s.state for s in steps}


def test_у_ук_шагов_нет_ни_у_одной_роли() -> None:
    for роль in ("superadmin", "admin", "developer", "control", "osb", "guest"):
        assert ob.steps_for(роль, "HQ", ВСЁ_НЕТ, bot_available=True) == ()


def test_админ_партнёра_шаги_в_порядке_работы() -> None:
    steps = ob.steps_for("admin", "ARMENIA", ВСЁ_НЕТ, bot_available=True)

    assert ключи(steps) == [
        ob.BOT,
        ob.PEOPLE,
        ob.COUNTRIES,
        ob.UNITS,
        ob.CHECKLIST,
        ob.INSPECTION,
        ob.CLAUDE,
    ]


def test_страны_пиццерии_и_чеклист_ждут_ук_а_не_партнёра() -> None:
    steps = ob.steps_for("admin", "ARMENIA", ВСЁ_НЕТ, bot_available=True)

    assert состояния(steps) == {
        ob.BOT: ob.TODO,
        ob.PEOPLE: ob.TODO,
        ob.COUNTRIES: ob.WAITING,
        ob.UNITS: ob.WAITING,
        ob.CHECKLIST: ob.WAITING,
        ob.INSPECTION: ob.TODO,
        ob.CLAUDE: ob.TODO,
    }


def test_проверяющий_без_шагов_админа() -> None:
    steps = ob.steps_for("auditor", "ARMENIA", ВСЁ_НЕТ, bot_available=True)

    assert ключи(steps) == [ob.BOT, ob.COUNTRIES, ob.UNITS, ob.CHECKLIST, ob.INSPECTION, ob.CLAUDE]
    assert ob.PEOPLE not in ключи(steps)


def test_бот_не_настроен_на_площадке_шага_бота_нет() -> None:
    steps = ob.steps_for("auditor", "ARMENIA", ВСЁ_НЕТ, bot_available=False)

    assert ob.BOT not in ключи(steps)


def test_всё_сделано_карточка_не_нужна() -> None:
    steps = ob.steps_for("admin", "ARMENIA", ВСЁ_ЕСТЬ, bot_available=True)

    assert all(s.state == ob.DONE for s in steps)
    assert ob.needs_attention(steps) is False


def test_клод_необязателен_карточку_не_держит() -> None:
    facts = ob.Facts(
        bot_bound=True,
        claude_connected=False,
        people_added=True,
        first_inspection=True,
        space=ВСЁ_ЕСТЬ.space,
    )
    steps = ob.steps_for("admin", "ARMENIA", facts, bot_available=True)

    assert состояния(steps)[ob.CLAUDE] == ob.TODO
    assert ob.needs_attention(steps) is False


def test_обязательный_шаг_не_сделан_карточка_нужна() -> None:
    for поле in ("bot_bound", "people_added", "first_inspection"):
        facts = ob.Facts(**{**ВСЁ_ЕСТЬ.__dict__, поле: False})
        steps = ob.steps_for("admin", "ARMENIA", facts, bot_available=True)

        assert ob.needs_attention(steps) is True, поле


def test_ожидание_ук_тоже_держит_карточку() -> None:
    facts = ob.Facts(**{**ВСЁ_ЕСТЬ.__dict__, "space": ob.SpaceFacts(True, False, True)})
    steps = ob.steps_for("admin", "ARMENIA", facts, bot_available=True)

    assert состояния(steps)[ob.UNITS] == ob.WAITING
    assert ob.needs_attention(steps) is True


def test_непрочитанное_не_показывается_и_не_считается_сделанным() -> None:
    facts = ob.Facts(
        bot_bound=None,
        claude_connected=None,
        people_added=True,
        first_inspection=True,
        space=ob.SpaceFacts(countries=True, units=None, checklist=True),
    )
    steps = ob.steps_for("admin", "ARMENIA", facts, bot_available=True)

    assert ob.BOT not in ключи(steps)
    assert ob.UNITS not in ключи(steps)
    assert ob.CLAUDE not in ключи(steps)
    # Всё прочитанное сделано, а непрочитанного карточка не знает — не нужна.
    assert ob.needs_attention(steps) is False


def test_готовность_пространства_одна_на_партнёра_и_на_ук() -> None:
    """Строки «ждёт УК» у партнёра и «есть / нет» в карточке пространства у УК — одна функция."""
    space = ob.SpaceFacts(countries=True, units=False, checklist=None)
    строки = ob.space_rows(space)
    у_партнёра = [
        s
        for s in ob.steps_for(
            "admin", "ARMENIA", ob.Facts(**{**ВСЁ_НЕТ.__dict__, "space": space}), bot_available=True
        )
        if s.key in (ob.COUNTRIES, ob.UNITS, ob.CHECKLIST)
    ]

    assert [(s.key, s.state) for s in строки] == [
        (ob.COUNTRIES, ob.DONE),
        (ob.UNITS, ob.WAITING),
        (ob.CHECKLIST, ob.UNKNOWN),
    ]
    # Непрочитанная строка у УК остаётся строкой «не прочиталось», у партнёра её нет.
    assert [(s.key, s.state) for s in у_партнёра] == [
        (ob.COUNTRIES, ob.DONE),
        (ob.UNITS, ob.WAITING),
    ]


def test_пространство_готово_только_когда_три_строки_есть() -> None:
    assert ob.space_ready(ob.SpaceFacts(True, True, True)) is True
    assert ob.space_ready(ob.SpaceFacts(True, True, False)) is False
    assert ob.space_ready(ob.SpaceFacts(True, True, None)) is False


def test_админ_партнёра_без_пространства_ук_не_сбивает_порядок_у_смешанного_пространства() -> None:
    # Партнёрская роль в пространстве УК невозможна, но сторона решается по пространству, а не роли.
    assert ob.steps_for("admin", "default", ВСЁ_НЕТ, bot_available=True) == ()
    assert ob.steps_for("admin", "", ВСЁ_НЕТ, bot_available=True) == ()
