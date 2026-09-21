"""Разделы веб-админки и признак «построен / не построен» (D138).

**Признак живёт здесь, данными, а не разметкой на каждом экране.** Разметка
расходится с фактом молча: раздел допишут, ленту «в разработке» снять забудут —
и человек будет верить пустому экрану. Здесь же расхождение невозможно по
устройству: `check_registry` сверяет реестр с набором экранов, которые
приложение действительно зарегистрировало, и приложение просто не собирается,
если они разошлись (`SectionRegistryError`).

Состав и порядок разделов — из прототипа владельца (`Dodo Audit Prototype
v2.dc.html`, строки 3535–3540). Ключи оттуда же и остаются кодами: названия
переводятся и правятся, ключи — нет (конституция, принцип 5). Названия лежат в
`texts.py` под `section.<ключ>.title`.

Что не строится и почему — решениями, а не по вкусу: «Календарь» и планирование
проверок вне объёма (D139), самопроверка партнёра и кабинет партнёра рисуются,
но не строятся (D138).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .errors import SectionRegistryError


@dataclass(frozen=True)
class Section:
    """Раздел навигации.

    `key` — код раздела, он же имя ключа текста и часть адреса. `path` — адрес
    страницы: у построенного раздела он говорит о предмете (`/inspections`), у
    непостроенного совпадает с ключом, потому что говорить ещё не о чем.
    `built` — построен ли раздел НА САМОМ ДЕЛЕ; сверяется с экранами при сборке
    приложения.
    """

    key: str
    path: str
    built: bool
    #: Виден и открывается ТОЛЬКО администратору. Заслон стоит на самом
    #: экране, а признак здесь — чтобы навигация не звала человека туда, куда
    #: его не пустят: ссылка, ведущая в отказ, выглядит как поломка продукта.
    admin_only: bool = False


#: Девять разделов прототипа в порядке прототипа. Построены два — «Проверки»
#: (T319) и «Методика» (T320): объём спринта — базовая часть веб-версии
#: (D133), а не вся она.
SECTIONS: tuple[Section, ...] = (
    Section(key="overview", path="/overview", built=False),
    Section(key="registry", path="/inspections", built=True),
    Section(key="plans", path="/plans", built=False),
    Section(key="orders", path="/orders", built=False),
    Section(key="country", path="/country", built=False),
    Section(key="calendar", path="/calendar", built=False),
    Section(key="admin", path="/admin", built=True),
    Section(key="tenants", path="/tenants", built=False),
    # Люди проекта (T338, #322). В прототипе раздела нет: заведение учёток
    # жило в командной строке, и владелец попросил перенести его на экран.
    Section(key="users", path="/users", built=True, admin_only=True),
    Section(key="mini", path="/mini", built=False),
)


def section(key: str) -> Section:
    """Раздел по ключу. Нет такого — отказ, а не `None`."""
    for item in SECTIONS:
        if item.key == key:
            return item
    raise SectionRegistryError(f"Раздела «{key}» нет в реестре src/web/sections.py")


def built_keys() -> frozenset[str]:
    """Ключи разделов, помеченных построенными."""
    return frozenset(item.key for item in SECTIONS if item.built)


def check_registry(with_screens: Iterable[str]) -> None:
    """Сверить реестр с разделами, у которых есть настоящий экран.

    `with_screens` — ключи разделов, под которые приложение зарегистрировало
    собственные страницы. Любое расхождение — отказ:

    * помечен построенным, экрана нет — человек получит пустоту вместо честной
      ленты «в разработке»;
    * экран есть, помечен непостроенным — готовый раздел спрятан за заглушкой,
      и узнать об этом можно только случайно.

    Проверка стоит на сборке приложения, а не в тесте: тест ловит расхождение
    у того, кто прогнал тесты, а отказ на сборке — у всех.
    """
    screens = frozenset(with_screens)
    declared = built_keys()
    unknown = screens - {item.key for item in SECTIONS}
    if unknown:
        raise SectionRegistryError(
            f"Экраны есть у разделов, которых нет в реестре: {', '.join(sorted(unknown))}"
        )
    missing = declared - screens
    if missing:
        raise SectionRegistryError(
            f"Разделы помечены построенными, а экранов у них нет: {', '.join(sorted(missing))}. "
            f"Признак «построен» живёт в src/web/sections.py и обязан совпадать с фактом (D138)"
        )
    extra = screens - declared
    if extra:
        raise SectionRegistryError(
            f"У разделов есть экраны, а в реестре они помечены непостроенными: "
            f"{', '.join(sorted(extra))}. Снимите ленту «в разработке» в "
            f"src/web/sections.py (D138)"
        )


def visible_sections(account: object | None) -> tuple[Section, ...]:
    """Разделы, которые этому человеку показывать.

    Скрытие — не защита, и заменой заслону на экране это не является: адрес
    известен, и набрать его руками может кто угодно. Смысл ровно в том, чтобы
    не звать человека туда, куда его не пустят.
    """
    админ = getattr(account, "role", None) == "admin"
    return tuple(item for item in SECTIONS if админ or not item.admin_only)
