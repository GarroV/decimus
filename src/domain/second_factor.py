"""Вторая ступень входа (D463): правила без базы и без веба.

Чистый Python: кому ступень обязательна, как выглядит и проверяется код из
приложения-аутентификатора, как выпускаются и сверяются резервные коды. Хранит и
спрашивает базу `src/db/second_factor.py`, показывает веб `src/web/second_step.py` и
`src/web/security_screen.py`; решение «что считается верным» — здесь, в одном месте.

**TOTP по RFC 6238:** шесть цифр, шаг 30 секунд, окно ±1 шаг (часы телефона уходят).
Проверка возвращает НОМЕР шага, по которому код сошёлся, а не «да/нет»: хранилище
запоминает последний принятый шаг и отвергает код, чей шаг не новее — тот же код в
пределах своего окна второй раз не проходит (повтор подсмотренного кода).

**Резервные коды** — 16 знаков алфавита без похожих друг на друга (`4×4` через дефис),
около 79 бит: перебор отпечатка sha256 из украденной базы нереален, поэтому медленная
свёртка не нужна (код случаен, не придуман человеком). В базе — только отпечаток с
солью учётки; показывается код один раз.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import pyotp

#: Роли, которым вторая ступень обязательна: угнанная учётка админа — вся система.
REQUIRED_ROLES = frozenset({"admin", "superadmin"})

#: Полупройденный вход живёт не дольше (D463): время на ввод кода, не на раздумья.
PENDING_TTL = timedelta(minutes=5)

#: Вызов входа ключом с формы входа живёт не дольше (D485): окно Touch ID, не раздумья.
PASSKEY_LOGIN_TTL = timedelta(minutes=2)

#: Кому после входа паролем или Google браузер сам предлагает Touch ID (D485): всем ролям веба,
#: кроме гостя и аудитора (он работает в мини-апп Telegram, а не в админке).
PASSKEY_AUTO_ROLES = frozenset({"developer", "admin", "superadmin", "control"})

#: Ключ доступа, которым не входили дольше, снимается сам (D485): забытое устройство не остаётся
#: входом навсегда. Отсчёт — от последнего входа, а у ни разу не использованного — от создания.
PASSKEY_IDLE_LIMIT = timedelta(days=30)

#: Сколько неверных ответов выдерживает один полупройденный вход, потом он мёртв.
MAX_PENDING_FAILURES = 5

#: Вход «свежий» для изменения способов входа: не старше (D463). Старее — войти заново.
FRESH_FOR_ENROLLMENT = timedelta(minutes=10)

#: Вызов ключа доступа живёт две минуты и снимается при первом предъявлении.
CHALLENGE_TTL = timedelta(minutes=2)

#: Сколько резервных кодов выпускается разом.
BACKUP_CODE_COUNT = 10

#: Имя ключа доступа: ограничение схемы (`0068`) и формы.
MAX_PASSKEY_NAME = 60

#: Приложение-аутентификатор: параметры RFC 6238, которые понимает любое приложение.
TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_WINDOW = 1
#: Имя издателя в приложении: по нему человек находит строку среди прочих.
TOTP_ISSUER = "Decimus"

#: Алфавит резервных кодов: без 0/O, 1/I/L (читаются и диктуются без ошибок).
_BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_BACKUP_GROUPS = 4
_BACKUP_GROUP_LEN = 4

_CODE_DIGITS = re.compile(r"[0-9]{%d}" % TOTP_DIGITS)


def passkey_auto_enroll(role: str) -> bool:
    """Предлагать ли этой роли сохранить Touch ID в браузере после входа."""
    return role in PASSKEY_AUTO_ROLES


def is_required(role: str) -> bool:
    """Вторая ступень обязательна этой роли."""
    return role in REQUIRED_ROLES


def new_totp_secret() -> str:
    """Новый секрет приложения: base32, 160 бит (`pyotp.random_base32`, 32 знака)."""
    return pyotp.random_base32(length=32)


def totp_uri(secret: str, *, login: str) -> str:
    """Адрес `otpauth://` для QR: человек сканирует его приложением."""
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS).provisioning_uri(
        name=login, issuer_name=TOTP_ISSUER
    )


def totp_step_now(now: datetime | None = None) -> int:
    """Номер шага времени на момент `now`."""
    момент = (now or datetime.now(UTC)).timestamp()
    return int(момент // TOTP_INTERVAL_SECONDS)


def normalize_totp_code(raw: str) -> str | None:
    """Код из приложения без пробелов; не шесть цифр — `None`."""
    чистый = re.sub(r"[\s\-]", "", raw or "")
    return чистый if _CODE_DIGITS.fullmatch(чистый) else None


def match_totp_step(secret: str, code: str, *, now: datetime | None = None) -> int | None:
    """Номер шага, по которому `code` сошёлся в окне ±`TOTP_WINDOW`; не сошёлся — `None`.

    Сравнение постоянного времени по каждому из шагов окна: ответ не зависит от того,
    на какой цифре код разошёлся.
    """
    чистый = normalize_totp_code(code)
    if чистый is None:
        return None
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS)
    сейчас = totp_step_now(now)
    найден: int | None = None
    for сдвиг in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        шаг = сейчас + сдвиг
        ожидаемый = totp.at(шаг * TOTP_INTERVAL_SECONDS)
        if hmac.compare_digest(ожидаемый.encode(), чистый.encode()) and найден is None:
            найден = шаг
    return найден


def new_backup_codes(count: int = BACKUP_CODE_COUNT) -> tuple[str, ...]:
    """Новые резервные коды вида `ABCD-EFGH-JKMN-PQRS`; показываются человеку один раз."""
    return tuple(
        "-".join(
            "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(_BACKUP_GROUP_LEN))
            for _ in range(_BACKUP_GROUPS)
        )
        for _ in range(count)
    )


def normalize_backup_code(raw: str) -> str | None:
    """Резервный код без пробелов и дефисов, прописными; не по форме — `None`."""
    чистый = re.sub(r"[\s\-]", "", raw or "").upper()
    длина = _BACKUP_GROUPS * _BACKUP_GROUP_LEN
    if len(чистый) != длина or any(знак not in _BACKUP_ALPHABET for знак in чистый):
        return None
    return чистый


def backup_code_hash(user_id: str, code: str) -> str | None:
    """Отпечаток резервного кода для хранения и сверки; код не по форме — `None`.

    Соль — номер учётки: одинаковые коды у двух людей давали бы одинаковые строки.
    """
    чистый = normalize_backup_code(code)
    if чистый is None:
        return None
    return hashlib.sha256(f"decimus-backup:{user_id}:{чистый}".encode()).hexdigest()


def enrollment_window(role: str, *, has_factor: bool) -> timedelta:
    """Сколько после входа можно менять способы входа.

    Админу и главному админу, у которых способа ещё нет, окно короче — как у полувхода
    (`PENDING_TTL`): подключение первого способа — единственное место, где украденная
    первая ступень могла бы закрепить ЧУЖОЙ способ (D463). Остальным и тем, у кого способ
    уже есть, — `FRESH_FOR_ENROLLMENT`.
    """
    if is_required(role) and not has_factor:
        return PENDING_TTL
    return FRESH_FOR_ENROLLMENT


def is_fresh_login(
    signed_in_at: datetime | None, *, role: str, has_factor: bool, now: datetime | None = None
) -> bool:
    """Вход достаточно свеж для изменения способов; время неизвестно — не свеж."""
    if signed_in_at is None:
        return False
    return (now or datetime.now(UTC)) - signed_in_at <= enrollment_window(
        role, has_factor=has_factor
    )


def may_remove_factor(
    *,
    passed_second_step: bool,
    signed_in_at: datetime | None,
    role: str,
    has_factor: bool,
    now: datetime | None = None,
) -> bool:
    """Снять способ входа или сбросить чужую ступень: сессия прошла вторую ступень И свежая.

    Сессия, выданная одной первой ступенью (пусть даже она потом подключила способ),
    снимать способы не может: украденный пароль не должен хватать, чтобы разоружить
    вторую ступень. Замена единственного способа — это снятие, и она тоже требует этого.
    """
    return passed_second_step and is_fresh_login(
        signed_in_at, role=role, has_factor=has_factor, now=now
    )


def removal_leaves_required_factor(*, role: str, remaining_factors: int) -> bool:
    """Можно ли убрать способ, если после этого останется `remaining_factors` способов.

    Резервные коды способом не считаются (это восстановление, не вход). Админу и
    главному админу последний способ не снять (D463); остальным — можно.
    """
    return remaining_factors > 0 or not is_required(role)
