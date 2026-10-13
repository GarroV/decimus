"""Имя и фото из Google в учётку (D468): скачать фото один раз и записать.

Имя и адрес фото приходят в ПРОВЕРЕННОМ `id_token` (`google_auth`). Фото мы
скачиваем сами при входе и храним у себя: страница отдаёт его со своего адреса
(`/settings/avatar`), политика источников остаётся `img-src 'self'`, и браузер
человека к Google за картинкой не ходит.

**Скачивание — единственное место, где мы идём по адресу, пришедшему снаружи,
поэтому защита от SSRF здесь, и она узкая:** только `https`, хост строго
`*.googleusercontent.com` (сам корень и чужие домены — отказ), без учётных данных
и чужого порта в адресе, БЕЗ перехода по редиректам (редирект на чужой хост —
отказ, а не «пойдём туда»), короткое ожидание, предел размера и тип по
СИГНАТУРЕ байт, а не по заголовку ответа: заголовок пишет тот, кто отвечает.

**Сбой не ломает вход.** Любая осечка — фото остаётся прежним, в журнал уходит
одна строка с причиной и без персональных данных (ни адреса, ни имени, ни почты).
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from src.db import web_own_profile
from src.db.errors import DbError

from .google_auth import GoogleIdentity

logger = logging.getLogger(__name__)

#: Хост фото: поддомены этого домена, и только они.
AVATAR_HOST_SUFFIX = ".googleusercontent.com"
#: Сколько ждём Google за фото: вход не должен зависеть от его картинок.
AVATAR_TIMEOUT_SECONDS = 3
#: Предел размера (совпадает с ограничением колонки `0065`).
MAX_AVATAR_BYTES = 200 * 1024

JPEG = "image/jpeg"
PNG = "image/png"
WEBP = "image/webp"
ALLOWED_TYPES = frozenset({JPEG, PNG, WEBP})


class AvatarRefused(Exception):
    """Фото не берём. Причина — короткий код для журнала, не данные."""


@dataclass(frozen=True)
class Avatar:
    data: bytes
    content_type: str


def check_url(url: str) -> str:
    """Адрес фото годится для скачивания или `AvatarRefused`."""
    try:
        разобран = urllib.parse.urlsplit(url)
        хост = (разобран.hostname or "").lower()
        порт = разобран.port
    except ValueError as сбой:
        raise AvatarRefused("адрес не разбирается") from сбой
    if разобран.scheme != "https":
        raise AvatarRefused("не https")
    if разобран.username is not None or разобран.password is not None:
        raise AvatarRefused("в адресе учётные данные")
    if порт not in (None, 443):
        raise AvatarRefused("чужой порт")
    if not хост.endswith(AVATAR_HOST_SUFFIX) or хост == AVATAR_HOST_SUFFIX[1:]:
        raise AvatarRefused("хост не googleusercontent.com")
    return url


def sniff_type(data: bytes) -> str | None:
    """Тип картинки по первым байтам; незнакомое — `None`."""
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редирект — отказ: он мог бы увести на хост, который мы не проверяли."""

    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):  # type: ignore[no-untyped-def]
        raise AvatarRefused("редирект")


def _open(url: str) -> tuple[str, bytes]:
    """Скачать: заголовок типа и не более `MAX_AVATAR_BYTES + 1` байт. Отдельно — для тестов."""
    открывальщик = urllib.request.build_opener(_NoRedirect)
    # Адрес уже прошёл `check_url`: https и хост Google, других схем здесь нет.
    запрос = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "image/jpeg,image/png,image/webp"}
    )
    with открывальщик.open(запрос, timeout=AVATAR_TIMEOUT_SECONDS) as ответ:
        if ответ.status != 200:
            raise AvatarRefused("ответ не 200")
        заголовок = (ответ.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return заголовок, ответ.read(MAX_AVATAR_BYTES + 1)


def fetch_avatar(url: str) -> Avatar:
    """Адрес из токена → фото, прошедшее все проверки. Иначе `AvatarRefused`."""
    check_url(url)
    try:
        заголовок, данные = _open(url)
    except AvatarRefused:
        raise
    except (urllib.error.URLError, OSError, ValueError) as сбой:
        raise AvatarRefused(f"скачать не удалось: {type(сбой).__name__}") from сбой
    if заголовок not in ALLOWED_TYPES:
        raise AvatarRefused("заголовок типа не картинка")
    if not данные or len(данные) > MAX_AVATAR_BYTES:
        raise AvatarRefused("пусто или больше предела")
    тип = sniff_type(данные)
    if тип is None or тип != заголовок:
        raise AvatarRefused("сигнатура байт не картинка или не тот тип")
    return Avatar(data=данные, content_type=тип)


def remember(token: str, identity: GoogleIdentity) -> None:
    """Записать имя и фото своей учётке (по токену живой сессии). Никогда не бросает.

    Вызывается ПОСЛЕ того, как вход или привязка уже состоялись: что бы здесь ни
    случилось, человек остаётся вошедшим.
    """
    фото: Avatar | None = None
    if identity.picture:
        try:
            фото = fetch_avatar(identity.picture)
        except AvatarRefused as отказ:
            logger.info("Google: фото не взято — %s", отказ)
        except Exception as сбой:
            # Только тип сбоя: текст исключения и трассировка несут адрес фото.
            logger.warning("Google: фото не взято — непредвиденный сбой %s", type(сбой).__name__)
    if not identity.name and фото is None:
        return
    try:
        web_own_profile.save_google_profile(
            token,
            name=identity.name or None,
            avatar=фото.data if фото else None,
            avatar_type=фото.content_type if фото else None,
        )
    except DbError as сбой:
        logger.warning("Google: имя и фото не записаны — отказ базы (%s)", type(сбой).__name__)
