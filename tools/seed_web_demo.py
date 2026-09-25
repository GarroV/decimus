"""Демо-история в базе: то, что показывает веб-админка. Запускается `make web-demo`.

Отличие от `tools/seed_demo.py` — в том, КУДА кладётся результат. Тот сид
собирает одну проверку в состоянии бота (`DEMO_STATE_DIR`) и нужен показу в
телеграме; веб-админка состояния бота не видит вовсе — она читает базу
завершённых проверок. Без этого сида реестр пуст на чистой машине, и поверхность
нечем смотреть: экран «проверок нет» выглядит одинаково и когда их правда нет, и
когда стенд собран неверно.

Проверки собираются ТЕМ ЖЕ кодом, которым их собирает бот (`src.domain`), и
сливаются в базу той же дверью (`src.db.push.push_inspection`), а не своим
запросом. Иначе демо разъехалось бы с продуктом на первой же правке движка или
схемы — ровно то, чего избегает `seed_demo` (см. его шапку).

**Тенант `demo`, а не `default`.** Демо обязано быть отличимо от боевого
одним взглядом на реестр, а не по названию точки. Веб-админка показывает ровно
один тенант (`WEB_TENANT`), поэтому демо-строки не могут подмешаться в историю
партнёров даже случайно.

**Сид отказывается писать в неместную базу.** `DATABASE_URL`, указывающий не на
петлю, — это почти наверняка площадка или база владельца, и выдуманные проверки
там не нужны никому. Осознанный случай (свой стенд по туннелю) снимается
переменной `SEED_WEB_DEMO_FORCE=1`.

Повторный запуск возвращает демо к ЧИСТОМУ ВИДУ, а не просто «не падает второй
раз»: прежняя демо-история сносится целиком и собирается заново. Одного слива
для этого мало — он идемпотентен по отпечатку СОДЕРЖИМОГО, поэтому правка
формулировки в наборе ниже клала бы в реестр вторую строку той же точки вместо
обновления первой (поймано на себе: пять строк вместо трёх). Цена сноса —
идентификаторы после пересборки другие, и прямые ссылки на демо-карточки
устаревают. Даты в наборе всё равно фиксированные, а не «сегодня»: реестр,
меняющийся от дня запуска, нечем сверять.

Запуск (из корня репозитория):

    .venv/bin/python tools/seed_web_demo.py
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

# Переменные окружения нужны до первого обращения к базе — тем же приёмом, что
# в точках входа бота, MCP и веба.
load_dotenv(REPO_ROOT / ".env")

import psycopg  # noqa: E402
import seed_demo  # noqa: E402 -- путь к репозиторию выставляется выше

from src import domain  # noqa: E402
from src.db.config import check_environment  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.domain.engine import chat_dir  # noqa: E402

#: Тенант демо-истории. Почему не `default` — в шапке модуля.
DEMO_TENANT = "demo"

#: Снятие защиты от записи в неместную базу.
FORCE_VAR = "SEED_WEB_DEMO_FORCE"

#: Подключение для сноса прежнего демо. Роль приложения этого сделать не может
#: и не должна: завершённая проверка закрыта от правки построчными политиками
#: (T111), и обойти их — ровно то, чего от продукта требовать нельзя. Здесь
#: берётся та же роль, что катит схему.
ADMIN_URL_VAR = "DATABASE_ADMIN_URL"

#: Хосты, которые считаются местными.
LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "host.docker.internal", "db"})


@dataclass(frozen=True)
class DemoInspection:
    """Одна демо-проверка: всё, что нужно собрать её тем же кодом, что и бот."""

    chat_id: int
    unit: str
    city: str
    #: Код страны точки ISO 3166-1 alpha-2, как в `units.country` (0017).
    #: Кодом, а не названием: название переводится, код нет.
    country: str
    auditor: str
    date: str
    kind: str
    #: (код пункта, класс, зона, формулировка) — коды из demo/data/checklist.csv.
    findings: tuple[tuple[str, str, str, str], ...]


#: Демо-сеть: номера чатов из того же заведомо вымышленного диапазона, что у
#: `seed_demo.DEMO_CHAT_ID`, — коллизия с боевым чатом исключена по построению.
#: Даты фиксированы ради идемпотентности (см. шапку), состав находок подобран
#: так, чтобы реестр показывал разные буквы, а не одну строку трижды.
DEMO_INSPECTIONS = (
    DemoInspection(
        chat_id=999_000_000_101,
        unit="Demo Pizzeria #1",
        country="RS",
        city="Demo City",
        auditor="Demo Auditor",
        date="2026-08-12",
        kind="planned",
        findings=(
            ("DEM01", "D1", "facade", "One bin lid propped open near the entrance, no overflow."),
            ("DEM03", "D1", "dining", "Scratch and dried stain on one guest table by the window."),
            ("DEM06", "D2", "kitchen", "Dried sauce splashes on the prep counter by the oven."),
            ("DEM07", "D1", "storage", "Two boxes of dough missing a received-date label."),
        ),
    ),
    DemoInspection(
        chat_id=999_000_000_102,
        unit="Demo Pizzeria #2",
        country="RS",
        city="Demo City",
        auditor="Demo Auditor",
        date="2026-08-19",
        kind="planned",
        findings=(
            ("DEM08", "D1", "storage", "One opened sauce container without an opening date."),
            ("DEM09", "D1", "staff", "One apron with dried flour marks worn through the shift."),
        ),
    ),
    DemoInspection(
        chat_id=999_000_000_103,
        unit="Demo Pizzeria #3",
        country="GE",
        city="Demo Town",
        auditor="Demo Auditor",
        date="2026-09-02",
        kind="unscheduled",
        findings=(
            ("DEM05", "D3", "storage", "One bag of shredded cheese two days past its shelf life."),
            ("DEM10", "D2", "staff", "Handwashing sink without paper towels at shift start."),
            ("DEM02", "D1", "facade", "Entrance door glass with visible hand marks at midday."),
        ),
    ),
)


def _require_local_dsn(dsn: str) -> None:
    """Отказать, если строка подключения ведёт не на местную базу."""
    if os.environ.get(FORCE_VAR, "").strip() == "1":
        return
    host = (urlsplit(dsn).hostname or "").strip()
    if host in LOCAL_HOSTS:
        return
    raise SystemExit(
        f"Сид демо-истории остановлен: DATABASE_URL ведёт на узел {host}, а не на петлю. "
        f"Выдуманные проверки пишутся только в местную базу. Если это осознанно — "
        f"{FORCE_VAR}=1"
    )


def _reset(app_dsn: str) -> int:
    """Снести прежнюю демо-историю и вернуть число убранных проверок.

    Идемпотентность слива (`push_inspection`) держится на отпечатке
    СОДЕРЖИМОГО: поправили формулировку находки — и тот же прогон кладёт в
    реестр ВТОРУЮ строку той же точки, а не обновляет первую. Поэтому демо
    пересобирается с нуля, как `seed_demo` пересобирает состояние: «повторный
    запуск возвращает демо к чистому виду», а не «не падает второй раз».

    Сносится только тенант `demo` и только он — код подставляется константой
    модуля, а не приходит снаружи, чтобы этой функции нечем было снести чужое.
    Находки, кадры и информационная часть уходят каскадом (миграция `0001`).
    """
    dsn = (os.environ.get(ADMIN_URL_VAR) or "").strip() or app_dsn
    _require_local_dsn(dsn)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("delete from inspections where tenant_code = %s", (DEMO_TENANT,))
        return cur.rowcount


def _set_geography(dsn: str) -> None:
    """Проставить демо-точкам страну и город.

    Отдельным шагом после слива, а не внутри него: проверка не знает
    географии точки — её ведёт справочник, и слив трогать эти колонки не
    вправе. Без этого шага экран сети нечем сузить: панель отбора показывает
    страну и город, а у демо-точек они пусты, и панель выглядит сломанной,
    хотя работает верно.
    """
    _require_local_dsn(dsn)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for spec in DEMO_INSPECTIONS:
            cur.execute(
                "update units set country = %s, city = %s "
                "where tenant_code = %s and name = %s",
                (spec.country, spec.city, DEMO_TENANT, spec.unit),
            )


def _build(spec: DemoInspection) -> None:
    """Собрать одну демо-проверку в состоянии тем же кодом, что и бот."""
    settings = domain.check_environment()
    work_dir = chat_dir(spec.chat_id, settings)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    domain.start_inspection(
        spec.chat_id,
        unit=spec.unit,
        kind=spec.kind,
        report_lang="en",
        ui_lang="en",
        speech_lang="en",
        date=spec.date,
        city=spec.city,
        auditor=spec.auditor,
        tenant=DEMO_TENANT,
    )
    for code, level, zone, evidence in spec.findings:
        domain.add_finding(spec.chat_id, code, level, zone, evidence)


def seed() -> list[str]:
    """Собрать демо-сеть и слить её в базу. Возвращает идентификаторы строк."""
    # Порядок тот же, что у `seed_demo`: окружение ставится до первого
    # обращения к домену, иначе вызов ушёл бы по боевому пути состояния.
    os.environ["AUDIT_DATA_DIR"] = str(seed_demo.DEMO_DATA_DIR)
    os.environ["STATE_DIR"] = str(seed_demo.demo_state_dir())

    app_dsn = check_environment().dsn
    _require_local_dsn(app_dsn)
    removed = _reset(app_dsn)
    if removed:
        print(f"Previous demo history removed: {removed} inspections")

    ids: list[str] = []
    for spec in DEMO_INSPECTIONS:
        _build(spec)
        # Версия методики: у синтетического чек-листа демо её нет, и это не
        # случайность, а свойство набора — слив такой проверки разрешается явно.
        inspection_id = push_inspection(spec.chat_id, allow_unknown_version=True)
        score = domain.score(spec.chat_id)
        ids.append(inspection_id)
        print(f"{spec.unit} — {spec.date}: {score.pct:g}% grade {score.grade}, id={inspection_id}")
    _set_geography(app_dsn)
    print(f"Demo history in the database: {len(ids)} inspections, tenant {DEMO_TENANT}")
    return ids


if __name__ == "__main__":
    seed()
