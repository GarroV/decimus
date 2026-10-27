"""Ярусы страницы «Рейтинги» (D658): состав яруса в коде, порядок внутри — компоновка из базы."""

from __future__ import annotations

from src.ratings import layout as rl

# Раскладка боевой базы до D658: семь-восемь блоков одним списком, `clients` в ней нет.
СТАРАЯ_БАЗА = (
    ("scores", 0, True),
    ("compare", 1, True),
    ("aggregators", 2, True),
    ("violations", 3, True),
    ("top", 4, False),
    ("hard", 5, True),
    ("risk", 6, True),
    ("maps", 7, True),
)


def ключи(blocks: tuple[rl.Block, ...]) -> list[str]:
    return [b.key for b in blocks]


def test_блоки_по_умолчанию_идут_ярусами() -> None:
    assert ключи(rl.arrange(())) == [
        "scores",
        "violations",
        "top",
        "clients",
        "maps",
        "aggregators",
        "risk",
        "hard",
        "compare",
    ]


def test_старая_раскладка_из_базы_раскладывается_по_ярусам_и_новый_блок_виден() -> None:
    blocks = rl.arrange(СТАРАЯ_БАЗА)

    assert ключи(blocks) == [
        "scores",
        "violations",
        "top",  # порядок внутри яруса — из базы
        "aggregators",
        "risk",
        "maps",
        "clients",  # в базе его нет: в конце своего яруса, виден
        "compare",
        "hard",
    ]
    видимость = {b.key: b.visible for b in blocks}
    assert видимость["clients"] is True
    assert видимость["top"] is False  # скрытое контролингом остаётся скрытым


def test_незнакомый_код_из_базы_выпадает() -> None:
    assert "legacy" not in ключи(rl.arrange((*СТАРАЯ_БАЗА, ("legacy", 99, True))))


def test_блок_двигается_внутри_яруса() -> None:
    blocks = rl.arrange(())
    assert ключи(rl.moved(blocks, "risk", -1))[3:7] == ["clients", "maps", "risk", "aggregators"]


def test_блок_не_выходит_из_своего_яруса() -> None:
    blocks = rl.arrange(())
    assert rl.moved(blocks, "scores", -1) == blocks  # выше некуда
    assert rl.moved(blocks, "top", 1) == blocks  # ниже — уже другой ярус
    assert rl.moved(blocks, "clients", -1) == blocks
    assert rl.moved(blocks, "hard", -1) == blocks
