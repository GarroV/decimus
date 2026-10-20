"""Ручная загрузка обучения из iSpring: `python -m src.learning`.

Ключи — из базы (экран «Ключи сервисов»), затем из окружения; нет ключей — отказ с
понятным текстом. Выводит только числа; результаты сотрудников не печатаются.
"""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from src.db import learning_store
from src.db.errors import DbError
from src.db.space import SYSTEM_SPACE, acting_space

from . import keys
from .ispring import IspringError
from .sync import run


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()
    with acting_space(SYSTEM_SPACE):
        client = keys.client()
        if client is None:
            print("Ключи iSpring не заданы: ни в базе, ни в окружении.", file=sys.stderr)
            return 2
        try:
            summary = run(client)
        except (IspringError, DbError) as exc:
            learning_store.log_load(ok=False, error=str(exc))
            print(f"Загрузка не удалась: {exc}", file=sys.stderr)
            return 1
        learning_store.log_load(ok=True, departments=summary.departments, results=summary.results)
    print(
        f"Подразделений {summary.departments}, пиццерий {summary.pizzerias} "
        f"(сопоставлено {summary.matched}), назначений {summary.results}, "
        f"отброшено строк {summary.dropped}, вне разбора {summary.ignored}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
