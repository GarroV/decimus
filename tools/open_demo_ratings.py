"""Рейтинги открытого демо (D524): РС и РКО пиццерий демо-сети — тем же импортёром, что у продукта.

Пиццерии рейтингов названы как точки проверок (`Northgate-1` …), поэтому «Рейтинги»,
блок рейтингов «Главной» и колонки РС/РКО таблицы пиццерий сходятся с проверками.
Периоды — полумесяцы, последние `HALVES` до сегодняшнего включительно: срез
«текущий квартал» не пуст в любой день. База стенда перед посевом пустая
(`deploy/demo/reset.sh`), поэтому прежнее здесь не ищется.

Снимок и выгрузка РКО — синтетические, по форме Dodo IS (`docs/15-ratings.md`).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import date, timedelta

from src.db.ratings_read import REFUSED_RULE, RatingsEditError, add_hard_rule, set_developer
from src.ratings.importer import CHANNEL_SEED, import_file

#: Общее начало id демо-строк рейтингов, как у `tools/seed_ratings_demo.py`.
PREFIX = "de00"
#: Сколько полумесяцев истории — около трёх месяцев.
HALVES = 6
#: Страны демо: id в снимке, название (по нему импортёр узнаёт код) и девелопер.
COUNTRIES = {
    "RS": (9101, "Serbia", "Marco Bianchi"),
    "GE": (9102, "Georgia", "Nina Petrosyan"),
    "AM": (9103, "Armenia", "Nina Petrosyan"),
}
#: Регион IMF в снимке (`snapshot.IMF_REGION`): страны вне него импортёр не берёт.
IMF_REGION = 2
_RS, _RKO = 2, 1
#: Баллы по полумесяцам, от старого к свежему: у каждой точки свой характер —
#: ровная отличница, растущая, проседающая, неровная.
RS_SCORES = {
    "Northgate-1": (93, 94, 95, 94, 96, 97),
    "Northgate-2": (88, 86, 84, 85, 82, 83),
    "Riverside-1": (78, 81, 84, 86, 88, 90),
    "Hillcrest-1": (97, 98, 97, 99, 98, 99),
    "Harbor Bay-1": (90, 87, 91, 88, 92, 89),
    "Old Town-1": (85, 86, 88, 87, 89, 91),
    "Lakeside-1": (82, 80, 79, 77, 80, 78),
    "Westfield-1": (91, 92, 90, 93, 94, 95),
}
RKO_SCORES = {
    "Northgate-1": (95, 96, 94, 97, 96, 98),
    "Northgate-2": (86, 84, 87, 83, 85, 84),
    "Riverside-1": (80, 82, 85, 84, 87, 89),
    "Hillcrest-1": (96, 97, 98, 97, 99, 98),
    "Harbor Bay-1": (88, 90, 86, 89, 91, 90),
    "Old Town-1": (84, 87, 86, 89, 88, 90),
    "Lakeside-1": (81, 79, 80, 76, 78, 77),
    "Westfield-1": (92, 91, 93, 94, 93, 96),
}
#: Замечания РС: название, класс. Точке достаются по её номеру — у слабых больше.
REMARKS = (
    ("Oven conveyor not cleaned after the shift", "D1"),
    ("Opened sauce without an opening date", "D1"),
    ("Hand-wash station without paper towels", "D1"),
    ("Floor in the dining area not cleaned at opening", "D1"),
    ("Raw product stored above ready-to-eat toppings", "D2"),
)
#: Тяжёлое замечание РС — класс D3 (хард-правило `rs contains D3` из миграции 0039 берёт его
#: по родителю). Лежит в последних периодах у слабых точек: блок «Тяжёлые нарушения»
#: за текущий период не пуст.
HARD_REMARK = "Rodent droppings found in the dry storage area"
HARD_REMARK_UNITS = {"Lakeside-1": 1, "Northgate-2": 1}  # в скольких последних периодах
#: Тяжёлое замечание РКО и правило, которое его берёт (правила миграции 0039 русские).
HARD_RKO_TEXT = "Pizza was delivered cold"
HARD_RKO_ORDERS = {("Lakeside-1", 0), ("Northgate-2", 0), ("Harbor Bay-1", 1)}
#: Что контролёр РКО написал о заказе.
RKO_TEXTS = (
    "Toppings on the crust",
    "Uneven topping spread",
    "Burnt crust edge",
    "Pizza arrived lukewarm",
)


def _hex(n: int) -> str:
    return f"{PREFIX}{n:028x}"


def halves(today: date, count: int = HALVES) -> list[tuple[date, date]]:
    """Последние `count` полумесяцев до сегодняшнего включительно, от старого к свежему."""
    begin = today.replace(day=1 if today.day <= 15 else 16)
    found: list[tuple[date, date]] = []
    for _ in range(count):
        if begin.day == 1:
            end = begin.replace(day=15)
            previous = (begin - timedelta(days=1)).replace(day=16)
        else:
            end = (begin.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            previous = begin.replace(day=1)
        found.append((begin, end))
        begin = previous
    return found[::-1]


def _units(units: Sequence[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """(dodo_id, имя, страна) — id по порядку точек, стабильно между посевами."""
    return [(_hex(n), name, country) for n, (name, country) in enumerate(units, start=1)]


def unit_ids(units: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Код Dodo каждой точки демо по имени: те же, что в снимке рейтингов, — по ним
    связываются оценки площадок (`open_demo_reviews`) и сведения о партнёрах."""
    return {name: dodo_id for dodo_id, name, _ in _units(units)}


def snapshot(units: Sequence[tuple[str, str]], today: date) -> bytes:
    """Снимок рейтинга: история РС и РКО по полумесяцам и замечания РС."""
    periods = halves(today)
    docs = []
    for n, (dodo_id, name, country) in enumerate(_units(units), start=1):
        history = []
        remarks = []
        for kind, scores in ((_RS, RS_SCORES), (_RKO, RKO_SCORES)):
            for i, (begin, end) in enumerate(periods):
                period_id = _hex(1000 * kind + i)
                history.append(
                    {
                        "score": scores[name][i],
                        "status": "1",
                        "period": {
                            "id": period_id,
                            "rating_type": kind,
                            "begin": begin.isoformat(),
                            "end": end.isoformat(),
                            "alias": f"Standards {begin.isoformat()}",
                            "alias_en": f"Standards {begin.isoformat()}",
                        },
                    }
                )
                if kind != _RS:
                    continue
                weak = 100 - scores[name][i]
                items = [
                    {
                        "criterion_id": str(k + 1),
                        "name": text,
                        "parent": level,
                        "amount": 1 + (n + i + k) % 2,
                    }
                    for k, (text, level) in enumerate(REMARKS)
                    if (n + i + k) % 4 < 1 + weak // 6
                ]
                if i >= len(periods) - HARD_REMARK_UNITS.get(name, 0):
                    items.append(
                        {
                            "criterion_id": str(len(REMARKS) + 1),
                            "name": HARD_REMARK,
                            "parent": "D3",
                            "amount": 1,
                        }
                    )
                remarks.append(
                    {
                        "period_id": period_id,
                        "checkups": 2,
                        "items": items,
                    }
                )
        docs.append(
            {
                "dodo_id": dodo_id,
                "name": name,
                "country_id": COUNTRIES[country][0],
                "history": history,
                "remarks": remarks,
            }
        )
    doc = {
        "version": 1,
        "taken_at": f"{today.isoformat()}T00:00:00Z",
        "chunk": {"index": 1, "of": 1},
        "countries": [
            {"id": cid, "name": title, "region": IMF_REGION} for cid, title, _ in COUNTRIES.values()
        ],
        "units": docs,
    }
    return json.dumps(doc).encode()


def rko_violations(units: Sequence[tuple[str, str]], today: date) -> bytes:
    """Выгрузка нарушений РКО: по четыре заказа на точку за последние недели."""
    header = [
        "Страна", "Пиццерия", "Пользователь", "Выявленные нарушения", "Ответы клиента",
        "Другие проблемы", "Номер заказа", "Дата заказа", "Название пиццы",
        "Размер и тип теста", "Link", "KnowledgeBaseLink", "CreatedAtUtc", "CheckupType",
    ]  # fmt: skip
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for n, (dodo_id, name, country) in enumerate(_units(units), start=1):
        for k in range(4):
            checkup = _hex(5000 + n * 10 + k)
            day = today - timedelta(days=3 + 5 * k + n % 3)
            texts = list(RKO_TEXTS[: (n + k) % 3])
            if (name, k) in HARD_RKO_ORDERS:
                texts.append(HARD_RKO_TEXT)
            writer.writerow(
                [
                    COUNTRIES[country][1], name, "", "; ".join(texts), "", "",
                    str(1000 + n * 10 + k), f"{day.isoformat()} 12:00:00", "Pepperoni", "30 cm",
                    f"https://control.dodois.io/backoffice/checkups/{checkup}",
                    f"https://dodopizza.info/rating#/{dodo_id}/1?checkupId={checkup}",
                    "", "Доставка" if k % 2 else "Ресторан",
                ]
            )  # fmt: skip
    return b"\xef\xbb\xbf" + out.getvalue().encode()


def seed(units: Sequence[tuple[str, str]], today: date) -> list[str]:
    """Загрузить снимок и выгрузку РКО, раздать странам девелоперов. Возвращает строки отчёта."""
    lines = []
    for file_name, data in (
        ("demo-snapshot.json", snapshot(units, today)),
        ("demo-rko-violations.csv", rko_violations(units, today)),
    ):
        report = import_file(
            data,
            kind=None,
            channel=CHANNEL_SEED,
            actor="demo-seed",
            file_name=file_name,
            today=today,
            source="demo",
        )
        # Несопоставленная строка — молча пустая колонка у точки, поэтому отказ.
        if report.outcome != "loaded" or report.unmatched or report.issues:
            raise RuntimeError(
                f"рейтинги демо не легли чисто: {file_name} — {report.outcome}, "
                f"несопоставлено {report.unmatched}, в журнале {report.issues}"
            )
        lines.append(f"{file_name}: +{report.accepted} ~{report.updated}")
    try:
        add_hard_rule("rko", "text", HARD_RKO_TEXT, actor="demo-seed")
    except RatingsEditError as exc:
        if exc.code != REFUSED_RULE:  # «уже лежит» — посев повторяется на той же базе
            raise
    for code, (_, _, developer) in COUNTRIES.items():
        if not set_developer(code, developer, actor="demo-seed"):
            raise RuntimeError(f"девелопер страны {code} не записан")
    return lines
