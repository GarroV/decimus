"""Пространства и их страны: завести, привязать к странам, перечислить. `make space`.

Пространство — новый заказчик (УК или партнёр), а не новый сотрудник, поэтому
продукт его не заводит: только эта команда, под ролью владельца схемы
(`DATABASE_ADMIN_URL`). Правила кода и стран — в `src/db/spaces.py`.

Запуск (из корня репозитория):

    .venv/bin/python tools/space.py add GE --name "Партнёр Грузия"
    .venv/bin/python tools/space.py countries GE GE
    .venv/bin/python tools/space.py list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Окружение — до импорта дверей, как у `tools/web_user.py`: без него команда не
# видит `DATABASE_ADMIN_URL` и объясняет это отказом подключения.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.errors import DbError  # noqa: E402
from src.db.spaces import bind_countries, create_space, list_spaces  # noqa: E402


def _list() -> int:
    for s in list_spaces():
        страны = ", ".join(s.countries) or "—"
        print(f"{s.code}\t{s.name or '—'}\tстраны: {страны}\tучёток: {s.people}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="space", description="Пространства и их страны (#340)")
    команды = parser.add_subparsers(dest="command", required=True)
    завести = команды.add_parser("add", help="завести пространство")
    завести.add_argument("code", help="код: заглавная латиница, например GE")
    завести.add_argument("--name", required=True, help="название для людей")
    страны = команды.add_parser("countries", help="привязать пространство партнёра к странам")
    страны.add_argument("code")
    страны.add_argument("countries", nargs="+", help="коды стран ISO, например GE AM")
    команды.add_parser("list", help="перечислить пространства")
    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            заведено = create_space(args.code, name=args.name)
            print(f"Пространство заведено: {заведено.code} · {заведено.name}")
            return 0
        if args.command == "countries":
            итог = bind_countries(args.code, tuple(args.countries))
            print(f"Страны пространства {args.code}: {', '.join(итог)}")
            return 0
        return _list()
    except DbError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
