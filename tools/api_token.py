"""Сервисные токены внешнего API: выпустить, перечислить, отозвать (D356, D388).

Первый потребитель — Swarm (`/api/v1/*`, #567, D387). Работает под той же
ролью, что заводит учётки (`tools/web_user.py`): администратор истории
(`DATABASE_RETRACTION_URL`), а без неё — владелец схемы. Роль приложения
выпускать токены не может (миграция `0049`).

**Токен печатается ОДИН раз** — в базе только его отпечаток SHA-256. Потерян —
выпустить новый и отозвать прежний. Ротация так и делается, без правки кода и
без перезапуска веба.

Запуск (из корня репозитория):

    .venv/bin/python tools/api_token.py issue swarm --scope ratings:scores,maps:ratings
    .venv/bin/python tools/api_token.py list
    .venv/bin/python tools/api_token.py revoke 3
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.api_access import SCOPES, issue, list_tokens, revoke  # noqa: E402
from src.db.database_target import managing_target  # noqa: E402
from src.db.errors import DbError  # noqa: E402


def _who() -> str:
    """Кто выпускает или отзывает — для следа в базе. Имя пользователя машины."""
    return os.environ.get("API_TOKEN_BY") or getpass.getuser()


def _scopes(raw: str) -> tuple[str, ...]:
    return tuple(часть.strip() for часть in raw.split(",") if часть.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="api_token", description="Токены внешнего API (D388)")
    команды = parser.add_subparsers(dest="command", required=True)
    выпустить = команды.add_parser("issue", help="выпустить токен")
    выпустить.add_argument("consumer", help="кто ходит токеном, например swarm")
    выпустить.add_argument(
        "--scope", required=True, help=f"права через запятую: {', '.join(SCOPES)}"
    )
    команды.add_parser("list", help="перечислить токены, включая отозванные")
    отозвать = команды.add_parser("revoke", help="отозвать токен по номеру")
    отозвать.add_argument("id", type=int)
    args = parser.parse_args(argv)

    try:
        print(f"Токены: {managing_target()}")
        if args.command == "issue":
            выпущен = issue(args.consumer, _scopes(args.scope), by=_who())
            print(f"Выпущен токен №{выпущен.id} · {выпущен.consumer} · {', '.join(выпущен.scopes)}")
            print("")
            print(f"  {выпущен.value}")
            print("")
            print("  Токен показан ОДИН раз — в базе только отпечаток. Положите его в секреты")
            print("  потребителя сразу; потерян — выпустите новый и отзовите этот.")
            return 0
        if args.command == "list":
            for т in list_tokens():
                состояние = (
                    f"отозван {т.revoked_at:%Y-%m-%d %H:%M} ({т.revoked_by})"
                    if т.revoked_at
                    else "живой"
                )
                print(
                    f"№{т.id} · {т.consumer} · {', '.join(т.scopes)} · "
                    f"выпущен {т.issued_at:%Y-%m-%d %H:%M} ({т.issued_by}) · {состояние}"
                )
            return 0
        if revoke(args.id, by=_who()):
            print(f"Токен №{args.id} отозван: с этой минуты он получает 401")
            return 0
        print(f"Живого токена №{args.id} нет")
        return 1
    except DbError as exc:
        print(f"Отказ: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
