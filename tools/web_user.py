"""Учётки веб-админки: завести, перечислить, отключить. Запускается `make web-user`.

**Это и есть «учётки заводит команда проекта».** Регистрации снаружи у админки
нет и не будет (D155): круг узкий — сотрудники управляющей компании, — и
появляется в нём человек тем, что кто-то из команды выполнил эту команду.

Работает под ролью ВЛАДЕЛЬЦА СХЕМЫ (`DATABASE_ADMIN_URL`), потому что роль
приложения таких прав не имеет вовсе (миграция `0014`). Это не неудобство, а
смысл разделения: получив базу продукта, чужой не заведёт себе учётку.

**Пароль в репозитории не лежит и в командной строке не передаётся.** Он
спрашивается вводом без эха, а для неинтерактивного запуска берётся из
переменной `WEB_USER_PASSWORD`. Причина простая: аргумент командной строки
виден в `ps` любому на машине и остаётся в истории оболочки навсегда.

Запуск (из корня репозитория):

    .venv/bin/python tools/web_user.py add director --tenant demo
    .venv/bin/python tools/web_user.py list --tenant demo
    .venv/bin/python tools/web_user.py disable director --tenant demo
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

# Файл окружения читается до импорта дверей — как у `src/web/__main__.py`:
# без него команда не видит ни `DATABASE_ADMIN_URL`, ни `WEB_TENANT`, и
# объясняет это отказом подключения вместо «окружение не прочитано».
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.errors import DbError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    ROLES,
    change_password,
    create_account,
    disable_account,
    list_accounts,
    set_role,
)
from src.web.config import WEB_TENANT_VAR  # noqa: E402

#: Пароль для неинтерактивного запуска. Существует ради разворачивания стенда
#: скриптом; на живой площадке учётку заводят руками, и тогда пароль спрашивают.
PASSWORD_VAR = "WEB_USER_PASSWORD"  # noqa: S105 — имя переменной, а не значение


def _tenant(argument: str | None) -> str:
    """Арендатор: из аргумента или из окружения стенда. Умолчания нет.

    Та же причина, что у `WEB_TENANT` в самой админке: подставленный «default»
    завёл бы учётку не тому арендатору и открыл бы ей чужую историю.
    """
    tenant = (argument or os.environ.get(WEB_TENANT_VAR) or "").strip()
    if not tenant:
        raise SystemExit(
            f"Не задан арендатор: передайте --tenant или {WEB_TENANT_VAR} в окружении. "
            f"Чью историю откроет эта учётка — не додумывается"
        )
    return tenant


def _password() -> str:
    """Пароль: из окружения или вводом без эха. Из аргументов — никогда."""
    из_окружения = os.environ.get(PASSWORD_VAR)
    if из_окружения:
        return из_окружения
    if not sys.stdin.isatty():
        raise SystemExit(
            f"Пароль спросить не у кого: запуск неинтерактивный. Передайте его "
            f"переменной {PASSWORD_VAR} — в аргументах командной строки пароль не "
            f"принимается, он виден в `ps` и остаётся в истории оболочки"
        )
    первый = getpass.getpass(f"Пароль (не короче {MIN_PASSWORD_LENGTH} знаков): ")
    второй = getpass.getpass("Ещё раз: ")
    if первый != второй:
        raise SystemExit("Пароли не совпали — ничего не изменено")
    return первый


#: Логин учётки стенда. Один и тот же, чтобы человек не гадал, чем входить;
#: пароль при этом каждый раз новый — постоянный лежал бы в репозитории.
STAND_LOGIN = "director"


def _ensure(tenant: str) -> int:
    """Учётка стенда: завести, если её нет, и напечатать пароль ОДИН раз.

    Нужно затем, что `make web-up` обязан оставаться одной командой: после
    T323 стенд без учётки открывается формой входа, войти в которую нечем, и
    это выглядит как поломка, а не как «учётку заводят руками».

    Пароль делается случайным и печатается на экран, а НЕ кладётся в
    репозиторий: постоянный пароль стенда — это пароль, известный всем, кто
    когда-либо видел исходники. Повторный запуск учётку не трогает и пароля не
    показывает — показать его второй раз нечем, в базе его нет.
    """
    if list_accounts(tenant=tenant):
        print(f"Учётки арендатора {tenant} уже заведены — вход прежний")
        return 0
    пароль = secrets.token_urlsafe(12)
    create_account(STAND_LOGIN, tenant=tenant, password=пароль)
    print("")
    print(f"  Учётка стенда: {STAND_LOGIN} / {пароль}")
    print("  Пароль показан ОДИН раз — в базе его нет, только необратимая свёртка.")
    print(f'  Забыли — заведите новую: make web-user ARGS="add <логин> --tenant {tenant}"')
    print("")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="web_user", description="Учётки веб-админки (T323)")
    команды = parser.add_subparsers(dest="command", required=True)

    def с_арендатором(имя: str, help: str) -> argparse.ArgumentParser:
        """Подкоманда с `--tenant` у самой себя, а не у корня.

        Это не вкусовщина: у корня ключ принимался бы ТОЛЬКО перед именем
        подкоманды (`--tenant demo add director`), а пишут его после — и
        argparse отвечает на это «unrecognized arguments», из которого не
        видно, что именно не так. Поймано первым же запуском.
        """
        под = команды.add_parser(имя, help=help)
        под.add_argument("--tenant", help=f"код арендатора; по умолчанию {WEB_TENANT_VAR}")
        return под

    завести = с_арендатором("add", "завести учётку")
    завести.add_argument("login")
    с_арендатором("ensure", "завести учётку стенда, если её ещё нет")
    с_арендатором("list", "перечислить учётки арендатора")
    сменить = с_арендатором("password", "сменить пароль учётке")
    сменить.add_argument("login")
    отключить = с_арендатором("disable", "отключить учётку")
    отключить.add_argument("login")
    # Роль назначается отдельной командой, а не ключом у `add`. Накат `0020`
    # не даёт прав никому, и первым админом стенда кого-то делает именно
    # она — на живом стенде это единственный способ открыть экран учёток.
    роль = с_арендатором("role", "назначить роль учётке")
    роль.add_argument("login")
    роль.add_argument("role", choices=ROLES, help="что человеку можно в админке")

    args = parser.parse_args(argv)
    tenant = _tenant(args.tenant)

    try:
        if args.command == "add":
            account = create_account(args.login, tenant=tenant, password=_password())
            print(f"Учётка заведена: {account.login} · арендатор {account.tenant}")
            return 0
        if args.command == "ensure":
            return _ensure(tenant)
        if args.command == "password":
            сменено = change_password(args.login, tenant=tenant, password=_password())
            if not сменено:
                print(f"Живой учётки «{args.login}» у арендатора {tenant} нет")
                return 1
            print(
                f"Пароль сменён: {args.login}. Сессии, открытые по прежнему паролю, "
                f"закрыты — вошедший по нему вылетел"
            )
            return 0
        if args.command == "role":
            назначено = set_role(args.login, tenant=tenant, role=args.role)
            if not назначено:
                print(f"Живой учётки «{args.login}» у арендатора {tenant} нет")
                return 1
            print(f"Роль назначена: {args.login} · {args.role}")
            return 0
        if args.command == "list":
            строки = list_accounts(tenant=tenant)
            if not строки:
                print(f"У арендатора {tenant} учёток нет")
                return 0
            for строка in строки:
                метка = (
                    f"отключена {строка.disabled_at:%Y-%m-%d}" if строка.disabled_at else "работает"
                )
                print(
                    f"{строка.login:<24} {строка.role:<8} {метка:<10} "
                    f"заведена {строка.created_at:%Y-%m-%d}"
                )
            return 0
        отключено = disable_account(args.login, tenant=tenant)
        if not отключено:
            print(f"Живой учётки «{args.login}» у арендатора {tenant} нет")
            return 1
        print(f"Учётка отключена: {args.login}. Открытые по ней сессии перестали действовать")
        return 0
    except DbError as exc:
        # Отказ печатается строкой, а не трассировкой: человеку нужна причина и
        # имя переменной, а не стек.
        print(f"Не вышло: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
