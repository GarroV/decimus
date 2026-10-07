"""Стенд мини-аппа обхода (#418): середина проверки и прошлая проверка той же точки.

Нужен, чтобы прототип можно было пощупать с телефона без бота: страница
открывается в режиме просмотра (`WEB_WALK_PREVIEW_CHAT`) на чат, который
собирает этот скрипт. Картина подобрана под то, что экран должен показать:

* прошлая проверка точки с замечаниями в четырёх зонах — подсказка «здесь
  было»;
* идущая проверка, где одно прошлое замечание записано снова, а ещё две
  записи сделаны в других зонах — часть зон засчитана сама, часть нет.

Методика — синтетическая из `tests/methodology`: коды зон в ней настоящие,
формулировки выдуманы, боевых данных стенд не касается. Состояние и база —
те, что заданы окружением (`STATE_DIR`, `DATABASE_URL`); база обязана быть
стендовой, адрес проверяется так же, как в `seed_web_demo`.

Повторный запуск возвращает стенд к исходному виду: прошлая проверка точки
стенда сносится и сливается заново, идущая собирается с нуля.

Запуск (из корня репозитория, окружение стенда):

    python tools/seed_walk_stand.py
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import psycopg  # noqa: E402
from seed_web_demo import ADMIN_URL_VAR, _require_local_dsn  # noqa: E402

from src import domain  # noqa: E402
from src.db.config import check_environment  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.domain.engine import chat_dir  # noqa: E402

METHODOLOGY = REPO_ROOT / "tests" / "methodology"

#: Чат идущей проверки — его и открывает просмотр. Из того же заведомо
#: вымышленного диапазона, что у демо-сидов: с боевым чатом не совпадёт.
WALK_CHAT = 999_000_000_501
PAST_CHAT = 999_000_000_502

UNIT = "Тестоград-1"
TENANT = "default"
PAST_DATE = "2026-09-16"

#: (код, класс, зона, формулировка) — прошлый раз.
PAST = (
    ("CLN12", "D1", "dining", "Два стола у окна не протёрты, крошки и разводы."),
    ("CLN05", "D1", "hot_kitchen", "Нагар на задней стенке печи, жировые потёки у вытяжки."),
    ("PRD09", "D2", "fridge", "Три контейнера с заготовками без даты маркировки."),
    ("CLN02", "D1", "dishwashing", "Налёт на смесителе у второй раковины."),
)

#: Сегодня: CLN05 в горячем цехе повторился, плюс две новые записи.
TODAY = (
    ("CLN05", "D1", "hot_kitchen", "Снова нагар на задней стенке печи."),
    ("CLN13", "D1", "staff", "Урна в раздевалке переполнена."),
    ("PRD06", "D1", "cold_kitchen", "Гастроёмкость с овощами не накрыта крышкой."),
)


def _fresh(chat_id: int) -> None:
    work_dir = chat_dir(chat_id, domain.check_environment())
    if work_dir.exists():
        shutil.rmtree(work_dir)


def _start(chat_id: int, day: str, findings: tuple[tuple[str, str, str, str], ...]) -> None:
    _fresh(chat_id)
    domain.start_inspection(
        chat_id,
        unit=UNIT,
        kind="planned",
        report_lang="ru",
        ui_lang="ru",
        speech_lang="ru",
        date=day,
        city="Тестоград",
        auditor="Стенд",
        tenant=TENANT,
    )
    for code, level, zone, text in findings:
        domain.add_finding(chat_id, code, level, zone, text)


def _forget_past(dsn: str) -> int:
    """Снести прошлые проверки точки стенда — и только её."""
    _require_local_dsn(dsn)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "delete from inspections i using units u "
            "where u.id = i.unit_id and u.name = %s and i.tenant_code = %s",
            (UNIT, TENANT),
        )
        return cur.rowcount


def seed() -> None:
    os.environ["AUDIT_DATA_DIR"] = str(METHODOLOGY)
    app_dsn = check_environment().dsn
    removed = _forget_past((os.environ.get(ADMIN_URL_VAR) or "").strip() or app_dsn)
    if removed:
        print(f"Прошлые проверки точки стенда снесены: {removed}")

    _start(PAST_CHAT, PAST_DATE, PAST)
    past_id = push_inspection(PAST_CHAT, allow_unknown_version=True)
    _fresh(PAST_CHAT)
    _start(WALK_CHAT, date.today().isoformat(), TODAY)
    print(f"Прошлая проверка {UNIT} от {PAST_DATE} в базе: {past_id}")
    print(f"Идущая проверка: чат {WALK_CHAT} — его и задать в WEB_WALK_PREVIEW_CHAT")


if __name__ == "__main__":
    seed()
