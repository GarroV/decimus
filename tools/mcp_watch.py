"""Сторож доступности MCP снаружи (#243).

**Зачем отдельно от healthcheck контейнера.** 15.09.2026 продукт был
недоступен снаружи, а на площадке всё выглядело здоровым: `mcp` — `healthy`,
звено — `running`. Рвалось на публикации порта, и обнаружил это владелец
собой, попытавшись подключиться. Проверять надо ПУТЬ ЦЕЛИКОМ и снаружи, иначе
проверка сторожит не то.

**Почему без токена.** Сторожу не нужен доступ к истории проверок — ему нужно
знать, что дверь на месте и заперта. Отказ `401` на запрос без токена — это и
есть здоровая дверь; молчание, `502` или сорванное соединение — нет. Так
сторож не носит с собой секрета, который пришлось бы хранить в CI.

**Адрес приходит окружением** (`MCP_PUBLIC_URL`) и в вывод не печатается:
репозиторий публичный, а адрес площадки — инфраструктурное имя.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

#: Сколько ждём ответа. Площадка — ноутбук за туннелем: десять секунд это
#: «спит или отвалился», а не «задумался».
TIMEOUT_SEC = 15

#: Что считается здоровой дверью на запрос БЕЗ токена.
EXPECTED_RPC_STATUS = 401

#: Путь установщика — единственная публичная поверхность сервера.
INSTALL_PATH = "/setup"


class WatchError(RuntimeError):
    """Продукт снаружи недоступен или отвечает не тем."""


def _status(адрес: str, *, тело: bytes | None = None) -> int:
    запрос = urllib.request.Request(  # noqa: S310
        адрес,
        data=тело,
        headers={"Content-Type": "application/json"} if тело else {},
    )
    try:
        with urllib.request.urlopen(запрос, timeout=TIMEOUT_SEC) as ответ:  # noqa: S310
            return int(ответ.status)
    except urllib.error.HTTPError as отказ:
        return int(отказ.code)
    except Exception as отказ:  # сеть, TLS, таймаут, сорванное соединение
        raise WatchError(f"адрес не ответил: {type(отказ).__name__}") from отказ


def check(адрес: str) -> list[str]:
    """Проверить дверь и установщик. Возвращает строки отчёта или бросает отказ."""
    база = адрес.rstrip("/")
    отчёт = []

    код = _status(f"{база}/", тело=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')
    if код != EXPECTED_RPC_STATUS:
        raise WatchError(f"дверь отвечает {код}, а не {EXPECTED_RPC_STATUS} — путь снаружи оборван")
    отчёт.append(f"дверь заперта (без токена {код})")

    код = _status(f"{база}{INSTALL_PATH}")
    if код != 200:
        raise WatchError(f"установщик отвечает {код}, а не 200 — подключиться никто не сможет")
    отчёт.append(f"установщик отдаётся ({код})")

    return отчёт


def main() -> int:
    адрес = (os.environ.get("MCP_PUBLIC_URL") or "").strip()
    if not адрес:
        print("не задан MCP_PUBLIC_URL — сторожу нечего проверять", file=sys.stderr)
        return 2
    try:
        for строка in check(адрес):
            print(строка)
    except WatchError as отказ:
        # Адрес в сообщение не подставляется намеренно: репозиторий публичный.
        print(f"MCP СНАРУЖИ НЕДОСТУПЕН: {отказ}", file=sys.stderr)
        return 1
    print("ДОСТУПЕН СНАРУЖИ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
