"""Справочник точек сети: загрузка с сайтов стран и заведение руками.

Две команды одной дверью, потому что дверь в базу у них одна
(`db.directory.upsert_unit`) и правило повторяемости тоже одно: та же точка не
создаёт вторую строку, а обновляет существующую.

    make units ARGS="ratings"                 # основной путь (D556): точки из РС и РКО
    make units ARGS="ratings --country TJ --dry-run"
    make units ARGS="sites --tenant default"
    make units ARGS="sites --tenant default --dry-run"
    make units ARGS="add 'Тбилиси-4' --country GE --city Tbilisi --tenant default"
    make units ARGS="list --tenant default --country GE"

**Откуда берутся точки в режиме `sites`.** С сайта самой страны: страница
контактов города несёт JSON-данные пиццерий, открытых гостю для заказа: код Dodo,
имя на сайте, улица. Точка находит свою строку справочника пиццерий по коду Dodo и
заводится под ЕЁ латинским именем (D538); имя с сайта и улица — синонимы. Страница без
данных или недоступный город — громкий отказ (код выхода 1), а не пустой город. Это НЕ
учётный источник — сеть числит больше точек, чем показывает витрина (сверено с
месячным отчётом Dodo Brands: 131 против 209 у DP IMF на август 2026).
Учётный источник — рейтинги РС и РКО (D556): режим `ratings` и бот после
каждого забора таблицы контроля (`src/ratings/directory_feed.py`). Витрина
осталась запасной дверью; четыре сайта (BY, HR, KG, TJ) городов не отдают (#981).

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
from src.db.errors import PushError, RatingsError
from src.db.reach import reach_of
from src.db.unit_profiles import by_country
from src.domain.unit_match import Ref
from src.ratings import directory_feed
from src.ratings.directory_feed import put_unit

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
    "KG": ("Кыргызстан", "dodopizza.kg"),
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

#: Пиццерия в данных страницы контактов (JSON внутри страницы): код Dodo, город, имя на
#: сайте («Bucharest-1») и улица (`alias`). Старый признак — вёрстка `contacts-pizzerias__title` —
#: с 2026-10 страница не отдаёт: карточки рисуются скриптом. Код Dodo в объекте — тот же, что
#: `unit_profiles.dodo_id`, поэтому имя угадывать не нужно.
ТОЧКА = re.compile(
    r'"id":"(?P<id>[0-9a-f]{32})","localityId":"[^"]*","name":"(?P<name>(?:[^"\\]|\\.)*)"'
    r'(?:,"alias":"(?P<alias>(?:[^"\\]|\\.)*)")?'
)
#: Признак того, что страница вообще несёт данные пиццерий (даже если в городе их ноль).
ПРИЗНАК_ДАННЫХ = '"localityId"'
#: Длиннее — не улица, а юридический текст (на сайте Румынии в `alias` лежит номер разрешения).
ПРЕДЕЛ_СИНОНИМА = 120

ПАУЗА_СЕК = 0.2
ПОПЫТОК = 3


@dataclass(frozen=True)
class Точка:
    country: str
    city: str
    #: Имя с сайта — не имя точки: именем служит строка справочника пиццерий с этим кодом.
    name: str
    #: Код Dodo с сайта — по нему точка находит свою строку справочника.
    dodo_id: str
    #: Улица или адрес с сайта; ляжет синонимом.
    alias: str = ""


class СайтОтказал(RuntimeError):
    """Страница города не дала данных. Молчаливый ноль здесь — потерянный город (D538)."""


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


def разобрать_точки(страница: str, *, страна: str, город: str) -> list[Точка]:
    """Пиццерии со страницы контактов по JSON-данным: код Dodo, имя и улица.

    Ноль найденных при отсутствии самого признака данных — не «в городе нет пиццерий», а
    «сайт изменил страницу»: отказ, а не пустой результат.
    """
    найдено: dict[str, Точка] = {}
    for m in ТОЧКА.finditer(страница):
        улица = " ".join(m["alias"].split()) if m["alias"] else ""
        найдено.setdefault(
            m["id"],
            Точка(
                страна,
                город,
                m["name"].strip(),
                m["id"],
                улица if len(улица) <= ПРЕДЕЛ_СИНОНИМА else "",
            ),
        )
    if not найдено and ПРИЗНАК_ДАННЫХ not in страница:
        raise СайтОтказал(f"{город}: в странице нет данных пиццерий (признак {ПРИЗНАК_ДАННЫХ})")
    return list(найдено.values())


def _точки_города(домен: str, страна: str, город: str) -> list[Точка]:
    корень, _, префикс = домен.partition("/")
    путь = f"/{префикс}" if префикс else ""
    стр = _взять(f"https://{корень}{путь}/{город}/contacts")
    if стр is None:
        raise СайтОтказал(f"{город}: страница контактов не открылась")
    return разобрать_точки(стр, страна=страна, город=город)


def собрать_страну(код: str) -> tuple[str, list[Точка], str | None]:
    """Точки одной страны с её сайта. Третье значение — что не вышло (точки при этом отдаются)."""
    имя, домен = САЙТЫ[код]
    города = _города(домен)
    if not города:
        return имя, [], f"сайт {домен} не отдал ни одного города"
    собрано: list[Точка] = []
    видено: set[str] = set()
    сбои: list[str] = []
    for город in города:
        try:
            страница = _точки_города(домен, код, город)
        except СайтОтказал as сбой:
            сбои.append(str(сбой))
            continue
        for точка in страница:
            if точка.dodo_id not in видено:
                видено.add(точка.dodo_id)
                собрано.append(точка)
        time.sleep(ПАУЗА_СЕК)
    if сбои:
        return (
            имя,
            собрано,
            f"{len(сбои)} из {len(города)} городов не прочитаны: " + "; ".join(сбои),
        )
    if not собрано:
        return имя, [], f"сайт {домен} отдал города, но ни одной точки"
    return имя, собрано, None


def _эталоны(страна: str) -> dict[str, Ref]:
    """Справочник пиццерий страны по коду Dodo; пусто, если свод не загружен."""
    try:
        профили = by_country(страна)
    except RatingsError:
        return {}
    return {
        p.dodo_id: Ref(p.country_code, p.name, p.dodo_id, p.city, p.address)
        for p in профили
        if p.dodo_id
    }


def _залить(точки: list[Точка], *, tenant: str) -> tuple[int, list[str]]:
    """Точка сайта находит строку справочника пиццерий по коду Dodo (D538).

    Точка заводится или находится под ЛАТИНСКИМ именем справочника и с его кодом; имя с
    сайта и улица — синонимы. Кода нет в справочнике — точка не заводится, а попадает в
    список «не в своде»: имя по сайту не угадывается. Возвращает (записано, не в своде).
    """
    заведено = 0
    не_в_своде: list[str] = []
    эталоны: dict[str, dict[str, Ref]] = {}
    for т in точки:
        ref = эталоны.setdefault(т.country, _эталоны(т.country)).get(т.dodo_id)
        if ref is None:
            не_в_своде.append(f"{т.country} {т.name} ({т.dodo_id})")
            continue
        синонимы = tuple(x for x in (т.name, т.alias) if x and x != ref.clean_name)
        отказ = put_unit(
            ref.clean_name, code=т.dodo_id, aliases=синонимы,
            country=т.country, city=т.city, tenant=tenant,
        )  # fmt: skip
        if отказ:
            не_в_своде.append(отказ)
            continue
        заведено += 1
    return заведено, не_в_своде


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
            все.extend(точки)
            if причина:
                отказы.append(f"{имя}: {причина}")
                print(f"{имя:15} — НЕ ВЫШЛО, {причина} (прочитано точек: {len(точки)})")
                continue
            города = len({т.city for т in точки})
            print(f"{имя:15} {len(точки):>3} точек, городов {города}")

    print(f"\nСобрано точек: {len(все)} по {len({т.country for т in все})} странам")
    if args.dry_run:
        print("Режим проверки: в базу ничего не писалось")
    else:
        заведено, не_в_своде = _залить(все, tenant=args.tenant)
        print(f"Заведено или обновлено в справочнике: {заведено}")
        if не_в_своде:
            print(
                f"Не заведено — кода нет в справочнике пиццерий или имя занято ({len(не_в_своде)}):"
            )
            for строка in не_в_своде:
                print(f"  — {строка}")

    if отказы:
        # Отказ печатается ОТДЕЛЬНО и в конце, а не тонет в общем списке:
        # страна, чей сайт не ответил, иначе выглядит страной без точек.
        print("\nСтраны и города, которые прочитать не удалось (их точек в базе может не быть):")
        for строка in отказы:
            print(f"  — {строка}")
        return 1
    return 0


def команда_ratings(args: argparse.Namespace) -> int:
    """Справочник из рейтингов РС и РКО — учётного источника живых пиццерий (D556)."""
    try:
        итог = directory_feed.sync(
            countries=args.country or (), tenant=args.tenant, dry_run=args.dry_run
        )
    except (PushError, RatingsError) as exc:
        print(f"Не вышло: {exc}", file=sys.stderr)
        return 1
    print(f"Живых точек в рейтингах: {итог.seen}; заведено или обновлено: {итог.put}")
    for строка in итог.skipped:
        print(f"  пропущено — {строка}")
    if args.dry_run:
        print("Режим проверки: в базу ничего не писалось")
    return 1 if итог.skipped else 0


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
    точки = list_units(reach=reach_of(args.tenant), country=args.country)
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
    s.add_argument("--tenant", default="HQ")
    s.add_argument("--dry-run", action="store_true", help="показать и не писать")
    s.set_defaults(функция=команда_sites)

    r = под.add_parser("ratings", help="завести живые точки из рейтингов РС и РКО (D556)")
    r.add_argument("--country", action="append", help="код страны; можно несколько")
    r.add_argument("--tenant", default="HQ")
    r.add_argument("--dry-run", action="store_true", help="показать и не писать")
    r.set_defaults(функция=команда_ratings)

    a = под.add_parser("add", help="завести точку руками")
    a.add_argument("name")
    a.add_argument("--country", help="код страны ISO, например GE")
    a.add_argument("--city")
    a.add_argument("--code", help="код точки во внешнем источнике")
    a.add_argument("--alias", action="append", help="синоним; можно несколько")
    a.add_argument("--tenant", default="HQ")
    a.set_defaults(функция=команда_add)

    ls = под.add_parser("list", help="показать справочник")
    ls.add_argument("--country", help="показать одну страну")
    ls.add_argument("--tenant", default="HQ")
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
