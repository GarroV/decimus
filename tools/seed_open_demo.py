"""Посев открытого демо (D524): выдуманная сеть пиццерий на отдельном стенде.

Отличие от `tools/seed_web_demo.py`: тот кладёт шесть проверок в общую базу
разработчика и пространство `demo` соседствует там с чужими данными. Этот
посев — для стенда, где база целиком демо (`/srv/decimus-demo`): стенд перед
ним сносит и заводит базу заново (`deploy/demo/reset.sh`), поэтому прежнее
здесь не ищется и не удаляется.

Что получается:

* восемь пиццерий в трёх странах, все — точки партнёра `demo`;
* проверки с мая по октябрь 2026, по две-три на точку: плановые, внеплановые
  и повторные, с повторами замечаний между визитами;
* к замечаниям — кадры из `DEMO_PHOTOS_DIR` (снимки Белграда-1 и -2 без
  метаданных; в репозиторий не кладутся — он публичный). Кадры проходят той же
  дорогой, что кадры мини-аппа: `save_upload` → слив → `upload_photos`;
* все проверки, кроме двух самых свежих, приняты дверью продукта
  (`accept_inspection`), и D2 порождают планы действий сами (D272);
* по учётке на роль из `src.domain.demo.DEMO_ROLES`, пароль случайный и нигде
  не печатается — входят через `/demo`.

Методика — синтетический демо-чек-лист `demo/data` (боевая методика вне git и
наружу не выходит). Даты фиксированные: демо, меняющееся от дня запуска, нечем
сверять.

Запуск (окружение стенда, из корня репозитория):

    SEED_WEB_DEMO_FORCE=1 DEMO_PHOTOS_DIR=... python tools/seed_open_demo.py
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import psycopg  # noqa: E402
import seed_demo  # noqa: E402 -- путь к репозиторию выставляется выше
from seed_web_demo import ADMIN_URL_VAR, _require_local_dsn  # noqa: E402

from src import domain  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.config import check_environment, load_storage_settings  # noqa: E402
from src.db.directory import upsert_unit  # noqa: E402
from src.db.errors import ConfigError  # noqa: E402
from src.db.photos import upload_photos  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.space import SYSTEM_SPACE, acting_space, apply_space  # noqa: E402
from src.db.spaces import bind_countries  # noqa: E402
from src.db.web_access import create_account  # noqa: E402
from src.domain.demo import DEMO_PARTNER_TENANT, DEMO_ROLES  # noqa: E402
from src.domain.engine import chat_dir  # noqa: E402
from src.domain.tenants import HQ_TENANT  # noqa: E402
from src.domain.uploads import upload_file  # noqa: E402

PHOTOS_VAR = "DEMO_PHOTOS_DIR"
#: Первый чат демо-проверок. Диапазон заведомо вымышленный, как у прочих сидов.
FIRST_CHAT = 999_000_000_601
#: Чат идущей проверки, которую открывает приложение аудитора в демо
#: (`WEB_WALK_PREVIEW_CHAT`); из вымышленного диапазона просмотра.
WALK_CHAT = 999_000_000_701
#: Сколько самых свежих проверок оставить на приёмке — показать очередь.
PENDING = 2

HQ_AUDITORS = ("Marco Bianchi", "Olivia Hart")
PARTNER_AUDITOR = "Lena Novak"


@dataclass(frozen=True)
class Unit:
    name: str
    city: str
    country: str


UNITS = (
    Unit("Northgate-1", "Northgate", "RS"),
    Unit("Northgate-2", "Northgate", "RS"),
    Unit("Riverside-1", "Riverside", "RS"),
    Unit("Hillcrest-1", "Hillcrest", "GE"),
    Unit("Harbor Bay-1", "Harbor Bay", "GE"),
    Unit("Old Town-1", "Old Town", "AM"),
    Unit("Lakeside-1", "Lakeside", "AM"),
    Unit("Westfield-1", "Westfield", "AM"),
)


@dataclass(frozen=True)
class Note:
    """Замечание: код, класс, зона, формулировка и кадры (имена файлов)."""

    code: str
    level: str
    zone: str
    text: str
    photos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Visit:
    unit: str
    date: str
    kind: str
    notes: tuple[Note, ...]
    by_partner: bool = False
    auditor: str = field(default="")


N = Note
VISITS: tuple[Visit, ...] = (
    Visit(
        "Northgate-1",
        "2026-05-06",
        "planned",
        (
            N(
                "DEM11",
                "D1",
                "kitchen",
                "Burnt-on residue under the oven conveyor belt and on the rollers.",
                ("p09.jpg", "p10.jpg"),
            ),
            N(
                "DEM08",
                "D1",
                "storage",
                "Opened BBQ sauce container without an opening date.",
                ("p18.jpg",),
            ),
            N(
                "DEM13",
                "D1",
                "staff",
                "Dust and debris collected in the corner of the courier area.",
                ("p26.jpg",),
            ),
            N(
                "DEM17",
                "D0",
                "kitchen",
                "Refrigerated table +4 °C, freezer −21 °C — within range.",
                ("p19.jpg", "p20.jpg"),
            ),
            N(
                "DEM18",
                "D0",
                "dining",
                "Test order: chicken and ham pizza, no remarks.",
                ("p03.jpg", "p04.jpg", "p05.jpg"),
            ),
        ),
    ),
    Visit(
        "Hillcrest-1",
        "2026-05-13",
        "planned",
        (
            N(
                "DEM11",
                "D2",
                "kitchen",
                "Thick carbon layer on the conveyor wire, crumbs between the coils.",
                ("q30.jpg", "q34.jpg"),
            ),
            N(
                "DEM12",
                "D1",
                "dining",
                "Burnt residue on the cup sealer ring and around the bolts.",
                ("q36.jpg",),
            ),
            N(
                "DEM15",
                "D1",
                "dining",
                "Crumbs left on benches and tables in several places.",
                ("q51.jpg",),
            ),
            N("DEM16", "D0", "kitchen", "Oven display: 277 °C, bake time 00:40.", ("q35.jpg",)),
        ),
    ),
    Visit(
        "Old Town-1",
        "2026-05-20",
        "planned",
        (
            N(
                "DEM13",
                "D2",
                "dining",
                "Debris trapped in the gap behind the counter equipment.",
                ("q50.jpg",),
            ),
            N(
                "DEM05",
                "D2",
                "kitchen",
                "Two packs of shredded cheese one day past their shelf life.",
            ),
            N("DEM10", "D1", "staff", "Paper towels ran out at the handwashing sink."),
            N(
                "DEM18",
                "D0",
                "dining",
                "Test order: pepperoni pizza, no remarks.",
                ("q16.jpg", "q17.jpg"),
            ),
        ),
    ),
    Visit(
        "Riverside-1",
        "2026-06-03",
        "planned",
        (
            N(
                "DEM14",
                "D1",
                "dining",
                "Rub marks and scuffs on the wall panel above the skirting.",
                ("p25.jpg",),
            ),
            N(
                "DEM12",
                "D1",
                "kitchen",
                "Grime around the screws of the can-opener mount on the prep table.",
                ("p17.jpg",),
            ),
            N("DEM01", "D1", "facade", "One bin lid left open at the entrance."),
        ),
    ),
    Visit(
        "Harbor Bay-1",
        "2026-06-10",
        "planned",
        (
            N(
                "DEM12",
                "D2",
                "kitchen",
                "Dough mixer left uncovered with vegetable scraps inside the bowl.",
                ("q42.jpg",),
            ),
            N(
                "DEM13",
                "D1",
                "dining",
                "Floor not mopped since morning: streaks along the aisle.",
                ("q52.jpg", "q53.jpg"),
            ),
            N(
                "DEM17",
                "D0",
                "kitchen",
                "Refrigerated table +4 °C, freezer −22 °C — within range.",
                ("q40.jpg", "q28.jpg"),
            ),
        ),
    ),
    Visit(
        "Northgate-2",
        "2026-06-17",
        "planned",
        (
            N(
                "DEM06",
                "D1",
                "kitchen",
                "Cutting board not sanitized between vegetables and chicken.",
            ),
            N("DEM09", "D1", "staff", "One apron with dried flour marks worn through the shift."),
            N(
                "DEM18",
                "D0",
                "kitchen",
                "Pizza from the line: cheese pizza, no remarks.",
                ("q32.jpg", "q33.jpg"),
            ),
        ),
        by_partner=True,
    ),
    Visit(
        "Lakeside-1",
        "2026-06-24",
        "unscheduled",
        (
            N(
                "DEM05",
                "D3",
                "storage",
                "Bag of mozzarella two days past its shelf life on the production shelf.",
            ),
            N("DEM07", "D1", "storage", "Sack of flour on the floor next to the door."),
            N("DEM02", "D1", "facade", "Hand marks on the entrance door glass at midday."),
        ),
    ),
    Visit(
        "Westfield-1",
        "2026-07-01",
        "planned",
        (
            N("DEM03", "D1", "dining", "Dried stain on one table by the window."),
            N("DEM04", "D2", "dining", "Menu board still lists a pizza removed from the offer."),
            N(
                "DEM16",
                "D0",
                "kitchen",
                "Oven display checked: settings match the standard.",
                ("q35.jpg",),
            ),
        ),
    ),
    Visit(
        "Northgate-1",
        "2026-07-08",
        "planned",
        (
            N(
                "DEM11",
                "D1",
                "kitchen",
                "Carbon is building up on the conveyor again near the hood.",
                ("p11.jpg",),
            ),
            N(
                "DEM13",
                "D1",
                "staff",
                "Debris along the threshold of the courier area.",
                ("p26.jpg",),
            ),
            N("DEM18", "D0", "dining", "Test order: no remarks.", ("p01.jpg", "p05.jpg")),
        ),
    ),
    Visit(
        "Hillcrest-1",
        "2026-07-15",
        "repeat",
        (
            N(
                "DEM11",
                "D1",
                "kitchen",
                "Belt cleaner than last time, light residue on the side panel.",
                ("q34.jpg",),
            ),
            N("DEM15", "D1", "dining", "Crumbs on two benches by the window.", ("q51.jpg",)),
        ),
    ),
    Visit(
        "Old Town-1",
        "2026-07-29",
        "planned",
        (
            N(
                "DEM13",
                "D1",
                "dining",
                "Small debris behind the counter, reachable area clean.",
                ("q50.jpg",),
            ),
            N(
                "DEM08",
                "D1",
                "storage",
                "Opened sauce container without an opening date.",
                ("p18.jpg",),
            ),
        ),
        by_partner=True,
    ),
    Visit(
        "Riverside-1",
        "2026-08-12",
        "planned",
        (
            N(
                "DEM14",
                "D1",
                "staff",
                "Dirt on the skirting board in the staff corridor.",
                ("p25.jpg",),
            ),
            N("DEM10", "D2", "staff", "No hot water at the handwashing sink at shift start."),
            N(
                "DEM17",
                "D0",
                "kitchen",
                "Refrigerated table +4 °C, freezer −21 °C.",
                ("p19.jpg", "p20.jpg"),
            ),
        ),
    ),
    Visit(
        "Lakeside-1",
        "2026-08-19",
        "repeat",
        (
            N("DEM07", "D1", "storage", "One box of dough on the floor during delivery intake."),
            N(
                "DEM18",
                "D0",
                "dining",
                "Test order: pepperoni, cheese stretch as standard.",
                ("q18.jpg", "q19.jpg"),
            ),
        ),
    ),
    Visit(
        "Harbor Bay-1",
        "2026-08-26",
        "planned",
        (
            N(
                "DEM12",
                "D1",
                "kitchen",
                "Mixer covered, light flour residue on the guard.",
                ("q42.jpg",),
            ),
            N("DEM13", "D1", "dining", "Streaks by the entrance column after rain.", ("q53.jpg",)),
        ),
    ),
    Visit(
        "Northgate-2",
        "2026-09-02",
        "planned",
        (
            N(
                "DEM06",
                "D2",
                "kitchen",
                "Raw chicken residue on the prep surface next to ready toppings.",
            ),
            N("DEM09", "D1", "staff", "Uniform worn without a cap in the production area."),
            N("DEM16", "D0", "kitchen", "Oven display: 277 °C, 00:40.", ("q35.jpg",)),
        ),
    ),
    Visit(
        "Westfield-1",
        "2026-09-09",
        "planned",
        (
            N("DEM03", "D1", "dining", "Window table stain is back after the last clean-up."),
            N("DEM15", "D1", "dining", "Crumbs on the sofa in the family corner.", ("q51.jpg",)),
        ),
    ),
    Visit(
        "Northgate-1",
        "2026-09-23",
        "planned",
        (
            N("DEM11", "D1", "kitchen", "Light residue on the conveyor rollers.", ("p10.jpg",)),
            N(
                "DEM12",
                "D1",
                "kitchen",
                "Grime around the screws of the prep-table mount.",
                ("p17.jpg",),
            ),
            N("DEM17", "D0", "kitchen", "All refrigeration within range.", ("p19.jpg", "p20.jpg")),
        ),
    ),
    Visit(
        "Hillcrest-1",
        "2026-10-07",
        "planned",
        (
            N(
                "DEM12",
                "D1",
                "dining",
                "Cup sealer ring wiped, residue left around the bolts.",
                ("q36.jpg",),
            ),
            N("DEM18", "D0", "dining", "Test order: no remarks.", ("q16.jpg", "q17.jpg")),
        ),
    ),
    Visit(
        "Old Town-1",
        "2026-10-12",
        "planned",
        (
            N("DEM13", "D1", "dining", "Floor streaks along the aisle at opening.", ("q52.jpg",)),
            N(
                "DEM05",
                "D1",
                "kitchen",
                "One opened sauce reaching its use-by time without a new label.",
            ),
        ),
    ),
    Visit(
        "Lakeside-1",
        "2026-10-14",
        "planned",
        (
            N(
                "DEM11",
                "D1",
                "kitchen",
                "Carbon on the oven conveyor near the loading window.",
                ("q30.jpg",),
            ),
            N("DEM02", "D1", "facade", "Fingerprints on the entrance door handle."),
            N("DEM18", "D0", "kitchen", "Pizza from the line: no remarks.", ("q32.jpg",)),
        ),
    ),
)


def _photo_bytes(name: str, photos_dir: Path | None) -> bytes | None:
    if photos_dir is None:
        return None
    path = photos_dir / name
    return path.read_bytes() if path.is_file() else None


def _bind_partner(dsn: str) -> None:
    """Завести партнёра `demo` и отдать ему страны всех точек."""
    _require_local_dsn(dsn)
    with psycopg.connect(dsn) as conn:
        apply_space(conn)
        conn.execute(
            "insert into tenants (code, name) values (%s, %s) on conflict (code) do nothing",
            (DEMO_PARTNER_TENANT, "Demo Pizza Partner"),
        )
    bind_countries(DEMO_PARTNER_TENANT, tuple(sorted({u.country for u in UNITS})))


def _accounts() -> None:
    """По учётке на роль демо; пароль случайный — вход только через `/demo`."""
    for role in DEMO_ROLES:
        create_account(
            role.login, tenant=role.tenant, password=secrets.token_urlsafe(24), role=role.role
        )


def _build(chat_id: int, visit: Visit, unit: Unit, seen: set[str], photos_dir: Path | None) -> None:
    """Собрать проверку тем же кодом, что бот и мини-апп; кадры — как у мини-аппа."""
    settings = domain.check_environment()
    work_dir = chat_dir(chat_id, settings)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    auditor = PARTNER_AUDITOR if visit.by_partner else HQ_AUDITORS[chat_id % len(HQ_AUDITORS)]
    domain.start_inspection(
        chat_id,
        unit=unit.name,
        kind=visit.kind,
        report_lang="en",
        ui_lang="en",
        speech_lang="en",
        date=visit.date,
        city=unit.city,
        auditor=auditor,
        tenant=DEMO_PARTNER_TENANT if visit.by_partner else HQ_TENANT,
    )
    for note in visit.notes:
        frames = []
        for name in note.photos:
            raw = _photo_bytes(name, photos_dir)
            if raw is not None:
                frames.append(domain.save_upload(raw, settings))
        domain.add_finding(
            chat_id,
            note.code,
            note.level,
            note.zone,
            note.text,
            photos=frames,
            repeat=note.level != "D0" and note.code in seen,
        )


def _read_frame(ref: str) -> bytes | None:
    path = upload_file(ref, domain.check_environment())
    return path.read_bytes() if path is not None else None


def _storage_ready() -> bool:
    """Хранилище кадров задано окружением. Нет — кадры лягут строками без ссылки.

    Так же ведёт себя продукт, когда хранилище лежит (#459): проверка в истории,
    кадры ждут дозагрузки. На стенде демо хранилище есть всегда; без него посев
    гоняется в тестах.
    """
    try:
        load_storage_settings()
    except ConfigError as exc:
        print(f"Хранилище кадров не задано — кадры не выгружаются: {exc}", file=sys.stderr)
        return False
    return True


def _walk(photos_dir: Path | None) -> None:
    """Идущая проверка Northgate-1 для приложения аудитора: в базу не сливается.

    У точки уже есть прошлые проверки — приложение покажет «здесь было».
    """
    visit = Visit(
        "Northgate-1",
        date.today().isoformat(),
        "planned",
        (
            N(
                "DEM11",
                "D1",
                "kitchen",
                "Light carbon on the conveyor rollers again.",
                ("p09.jpg",),
            ),
            N("DEM13", "D1", "staff", "Debris in the corner of the courier area.", ("p26.jpg",)),
        ),
    )
    _build(WALK_CHAT, visit, {u.name: u for u in UNITS}["Northgate-1"], {"DEM11"}, photos_dir)


def seed() -> int:
    os.environ["AUDIT_DATA_DIR"] = str(seed_demo.DEMO_DATA_DIR)
    os.environ["STATE_DIR"] = str(seed_demo.demo_state_dir())
    raw_dir = (os.environ.get(PHOTOS_VAR) or "").strip()
    photos_dir = Path(raw_dir) if raw_dir else None
    if photos_dir is None or not photos_dir.is_dir():
        print(f"{PHOTOS_VAR} не задан или не каталог — проверки лягут без кадров", file=sys.stderr)
        photos_dir = None
    app_dsn = check_environment().dsn
    _require_local_dsn(app_dsn)
    upload = photos_dir is not None and _storage_ready()
    admin_dsn = (os.environ.get(ADMIN_URL_VAR) or "").strip() or app_dsn
    _bind_partner(admin_dsn)
    for unit in UNITS:
        upsert_unit(unit.name, country=unit.country, city=unit.city, tenant=HQ_TENANT)
    _accounts()

    units = {u.name: u for u in UNITS}
    seen: dict[str, set[str]] = {}
    pushed: list[tuple[str, str]] = []
    for i, visit in enumerate(sorted(VISITS, key=lambda v: v.date)):
        chat_id = FIRST_CHAT + i
        prior = seen.setdefault(visit.unit, set())
        _build(chat_id, visit, units[visit.unit], prior, photos_dir)
        ident = push_inspection(chat_id, allow_unknown_version=True)
        if upload:
            upload_photos(ident, fetch=_read_frame)
        score = domain.score(chat_id)
        prior.clear()
        prior.update(n.code for n in visit.notes if n.level != "D0")
        pushed.append((ident, DEMO_PARTNER_TENANT if visit.by_partner else HQ_TENANT))
        print(f"{visit.unit} {visit.date}: {score.pct:g}% {score.grade}")
    # Принимает пространство, которое проверку провело: партнёрскую — его админ.
    for ident, owner in pushed[:-PENDING]:
        actor = PARTNER_AUDITOR if owner == DEMO_PARTNER_TENANT else "Olivia Hart"
        accept_inspection(ident, tenant=owner, actor=actor)
    _walk(photos_dir)
    print(f"Auditor app: in-progress inspection in chat {WALK_CHAT} (WEB_WALK_PREVIEW_CHAT)")
    print(f"Open demo seeded: {len(pushed)} inspections, {len(DEMO_ROLES)} demo accounts")
    return 0


if __name__ == "__main__":
    with acting_space(SYSTEM_SPACE):
        sys.exit(seed())
