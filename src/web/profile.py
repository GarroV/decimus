"""Свой пароль с экрана (#324): что форма пропускает к базе и что отвечает.

Экран — карточка «Сменить пароль» на вкладке «Пользователи»: эта вкладка
открыта каждому вошедшему, и там человек уже видит свою учётку. Отдельного
раздела навигации под одну форму не заводится.

Порядок проверок не случаен:

1. новый пароль и повтор — до всего остального: это ввод самого человека, о
   текущем пароле он ничего не говорит и попытки не тратит;
2. заявка ограничителю перебора (`admit_attempt`) — по логину вошедшего и
   адресу, ТЕМИ ЖЕ ключами, что у формы входа. Иначе форма профиля была бы
   вторым входом для подбора: кто сидит в чужой открытой вкладке, перебирал бы
   текущий пароль без счёта. Запертый до сверки не доходит;
3. сверка и запись — одной дверью базы, своей сессией (`change_own_password`).

Отказ на текущий пароль один и тот же: что именно с ним не так, форма не
говорит.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.db.errors import DbError
from src.db.web_throttle import Verdict, admit_attempt, note_success

from . import accounts

#: Исходы смены — коды, а не фразы: текст подбирает экран на своём языке
#: (`users.password.<исход>` в `texts.py`).
OK = "ok"
MISMATCH = "mismatch"
SHORT = "short"
EMPTY = "empty"
WRONG = "wrong"
LOCKED = "locked"
FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    """Чем кончилась смена: код исхода, код ответа и срок запрета, если заперто."""

    key: str
    status: int
    retry_after_seconds: int | None = None
    locked_minutes: int | None = None


def change_own(
    *, current: str, new: str, repeat: str, token: str, login: str, stand: str, address: str
) -> Outcome:
    """Сменить пароль вошедшему. `stand` — тенант стенда: на нём ведётся счётчик входа."""
    if not current or not new:
        return Outcome(EMPTY, 400)
    if new != repeat:
        return Outcome(MISMATCH, 400)
    if len(new) < accounts.MIN_PASSWORD_LENGTH:
        return Outcome(SHORT, 400)
    попытка = admit_attempt(tenant=stand, address=address, login=login)
    if not попытка.admitted:
        return _заперто(попытка.verdict)
    try:
        сменён = accounts.change_own_password(token, current=current, new=new)
    except DbError:
        return Outcome(FAILED, 503)
    if not сменён:
        if попытка.verdict.locked:
            return _заперто(попытка.verdict)
        return Outcome(WRONG, 400)
    note_success(tenant=stand, address=address, login=login)
    return Outcome(OK, 200)


def _заперто(приговор: Verdict) -> Outcome:
    return Outcome(
        LOCKED,
        429,
        retry_after_seconds=приговор.retry_after_seconds,
        locked_minutes=приговор.retry_after_minutes,
    )
