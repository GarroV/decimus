"""Приглашения по Telegram-юзернейму: кого пускать до того, как узнали ID (#230).

Доступ к боту держится числовыми Telegram ID (`src.bot.access`), и это верно:
ID неизменен, юзернейм — нет. Но числа неоткуда взять заранее. Bot API не
отдаёт ID по юзернейму, а сам ID приходит только в апдейте — то есть уже
после того, как человек написал. Пока обе стороны ждут друг друга, каждый
новый аудитор стоит ssh на площадку, правки `.env` и перезапуска.

Юзернейм при этом лежит в том же апдейте и до сих пор не читался нигде.
Отсюда развязка: стенд называет ЮЗЕРНЕЙМЫ, бот узнаёт ID при первом контакте
и дальше проверяет уже по нему (`src.bot.roster`).

**Юзернейм — приглашение, а не ключ.** Владелец отпускает его в любой момент,
и освободившийся занимает кто угодно другой; пускать по юзернейму постоянно
означало бы отдать постороннему отчёты партнёров и историю проверок. Поэтому
приглашение срабатывает один раз, а постоянным ключом становится ID.

**Источник приглашений спрятан за `InviteSource`.** Сейчас за ним `.env`
(`StaticInvites`), дальше — серверная логика сервиса проверок; проверка
доступа при подмене источника не меняется вовсе.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .errors import BotConfigError

#: Список приглашений в окружении стенда: «юзернейм:Имя Фамилия» через
#: запятую, имя необязательно. Переменная необязательна целиком — стенд, куда
#: никого не приглашают, обязан подниматься без неё.
INVITES_VAR = "BOT_INVITES"

#: Из чего Telegram позволяет составить юзернейм: латиница, цифры,
#: подчёркивание. Предел длины у Telegram — 32 знака.
#:
#: Проверка здесь не воспроизводит правила Telegram (нижнюю границу в пять
#: знаков, запрет начинать с цифры) и не должна: её работа — поймать опечатку
#: в файле настроек, а не отказать живому юзернейму, если Telegram однажды
#: смягчит своё правило. Чужой формат, повторённый в нашем коде, устаревает
#: молча и отказывает тому, кто ни в чём не виноват.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")


@dataclass(frozen=True)
class Invite:
    """Приглашение: кого ждём и как его назвать в отчёте партнёру.

    `name` необязателен: без него имя возьмётся из профиля Telegram
    (`src.bot.auditor`), со всеми его эмодзи. Это законное состояние, а не
    недоделка — приглашение не должно ждать, пока выяснят фамилию.
    """

    username: str
    name: str | None = None


class InviteSource(Protocol):
    """Откуда берутся приглашения. Единственная точка, которую заменит сервис."""

    def find(self, username: str | None) -> Invite | None:
        """Приглашение для этого юзернейма — или `None`, если такого не ждут."""


@dataclass(frozen=True)
class StaticInvites:
    """Приглашения, названные окружением стенда: список из `BOT_INVITES`."""

    invites: Mapping[str, Invite]

    def find(self, username: str | None) -> Invite | None:
        if not username:
            return None
        return self.invites.get(normalize_username(username))


def normalize_username(raw: str) -> str:
    """Привести юзернейм к виду, в котором он сравнивается.

    Юзернеймы Telegram регистронезависимы: `@Ivanov` и `ivanov` — один
    человек. Сравнивать их как есть означало бы, что приглашение не срабатывает
    из-за заглавной буквы в файле настроек, — и понять это по молчащему боту
    нельзя (посторонним он не отвечает намеренно).
    """
    return raw.strip().lstrip("@").strip().lower()


def parse_invites(raw: str) -> dict[str, Invite]:
    """Разобрать `BOT_INVITES`: «юзернейм:Имя Фамилия» через запятую.

    Кривая запись — отказ на старте, а не пропуск строки. Тот же принцип уже
    держит `AUDITOR_NAMES` (`src.bot.config`): молча пропущенное приглашение
    означало бы, что человек не может войти, а настройка выглядит рабочей, и
    выяснять это пришлось бы по боту, который посторонним не отвечает.
    """
    invites: dict[str, Invite] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        raw_username, has_name, raw_name = piece.partition(":")
        username = normalize_username(raw_username)
        if not _USERNAME_RE.match(username):
            raise BotConfigError(
                f"{INVITES_VAR}: «{piece}» не похоже на юзернейм Telegram. "
                f"Нужен вид @username:Имя Фамилия через запятую"
            )
        name = raw_name.strip()
        if has_name and not name:
            raise BotConfigError(
                f"{INVITES_VAR}: у @{username} пустое имя. Уберите двоеточие, "
                f"если имя брать из профиля Telegram"
            )
        if username in invites:
            raise BotConfigError(
                f"{INVITES_VAR}: @{username} назван дважды. Имя в отчёте зависело бы "
                f"от порядка строк — оставьте одну запись"
            )
        invites[username] = Invite(username=username, name=name or None)
    return invites
