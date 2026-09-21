"""Справочник точек сети: загрузка с сайтов стран и заведение руками.

Две команды одной дверью, потому что дверь в базу у них одна
(`db.directory.upsert_unit`) и правило повторяемости тоже одно: та же точка не
создаёт вторую строку, а обновляет существующую.

    make units ARGS="sites --tenant default"
    make units ARGS="sites --tenant default --dry-run"
    make units ARGS="add 'Тбилиси-4' --country GE --city Tbilisi --tenant default"
    make units ARGS="list --tenant default --country GE"

**Откуда берутся точки в режиме `sites`.** С сайта самой страны: страница
контактов города перечисляет пиццерии, открытые гостю для заказа. Это НЕ
учётный источник — сеть числит больше точек, чем показывает витрина (сверено с
месячным отчётом Dodo Brands: 131 против 209 у DP IMF на август 2026).
Витрина годится, чтобы завести справочник и увидеть страны; когда появится
ключ Partner API (#312), учётный источник заменит её, и точки сойдутся по
`units.code`, а не по названию.

Поэтому же загрузка ничего не УДАЛЯЕТ. Точка, пропавшая с витрины, не
обязательно закрыта: её могли снять с доставки на день. Удалять справочник по
такому признаку значило бы стирать историю проверок точки из-за суточной
накладки.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from src.db.directory import list_units, upsert_unit
from src.db.errors import PushError

#: Сайты сети по странам. Код страны — ISO 3166-1 alpha-2, тот же, что ляжет в
#: `units.country`: связываем кодом, а не названием.
#:
#: Монголия стоит на `dodo-pizza.mn` с дефисом — на угаданном `dodopizza.mn`
#: обход молча терял страну целиком, пока домен не был проверен.
САЙТЫ: dict[str, tuple[str, str]] = {
    "AM": ("Армения", "dodopizza.am"),
    "AZ": ("Азербайджан", "dodopizza.az"),
    "BG": ("Болгария", "dodopizza.bg"),
    "BY": ("Беларусь", "dodopizza.by"),
    "CY": ("Кипр", "dodopizza.com.cy"),
    "EE": ("Эстония", "dodopizza.ee"),
    "ES": ("Испания", "dodopizza.es"),
    "GE": ("Грузия", "dodopizza.ge"),
    "HR": ("Хорватия", "dodopizza.hr"),
    "ID": ("Индонезия", "dodopizza.co.id"),
    "KG": ("Киргизия", "dodopizza.kg"),
    "LT": ("Литва", "dodopizza.lt"),
    "ME": ("Черногория", "dodopizza.me"),
    "MN": ("Монголия", "dodo-pizza.mn/en"),
    "NG": ("Нигерия", "dodopizza.ng"),
    "PL": ("Польша", "dodopizza.pl"),
    "QA": ("Катар", "dodopizza.qa"),
    "RO": ("Румыния", "dodopizza.ro"),
    "RS": ("Сербия", "dodopizza.rs"),
    "SI": ("Словения", "dodopizza.si"),
    "TJ": ("Таджикистан", "dodopizza.tj"),
    "TR": ("Турция", "dodopizza.com.tr"),
    "AE": ("ОАЭ", "dodopizza.ae"),
}

#: Разделы сайта, которые выглядят городом в адресе, но городом не являются.
#: Список здесь, а не «угадаем по длине»: угадывание тихо теряет короткие
#: названия городов и тихо заводит несуществующие.
НЕ_ГОРОДА = frozenset(
    {
        "about",
        "actions",
        "app",
        "bonus",
        "cart",
        "coins",
        "contacts",
        "delivery",
        "dodocoins",
        "en",
        "franchise",
        "legal",
        "login",
        "menu",
        "news",
        "profile",
        "restaurants",
        "ru",
        "search",
        "vacancies",
    }
)

ЗАГОЛОВКИ = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}

#: Признак карточки пиццерии на странице контактов. Один на точку — проверено
#: на городе с известным числом точек.
ТОЧКА = re.compile(r'class="contacts-pizzerias__title title">([^<]+)<')

ПАУЗА_СЕК = 0.2
ПОПЫТОК = 3


@dataclass(frozen=True)
class Точка:
    country: str
    city: str
    name: str


def _взять(адрес: str) -> str | None:
    """Страница или `None`. Отказ здесь обычен: сайт страны бывает недоступен."""
    for попытка in range(ПОПЫТОК):
        try:
            with urlopen(Request(адрес, headers=ЗАГОЛОВКИ), timeout=25) as ответ:  # noqa: S310
                сырое = ответ.read()
                if ответ.headers.get("Content-Encoding") == "gzip":
                    сырое = gzip.decompress(сырое)
                текст: str = сырое.decode("utf-8", "replace")
                return текст
        except (HTTPError, URLError, OSError):
            if попытка == ПОПЫТОК - 1:
                return None
            time.sleep(1.5)
    return None


def _города(домен: str) -> list[str]:
    """Города страны — с её же главной страницы.

    Свой список городов здесь был бы худшим из возможных решений: город,
    которого в нём нет, пропал бы из справочника молча, а проверить это
    нечем — числа-эталона у нас нет.
    """
    корень, _, префикс = домен.partition("/")
    путь = f"/{префикс}" if префикс else ""
    дом = _взять(f"https://{корень}{путь}/")
    if дом is None:
        return []
    найдено: list[str] = []
    for город in re.findall(rf'href="{re.escape(путь)}/([a-z0-9\-]+)"', дом):
        if город in НЕ_ГОРОДА or len(город) < 3 or город in найдено:
            continue
        найдено.append(город)
    return найдено


def _точки_города(домен: str, город: str) -> list[str]:
    корень, _, префикс = домен.partition("/")
    путь = f"/{префикс}" if префикс else ""
    стр = _взять(f"https://{корень}{путь}/{город}/contacts")
    if стр is None:
        return []
    тело = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", стр, flags=re.S | re.I)
    return [имя.strip() for имя in ТОЧКА.findall(тело) if имя.strip()]


def собрать_страну(код: str) -> tuple[str, list[Точка], str | None]:
    """Точки одной страны с её сайта. Третье значение — причина, если не вышло."""
    имя, домен = САЙТЫ[код]
    города = _города(домен)
    if not города:
        return имя, [], f"сайт {домен} не отдал ни одного города"
    собрано: list[Точка] = []
    видено: set[str] = set()
    for город in города:
        for точка in _точки_города(домен, город):
            if точка in видено:
                continue
            видено.add(точка)
            собрано.append(Точка(country=код, city=город, name=точка))
        time.sleep(ПАУЗА_СЕК)
    if not собрано:
        return имя, [], f"сайт {домен} отдал города, но ни одной точки"
    return имя, собрано, None


def _залить(точки: list[Точка], *, tenant: str) -> int:
    заведено = 0
    for т in точки:
        upsert_unit(т.name, country=т.country, city=т.city, tenant=tenant)
        заведено += 1
    return заведено


def команда_sites(args: argparse.Namespace) -> int:
    коды = [к.upper() for к in args.country] if args.country else sorted(САЙТЫ)
    неизвестные = [к for к in коды if к not in САЙТЫ]
    if неизвестные:
        print(f"Нет сайта для страны: {', '.join(неизвестные)}", file=sys.stderr)
        return 2

    все: list[Точка] = []
    отказы: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as пул:
        for имя, точки, причина in пул.map(собрать_страну, коды):
            if причина:
                отказы.append(f"{имя}: {причина}")
                print(f"{имя:15} — НЕ ВЫШЛО, {причина}")
                continue
            все.extend(точки)
            города = len({т.city for т in точки})
            print(f"{имя:15} {len(точки):>3} точек, городов {города}")

    print(f"\nСобрано точек: {len(все)} по {len({т.country for т in все})} странам")
    if args.dry_run:
        print("Режим проверки: в базу ничего не писалось")
    else:
        заведено = _залить(все, tenant=args.tenant)
        print(f"Заведено или обновлено в справочнике: {заведено}")

    if отказы:
        # Отказ печатается ОТДЕЛЬНО и в конце, а не тонет в общем списке:
        # страна, чей сайт не ответил, иначе выглядит страной без точек.
        print("\nСтраны, которые собрать не удалось (их точек в базе НЕТ):")
        for строка in отказы:
            print(f"  — {строка}")
    return 0


def команда_add(args: argparse.Namespace) -> int:
    код = upsert_unit(
        args.name,
        code=args.code,
        aliases=tuple(args.alias or ()),
        country=args.country,
        city=args.city,
        tenant=args.tenant,
    )
    print(f"Точка «{args.name}» заведена или обновлена: {код}")
    return 0


def команда_list(args: argparse.Namespace) -> int:
    точки = list_units(tenant=args.tenant, country=args.country)
    if not точки:
        куда = f" в стране {args.country.upper()}" if args.country else ""
        print(f"Справочник арендатора {args.tenant}{куда} пуст")
        return 0
    for т in точки:
        где = " / ".join(x for x in (т.country, т.city) if x) or "география не задана"
        синонимы = f"  синонимы: {', '.join(т.aliases)}" if т.aliases else ""
        print(f"{т.name:28} {где}{синонимы}")
    страны = {т.country for т in точки if т.country}
    print(f"\nВсего точек: {len(точки)}, стран: {len(страны)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    парсер = argparse.ArgumentParser(description="Справочник точек сети")
    под = парсер.add_subparsers(dest="команда", required=True)

    s = под.add_parser("sites", help="загрузить точки с сайтов стран")
    s.add_argument("--country", action="append", help="код страны; можно несколько")
    s.add_argument("--tenant", default="default")
    s.add_argument("--dry-run", action="store_true", help="показать и не писать")
    s.set_defaults(функция=команда_sites)

    a = под.add_parser("add", help="завести точку руками")
    a.add_argument("name")
    a.add_argument("--country", help="код страны ISO, например GE")
    a.add_argument("--city")
    a.add_argument("--code", help="код точки во внешнем источнике")
    a.add_argument("--alias", action="append", help="синоним; можно несколько")
    a.add_argument("--tenant", default="default")
    a.set_defaults(функция=команда_add)

    ls = под.add_parser("list", help="показать справочник")
    ls.add_argument("--country", help="показать одну страну")
    ls.add_argument("--tenant", default="default")
    ls.set_defaults(функция=команда_list)

    args = парсер.parse_args(argv)
    try:
        результат: int = args.функция(args)
    except PushError as отказ:
        print(f"Справочник: {отказ}", file=sys.stderr)
        return 1
    return результат


if __name__ == "__main__":
    raise SystemExit(main())
