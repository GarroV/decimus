"""Запрет на вход: показать запертых и снять запрет. Запускается `make web-unlock`.

**ЗАЧЕМ ЭТА КОМАНДА ЕСТЬ** (T328, решение D158). Ограничитель перебора запирает
вход после серии неудач, и до T328 запрет проходил только по времени. Значит,
посторонний, знающий логин администратора, держал его запертым сколь угодно
долго: одна неудачная попытка раз в час — и счётчик не успевает забыться, а
пароль для этого не нужен вовсе. Команда возвращает человеку доступ, не дожидаясь
часа и не трогая учётку.

**РАБОТАЕТ ПОД РОЛЬЮ АДМИНИСТРАТОРА ИСТОРИИ** (`DATABASE_RETRACTION_URL`) — той
же, что снимает проверку. Не под ролью приложения: снятие запрета — действие
человека из команды, а не шаг продуктового сценария, и подключение у него своё.

**ЗАПЕРТЫЙ АДРЕС И ЗАПЕРТЫЙ ЛОГИН — РАЗНЫЕ ЗАПРЕТЫ.** Их и снимать нужно
раздельно: человек за запертым адресом не войдёт и с открытым логином.

Запуск (из корня репозитория):

    .venv/bin/python tools/web_unlock.py list --tenant demo
    .venv/bin/python tools/web_unlock.py unlock director --tenant demo
    .venv/bin/python tools/web_unlock.py unlock-address 203.0.113.7 --tenant demo
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Файл окружения читается до импорта дверей — как у `tools/web_user.py`: без
# него команда не видит ни `DATABASE_RETRACTION_URL`, ни `WEB_TENANT`, и
# объясняет это отказом подключения вместо «окружение не прочитано».
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.errors import DbError  # noqa: E402
from src.db.web_unlock import Key, counters, unlock_address, unlock_login  # noqa: E402
from src.web.config import WEB_TENANT_VAR  # noqa: E402


def _tenant(argument: str | None) -> str:
    """Арендатор: из аргумента или из окружения стенда. Умолчания нет.

    Тот же помощник и та же причина, что в `tools/web_user.py`: подставленный
    «default» снял бы запрет не у того арендатора, а человек остался бы ждать
    своего. Общий модуль тут не заводится намеренно — `src/` про продукт, а
    десять строк разбора аргументов у двух команд дешевле, чем функция в
    продукте, которую продукт не зовёт.
    """
    tenant = (argument or os.environ.get(WEB_TENANT_VAR) or "").strip()
    if not tenant:
        raise SystemExit(
            f"Не задан арендатор: передайте --tenant или {WEB_TENANT_VAR} в окружении. "
            f"У кого снимать запрет — не додумывается"
        )
    return tenant


def _строка(ключ: Key) -> str:
    """Одна строка списка: чей ключ, сколько неудач, заперт ли и насколько."""
    чей = ключ.login or f"{ключ.fingerprint[:12]}…"
    состояние = f"заперт ещё {ключ.verdict.retry_after_minutes} мин" if ключ.locked else "не заперт"
    return (
        f"{ключ.scope:<8} {чей:<24} {ключ.counter.failures:>3} неудач  {состояние:<20}"
        f"последняя {ключ.counter.updated_at:%Y-%m-%d %H:%M}"
    )


def _list(tenant: str) -> int:
    ключи = counters(tenant=tenant)
    if not ключи:
        print(f"У арендатора {tenant} неудачных попыток не числится — запирать нечего")
        return 0
    заперто = [ключ for ключ in ключи if ключ.locked]
    for ключ in ключи:
        print(_строка(ключ))
    print("")
    if not заперто:
        print("Запертых сейчас нет: все счётчики ниже порога или их срок уже прошёл")
    else:
        print(f"Заперто ключей: {len(заперто)}")
        # Логин не узнан — значит, учётки с таким логином у арендатора нет.
        # Это не ошибка команды: перебирают и несуществующие логины.
        print("Снять: unlock <логин>  или  unlock-address <адрес>")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="web_unlock", description="Запрет на вход в админку: показать и снять (T328)"
    )
    команды = parser.add_subparsers(dest="command", required=True)

    def с_арендатором(имя: str, help: str) -> argparse.ArgumentParser:
        """Подкоманда с `--tenant` у самой себя, а не у корня.

        Та же причина, что в `tools/web_user.py`: у корня ключ принимался бы
        только ПЕРЕД именем подкоманды, а пишут его после.
        """
        под = команды.add_parser(имя, help=help)
        под.add_argument("--tenant", help=f"код арендатора; по умолчанию {WEB_TENANT_VAR}")
        return под

    с_арендатором("list", "показать счётчики попыток: кто заперт и насколько")
    по_логину = с_арендатором("unlock", "снять запрет с логина")
    по_логину.add_argument("login")
    по_адресу = с_арендатором("unlock-address", "снять запрет с адреса")
    по_адресу.add_argument("address")

    args = parser.parse_args(argv)
    tenant = _tenant(args.tenant)

    try:
        if args.command == "list":
            return _list(tenant)
        if args.command == "unlock":
            снято = unlock_login(tenant=tenant, login=args.login)
            if not снято:
                print(f"За логином «{args.login}» у арендатора {tenant} неудач не числится")
                return 1
            print(f"Запрет снят: {args.login} · арендатор {tenant}. Вход открыт сразу")
            return 0
        снято = unlock_address(tenant=tenant, address=args.address)
        if not снято:
            print(f"За адресом {args.address} у арендатора {tenant} неудач не числится")
            return 1
        print(f"Запрет снят: адрес {args.address} · арендатор {tenant}. Вход открыт сразу")
        return 0
    except DbError as exc:
        # Отказ печатается строкой, а не трассировкой: человеку нужна причина и
        # имя переменной, а не стек.
        print(f"Не вышло: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
