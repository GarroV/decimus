"""Перенос нынешнего входа в Dodo IS в базу — разовый, по одной стране (D640, #951).

JSON входа читается из stdin (поля `access_token`, `refresh_token`, `expires_in`, `scope`,
`obtained_at`), страна и логин владельца, который переносит вход, — из аргументов:

    python tools/dodois_import.py --country SI --by owner < token.json

Вход пишется как обычный (ключи — шифрованно в `vault.secrets`, заменяет прежний вход
страны), «кто подтвердил» у такого входа — «владелец». Если ключ доступа к этому часу уже
истёк, вход сразу продлевается (нужны ключи приложения Dodo IS), затем идёт проверка.

**Печатает только состояние и «открыто X из Y».** Значения ключей — никогда: ни при успехе,
ни в сообщениях об ошибках (исключения здесь называются типом, не текстом).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db import dodois_logins
from src.db.errors import DbError
from src.db.space import SYSTEM_SPACE, acting_space
from src.dodois import service
from src.dodois.client import TokenPair
from src.domain import dodois as rules

EXIT_OK, EXIT_BAD_INPUT, EXIT_FAILED = 0, 2, 1


class BadInput(Exception):
    """Вход не разобрался. Текст — без значений из входа."""


def _moment(raw: Any) -> datetime:
    """`obtained_at`: ISO-строка или число секунд от эпохи; без пояса — UTC."""
    if isinstance(raw, bool) or raw is None:
        raise BadInput("obtained_at: нужна дата")
    if isinstance(raw, int | float):
        return datetime.fromtimestamp(raw, UTC)
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise BadInput("obtained_at: не дата") from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def parse(raw_json: str) -> tuple[TokenPair, datetime]:
    """Пара ключей и момент, когда истекает ключ доступа. Ошибка — `BadInput` без значений."""
    try:
        data = json.loads(raw_json)
    except ValueError:
        raise BadInput("на входе не JSON") from None
    if not isinstance(data, dict):
        raise BadInput("на входе не объект JSON")
    for field in ("access_token", "refresh_token"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise BadInput(f"нет поля {field}")
    expires_in = data.get("expires_in")
    if isinstance(expires_in, bool) or not isinstance(expires_in, int | float) or expires_in <= 0:
        raise BadInput("expires_in: нужно положительное число секунд")
    obtained = _moment(data.get("obtained_at"))
    scope = data.get("scope")
    pair = TokenPair(
        access=data["access_token"].strip(),
        refresh=data["refresh_token"].strip(),
        expires_in=int(expires_in),
        scope=scope if isinstance(scope, str) and scope else None,
    )
    return pair, obtained + timedelta(seconds=pair.expires_in)


def run(country: str, by: str, raw_json: str, *, now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    if not rules.is_country(country):
        print("страна: две заглавные латинские буквы", file=sys.stderr)
        return EXIT_BAD_INPUT
    if not by.strip():
        print("--by: нужен логин владельца", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        pair, expires_at = parse(raw_json)
    except BadInput as exc:
        print(f"вход: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        with acting_space(SYSTEM_SPACE):
            login = service.attach(
                country=country,
                pair=pair,
                issued_by=by.strip(),
                source=rules.SOURCE_IMPORT,
                invite_id=None,
                now=moment,
                account=(None, None),
                access_expires_at=expires_at,
                verify=expires_at > moment,
            )
            if expires_at <= moment:
                creds = service.credentials()
                if creds is None:
                    print("ключ доступа истёк, а ключей приложения Dodo IS нет", file=sys.stderr)
                    return EXIT_FAILED
                fresh = dodois_logins.get_login(country) or login
                if service.refresh(fresh, creds, now=moment):
                    login = service.check(country, now=moment) or fresh
            login = dodois_logins.get_login(country) or login
    except DbError as exc:
        print(f"база: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILED
    total = "?" if login.units_total is None else str(login.units_total)
    opened = "?" if login.units_open is None else str(login.units_open)
    print(f"{country}: состояние {login.state}, открыто {opened} из {total}")
    return EXIT_OK if login.state in (rules.OK, rules.PARTIAL) else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--country", required=True, help="код страны, например SI")
    args.add_argument("--by", required=True, help="логин владельца, переносящего вход")
    parsed = args.parse_args(argv)
    return run(parsed.country, parsed.by, sys.stdin.read())


if __name__ == "__main__":
    sys.exit(main())
