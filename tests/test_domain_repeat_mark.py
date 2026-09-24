"""#359: пометка повтора проходит через контракт домена, а не только через CLI.

Бот и веб ходят к движку через домен, и если пометка остановится здесь, то в
живом продукте её не поставить — а на папочных проверках она будет работать.
Такой разрыв не виден снаружи: обе ветки считают без ошибок, просто одна не
умеет то, что требует методика.
"""

from __future__ import annotations

from pathlib import Path

from conftest import requires_data

from src.domain import add_finding, edit_finding, get_state, start_inspection

pytestmark = requires_data

CHAT = 5151


def начата() -> None:
    start_inspection(CHAT, unit="Белград-1", kind="planned", report_lang="ru")


def запись(n: int = 1):
    состояние = get_state(CHAT)
    assert состояние is not None
    найдена = состояние.finding(n)
    assert найдена is not None
    return найдена


def test_повтор_фиксируется_при_записи(domain_env: Path) -> None:
    начата()

    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "нагар", repeat=True)

    assert запись().repeat is True


def test_обычная_запись_повтором_не_становится(domain_env: Path) -> None:
    начата()

    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "нагар")

    assert запись().repeat is False


def test_пометка_ставится_правкой_записанного(domain_env: Path) -> None:
    # Подсказка о повторе приходит после фиксации: система сверяется с
    # историей точки, когда уже знает пункт. Значит пометка обязана ставиться
    # отдельным решением, а не только в момент записи.
    начата()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "нагар")

    edit_finding(CHAT, 1, repeat=True)

    assert запись().repeat is True


def test_пометка_снимается(domain_env: Path) -> None:
    начата()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "нагар", repeat=True)

    edit_finding(CHAT, 1, repeat=False)

    assert запись().repeat is False


def test_правка_формулировки_пометку_не_снимает(domain_env: Path) -> None:
    начата()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "нагар", repeat=True)

    edit_finding(CHAT, 1, text="другая формулировка")

    assert запись().repeat is True
