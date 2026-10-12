"""Языки отчёта по странам (D415): перечень — данные, а не код.

Файл `report_langs.json` в каталоге методики:

```json
{"default": ["ru", "en"], "countries": {"RS": ["ru", "en"], "GE": ["en"]}}
```

* `default` — перечень для страны, которой в `countries` нет или которая
  неизвестна;
* `countries` — код страны ISO 3166-1 alpha-2 → список языков отчёта.

Новая страна или язык — строка в файле, не релиз. Считаются только языки из
`TEXT_LANGS`: отчёт можно напечатать лишь на том, на котором заведена методика.
Неизвестный язык пропускается со строкой в журнал, а не отказом: из-за опечатки
в справочнике аудитор не должен остаться на точке без отчёта. Если после
пропуска перечень пуст, берётся перечень по умолчанию, а если и он пуст, то все
`TEXT_LANGS` — выбор из нуля вариантов человеку предложить нечем.

Файла нет — перечень по умолчанию, `ru` и `en`: это законное состояние (так
работает методика, у которой отдельных правил для стран нет).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import check_environment
from .errors import ConfigError
from .geo import CITY_COUNTRY
from .models import TEXT_LANGS

logger = logging.getLogger(__name__)

REPORT_LANGS_FILE = "report_langs.json"

#: Перечень, когда файла нет совсем.
FALLBACK_LANGS: tuple[str, ...] = ("ru", "en")


def _clean(value: Any, where: str) -> list[str]:
    """Оставить из списка только языки методики, без повторов, в заданном порядке."""
    if not isinstance(value, list):
        logger.warning("%s: ожидался список языков, а лежит %r — пропущено", where, value)
        return []
    out: list[str] = []
    for raw in value:
        code = str(raw).strip().lower()
        if code not in TEXT_LANGS:
            logger.warning("%s: язык «%s» в методике не заведён — пропущен", where, raw)
        elif code not in out:
            out.append(code)
    return out


def load(data_dir: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Прочитать файл: перечень по умолчанию и перечни стран. Файла нет — запасной перечень."""
    path = data_dir / REPORT_LANGS_FILE
    if not path.is_file():
        return list(FALLBACK_LANGS), {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Языки отчёта по странам {path} не читаются: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Языки отчёта по странам {path}: ожидался объект с default и countries")
    default = _clean(raw.get("default"), f"{REPORT_LANGS_FILE}: default") or list(TEXT_LANGS)
    countries_raw = raw.get("countries") or {}
    if not isinstance(countries_raw, dict):
        raise ConfigError(f"Языки отчёта по странам {path}: countries должен быть объектом")
    countries: dict[str, list[str]] = {}
    for code, langs in countries_raw.items():
        cleaned = _clean(langs, f"{REPORT_LANGS_FILE}: {code}")
        if cleaned:
            countries[str(code).strip().upper()] = cleaned
    return default, countries


def report_langs_for(country: str | None, *, data_dir: Path | None = None) -> list[str]:
    """Языки отчёта для страны (ISO 3166-1 alpha-2). Страны нет или не названа — по умолчанию."""
    default, countries = load(data_dir or check_environment().data_dir)
    return list(countries.get((country or "").strip().upper(), default))


def country_of_city(city: str) -> str | None:
    """Страна города по коду источника (`tbilisi`). Регистр и края не важны."""
    return CITY_COUNTRY.get((city or "").strip().lower())
