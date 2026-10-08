"""Демо-рейтинги для веб-админки (`make web-demo`): английский, вымышленные пиццерии.

Тем же импортёром, что у продукта (`src.ratings.importer`), из синтетического
снимка и выгрузки РКО, собранных здесь же. Повторный запуск возвращает демо к
чистому виду: прежние демо-строки (`dodo_id` с префиксом `de00`) удаляются, потом
грузятся заново. Обходной путь демо: `wipe` переводит прежние `loaded` сида в
`failed`, чтобы тот же файл (sha256) снова лёг — индекс `imports_loaded_once`
иначе вернул бы `duplicate`. В неместную базу не пишет — тем же правилом, что
`tools/seed_web_demo.py` (`SEED_WEB_DEMO_FORCE=1` снимает).

На тестовую базу стенда приёмки не грузить (P23): демо-страны — настоящие коды
IMF, и «Demo City» попали бы в средние Сербии, Словении и Болгарии. Убрать демо:
`wipe` (функция ниже) или `select count(*) from ratings.units where dodo_id like
'de00%'` должно быть 0.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

load_dotenv(REPO_ROOT / ".env")

import psycopg  # noqa: E402
import seed_web_demo  # noqa: E402 -- путь к репозиторию выставляется выше

from src.db.config import check_environment  # noqa: E402
from src.ratings.importer import CHANNEL_SEED, import_file  # noqa: E402

DEMO_PREFIX = "de00"
DEVELOPER = "Alex Demo"
UNITS = [
    (f"{DEMO_PREFIX}{n:028x}", f"Demo City-{n}", code)
    for n, code in ((1, "RS"), (2, "RS"), (3, "SI"), (4, "SI"), (5, "BG"), (6, "BG"))
]
COUNTRY_IDS = {"RS": 9001, "SI": 9002, "BG": 9003}
NAMES = {"RS": "Serbia", "SI": "Slovenia", "BG": "Bulgaria"}
RS_PERIODS = [
    ("2026-07-01", "2026-07-15"),
    ("2026-07-16", "2026-07-31"),
    ("2026-08-01", "2026-08-15"),
    ("2026-08-16", "2026-08-31"),
    ("2026-09-01", "2026-09-15"),
    ("2026-09-16", "2026-09-30"),
]
SCORES = {
    1: [96, 97, 95, 98, 97, 99],
    2: [84, 80, 82, 79, 83, 81],
    3: [90, 91, 92, 93, 94, 95],
    4: [70, 75, 72, 74, 71, 73],
    5: [88, 86, 85, 90, 87, 89],
    6: [95, 93, 94, 92, 96, 97],
}
REMARKS = [
    "Dirty floor in the prep zone",
    "Expired label on dough",
    "Hand wash station not stocked",
    "Level D3: raw product stored above ready product",
]
VIOLATION_TEXTS = [
    "Toppings on the crust",
    "Uneven topping spread",
    "Burnt crust",
    "Cold pizza on delivery",
]


def _pid(n: int) -> str:
    return f"{DEMO_PREFIX}{(1000 + n):028x}"


def snapshot() -> bytes:
    units = []
    for n, (dodo_id, name, code) in enumerate(UNITS, start=1):
        history = [
            {
                "score": SCORES[n][i],
                "status": "1",
                "period": {
                    "id": _pid(i),
                    "rating_type": 2,
                    "begin": b,
                    "end": e,
                    "alias": f"Standards {b}",
                    "alias_en": f"Standards {b}",
                },
            }
            for i, (b, e) in enumerate(RS_PERIODS)
        ]
        remarks = [
            {
                "period_id": _pid(i),
                "checkups": 2,
                "items": [
                    {
                        "criterion_id": str(k),
                        "name": REMARKS[k],
                        "parent": "D3" if k == 3 else "D1",
                        "amount": 1 + (n + i + k) % 2,
                    }
                    for k in range(len(REMARKS))
                    if (n + k) % 3
                ],
            }
            for i in range(len(RS_PERIODS))
        ]
        units.append(
            {
                "dodo_id": dodo_id,
                "name": name,
                "country_id": COUNTRY_IDS[code],
                "history": history,
                "remarks": remarks,
            }
        )
    doc = {
        "version": 1,
        "taken_at": "2026-10-01T00:00:00Z",
        "chunk": {"index": 1, "of": 1},
        "countries": [{"id": i, "name": NAMES[c], "region": 2} for c, i in COUNTRY_IDS.items()],
        "units": units,
    }
    return json.dumps(doc).encode()


def rko_violations() -> bytes:
    header = [
        "Страна", "Пиццерия", "Пользователь", "Выявленные нарушения", "Ответы клиента",
        "Другие проблемы", "Номер заказа", "Дата заказа", "Название пиццы",
        "Размер и тип теста", "Link", "KnowledgeBaseLink", "CreatedAtUtc", "CheckupType",
    ]  # fmt: skip
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for n, (dodo_id, name, code) in enumerate(UNITS, start=1):
        for k in range(4):
            checkup = f"{DEMO_PREFIX}{(5000 + n * 10 + k):028x}"
            writer.writerow(
                [
                    NAMES[code], name, "", "; ".join(VIOLATION_TEXTS[: (n + k) % 3]), "", "",
                    str(k), f"2026-09-{10 + k:02d} 12:00:00", "Pepperoni", "30 cm",
                    f"https://control.dodois.io/backoffice/checkups/{checkup}",
                    f"https://dodopizza.info/rating#/{dodo_id}/1?checkupId={checkup}",
                    "", "Доставка" if k % 2 else "Ресторан",
                ]
            )  # fmt: skip
    return b"\xef\xbb\xbf" + out.getvalue().encode()


def wipe(conn: psycopg.Connection) -> None:
    """Убрать демо: строки с `dodo_id` на `de00` и журнал сида."""
    like = DEMO_PREFIX + "%"
    conn.execute("delete from ratings.violations where unit_dodo_id like %s", (like,))
    conn.execute("delete from ratings.checkups where dodo_id like %s", (like,))
    conn.execute("delete from ratings.scores where unit_dodo_id like %s", (like,))
    conn.execute("delete from ratings.periods where dodo_id like %s", (like,))
    conn.execute("delete from ratings.units where dodo_id like %s", (like,))
    conn.execute(
        "update ratings.countries set developer = null where developer = %s", (DEVELOPER,)
    )
    conn.execute(
        "delete from ratings.import_issues where import_id in "
        "(select id from ratings.imports where channel = 'seed')"
    )
    conn.execute(
        "update ratings.imports set outcome = 'failed', note = 'demo reset' "
        "where channel = 'seed' and outcome = 'loaded'"
    )


def main() -> int:
    dsn = check_environment().dsn
    seed_web_demo._require_local_dsn(dsn)
    with psycopg.connect(dsn) as conn:
        wipe(conn)
    for name, data in (
        ("demo-snapshot.json", snapshot()),
        ("demo-rko-violations.csv", rko_violations()),
    ):
        report = import_file(
            data,
            kind=None,
            channel=CHANNEL_SEED,
            actor="demo-seed",
            file_name=name,
            today=date(2026, 10, 1),
            source="demo",
        )
        print(f"{name}: {report.outcome}, +{report.accepted} ~{report.updated}")
    with psycopg.connect(dsn) as conn:
        for code in COUNTRY_IDS:
            conn.execute(
                "update ratings.countries set developer = %s where code = %s", (DEVELOPER, code)
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
