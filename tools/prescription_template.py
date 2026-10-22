"""Шаблон предписания: загрузить новую версию из файла или показать действующую.

Реальный текст (юрлицо франчайзора, адрес, регистрация, номера пунктов договора)
в репозиторий не кладётся — он публичный. Встроенный шаблон обезличен и годится
как заготовка (`show` без версии в базе печатает его). Настоящий текст загружается
в базу этой командой, под ролью администратора истории (`DATABASE_RETRACTION_URL`,
иначе `DATABASE_ADMIN_URL`): каждая загрузка — новая версия, прежние не правятся,
а предписание помнит ту версию, по которой собрано.

Запуск (из корня репозитория):

    .venv/bin/python tools/prescription_template.py set --file <путь> \\
        --kind prescription_inspection --lang en
    .venv/bin/python tools/prescription_template.py show \\
        --kind prescription_inspection --lang en [--version 2]

Подстановки шаблона — `src/report/notice_template.py`; неизвестная подстановка —
отказ до записи.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv

# Окружение — до импорта дверей, как у `tools/space.py`.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import mail_templates  # noqa: E402
from src.db.errors import DbError  # noqa: E402
from src.report import notice_template  # noqa: E402
from src.report.errors import ReportError  # noqa: E402

#: Виды, у которых есть разбор подстановок. Остальные виды заведены в базе, но
#: инструмент их пока не принимает (шаги 5–6 спеки).
KINDS = (notice_template.TEMPLATE_KIND,)


def _show(kind: str, lang: str, version: int | None) -> int:
    found = mail_templates.versions(kind, lang)
    if version is not None:
        found = tuple(v for v in found if v.version == version)
        if not found:
            print(f"Версии {version} вида {kind}/{lang} в базе нет", file=sys.stderr)
            return 1
    if not found:
        print("# В базе версий нет — встроенный обезличенный шаблон (версия не записана)\n")
        print(notice_template.BUILTIN_PRESCRIPTION_INSPECTION)
        return 0
    top = found[0]
    stamp = f"{top.created_at:%Y-%m-%d %H:%M}"
    print(f"# {top.kind}/{top.lang} версия {top.version}, {top.created_by}, {stamp}\n")
    print(top.body)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prescription_template", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("set", help="загрузить новую версию шаблона из файла")
    put.add_argument("--file", required=True, type=Path, help="текстовый файл шаблона (UTF-8)")
    put.add_argument("--actor", default="", help="кто загружает (по умолчанию — пользователь ОС)")
    show = commands.add_parser("show", help="показать действующую (или названную) версию")
    show.add_argument("--version", type=int, default=None)
    for sub in (put, show):
        sub.add_argument("--kind", required=True, choices=KINDS)
        sub.add_argument("--lang", required=True, help="двухбуквенный язык, например en")
    args = parser.parse_args(argv)

    try:
        if args.command == "show":
            return _show(args.kind, args.lang, args.version)
        try:
            text = args.file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Файл не прочитан: {type(exc).__name__}", file=sys.stderr)
            return 1
        notice_template.check_template(text)
        saved = mail_templates.add_version(
            args.kind, args.lang, text, actor=args.actor or getpass.getuser()
        )
        print(f"Загружено: {saved.kind}/{saved.lang} версия {saved.version}")
        return 0
    except (DbError, ReportError) as exc:
        print(f"Не вышло: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
