"""Токены API `/api/v1` для сервисов: выпустить, перечислить, отозвать (#567, D336).

Запускается `make api-token ARGS="..."`. Работает ролью повышенных полномочий —
той же, что заводит учётки админки (`DATABASE_RETRACTION_URL`, без неё —
`DATABASE_ADMIN_URL`); роль приложения выпускать токены не может (миграция
`0041`). Первой строкой команда называет базу, куда пишет, без пароля.

**Значение токена печатается ОДИН раз** — при выпуске, отдельной строкой. В базе
только отпечаток SHA-256; потерянный токен не восстанавливается — выпускается
новый, старый отзывается. Ротация так и делается: `issue` → заменить секрет у
потребителя → `revoke` старого. Перезапуск сервера не нужен.

    .venv/bin/python tools/api_token.py issue swarm --scope ratings:read \
        --scope inspections:read --by <кто>
    .venv/bin/python tools/api_token.py list
    .venv/bin/python tools/api_token.py revoke <id> --by <кто>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import api_tokens  # noqa: E402
from src.db.database_target import managing_target  # noqa: E402
from src.db.errors import DbError  # noqa: E402


def _issue(args: argparse.Namespace) -> int:
    выпущен = api_tokens.issue(args.consumer, scopes=args.scope, by=args.by)
    print(f"Токен выпущен: id {выпущен.id} · {выпущен.consumer} · {', '.join(выпущен.scopes)}")
    print("Значение показано ОДИН раз — в базе только отпечаток. Сохраните его в секреты")
    print("потребителя сразу; потерянный токен не восстанавливается, выпускается новый.")
    print("")
    print(выпущен.value)
    print("")
    return 0


def _list() -> int:
    строки = api_tokens.list_tokens()
    if not строки:
        print("Токенов API нет")
        return 0
    for с in строки:
        метка = f"отозван {с.revoked_at:%Y-%m-%d} ({с.revoked_by})" if с.revoked_at else "живой"
        был = f"{с.last_used_at:%Y-%m-%d %H:%M}" if с.last_used_at else "не использовался"
        print(
            f"{с.id}  {с.consumer:<12} {','.join(с.scopes):<30} {метка:<28} "
            f"выпустил {с.issued_by} {с.issued_at:%Y-%m-%d} · последний вызов {был}"
        )
    return 0


def _revoke(args: argparse.Namespace) -> int:
    if not api_tokens.revoke(args.id, by=args.by):
        print(f"Живого токена {args.id} нет — уже отозван или такого не выпускали")
        return 1
    print(f"Токен {args.id} отозван. Следующий запрос с ним получит 401")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="api_token", description="Токены API /api/v1 (#567)")
    команды = parser.add_subparsers(dest="command", required=True)
    выпустить = команды.add_parser("issue", help="выпустить токен потребителю")
    выпустить.add_argument("consumer", help="имя сервиса латиницей, например swarm")
    выпустить.add_argument(
        "--scope",
        action="append",
        required=True,
        choices=api_tokens.SCOPES,
        help="право токена; ключ повторяется для нескольких",
    )
    выпустить.add_argument("--by", required=True, help="кто выпускает — для следа")
    команды.add_parser("list", help="перечислить токены (без значений)")
    отозвать = команды.add_parser("revoke", help="отозвать токен по id из list")
    отозвать.add_argument("id")
    отозвать.add_argument("--by", required=True, help="кто отзывает — для следа")
    args = parser.parse_args(argv)
    try:
        print(f"Токены API: {managing_target()}")
        if args.command == "issue":
            return _issue(args)
        if args.command == "list":
            return _list()
        return _revoke(args)
    except DbError as exc:
        print(f"Не вышло: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
