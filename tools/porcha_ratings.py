"""Порча защит рейтингов: каждая сломанная защита обязана уронить свой тест.

Запуск: `.venv/bin/python tools/porcha_ratings.py` из корня репозитория, с
`DATABASE_URL` тестовой базы, как в `make test`. Каждый случай подменяет одну
строку кода, гоняет ровно её тест и возвращает файл на место. «НЕ ПРИМЕНИЛАСЬ» —
код уехал, и порчу надо обновить: молча зелёный прогон без подмены и есть та
ложь, ради которой скрипт заведён.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`, см. цель `test-honest` в
`Makefile`): порча того же размера в ту же секунду подхватила бы кэш, и тест
«поймал» бы исправный код.
"""

import os
import pathlib
import re
import subprocess
import sys

cases = [
    (
        "src/domain/tenants.py",
        "    return canonical_tenant(tenant) == HQ_TENANT and role in RATINGS_MANAGER_ROLES\n",
        "    return role in RATINGS_MANAGER_ROLES\n",
        "tests/test_ratings_access.py",
    ),
    (
        "src/db/web_access.py",
        "    if role not in roles_for(tenant):\n",
        "    if False:\n",
        "tests/test_db_web_access_control.py::test_контроль_у_партнёра_отказ_кодом",
    ),
    (
        "src/web/app.py",
        "        if not _control_may_write(\n",
        "        if False and not _control_may_write(\n",
        "tests/test_web_users_access.py::test_контроль_вне_рейтингов_не_пишет",
    ),
    (
        "src/web/people.py",
        "    if role not in accounts.roles_for(tenant):",
        "    if role not in accounts.ROLES:",
        "tests/test_web_users_access.py::test_контроль_вне_уК_до_базы_не_доходит",
    ),
    (
        "src/ratings/countries.py",
        'EXCLUDED = frozenset({"RU", "KZ", "UZ"})\n',
        "EXCLUDED = frozenset()\n",
        "tests/test_ratings_formats.py::test_нарушения_ркО_разобраны",
    ),
    (
        "src/ratings/formats.py",
        "    if link.rating_type not in (None, rating_type):\n",
        "    if False:\n",
        "tests/test_ratings_formats.py::test_нарушения_ркО_тип_рейтинга_в_ссылке_чужой",
    ),
    (
        "src/ratings/links.py",
        "    if parts.hostname != RATING_HOST or not parts.fragment:\n",
        "    if not parts.fragment:\n",
        "tests/test_ratings_formats.py::test_испорченная_ссылка_не_разбирается",
    ),
    (
        "src/ratings/formats.py",
        "        backoffice_url=checkup_backoffice_url(checkup_id),\n",
        "        backoffice_url=row[back_col],\n",
        "tests/test_ratings_formats.py::test_ссылки_в_результате_собраны_заново_а_не_из_ячейки",
    ),
    (
        "src/ratings/formats.py",
        "        rating_url=checkup_rating_url(",
        "        rating_url=row[rating_col] or checkup_rating_url(",
        "tests/test_ratings_formats.py::test_ссылки_в_результате_собраны_заново_а_не_из_ячейки",
    ),
    (
        "src/ratings/links.py",
        '    if host != BACKOFFICE_DOMAIN and not host.endswith("." + BACKOFFICE_DOMAIN):\n',
        "    if False:\n",
        "tests/test_ratings_formats.py::test_чужая_ссылка_бэкофиса_строка_отвергается",
    ),
    (
        "src/ratings/sheet.py",
        "        elif start > later:\n            year -= 1\n",
        "        elif start > later:\n            pass\n",
        "tests/test_ratings_sheet.py::test_год_выводится_справа_налево_через_новый_год",
    ),
    (
        "src/ratings/sheet.py",
        "    if not 0 <= value <= 100:\n",
        "    if False:\n",
        "tests/test_ratings_sheet.py::test_балл_вне_0_100_строкой_журнала",
    ),
    (
        "src/ratings/links.py",
        "    if parts.hostname != RATING_HOST or not parts.fragment:\n",
        "    if not parts.fragment:\n",
        "tests/test_ratings_sheet.py::test_ссылка_листа_чужой_хост_id_не_берётся",
    ),
    (
        "src/ratings/formats.py",
        "    if not (value.isascii() and value.isdigit()):",
        "    if not value.isdigit():",
        "tests/test_ratings_formats.py::test_продолжительность_надстрочная_цифра_строкой_журнала",
    ),
    (
        "src/ratings/csvio.py",
        "    except csv.Error as exc:",
        "    except KeyError as exc:",
        "tests/test_ratings_formats.py::test_ячейка_длиннее_лимита_csv_отказ_а_не_падение",
    ),
    (
        "src/ratings/formats.py",
        '"%d.%m.%Y %H:%M:%S", ',
        "",
        "tests/test_ratings_formats.py::test_дата_excel_с_секундами",
    ),
    (
        "src/ratings/formats.py",
        ', "%d.%m.%Y %H:%M")',
        ")",
        "tests/test_ratings_formats.py::test_сохранённый_в_excel_с_точкой_с_запятой_читается",
    ),
    (
        "src/ratings/sheet.py",
        "            if known != developer and country",
        "            if False and country",
        "tests/test_ratings_sheet.py::test_два_девелопера_у_страны_не_теряются_молча",
    ),
    (
        "src/ratings/sheet.py",
        "            if known != developer and country not in conflicted:",
        "            if known != developer:",
        "tests/test_ratings_sheet.py::test_конфликт_девелопера_одно_замечание_на_страну",
    ),
    (
        "src/db/migrations/0038_ratings.sql",
        "'bad_row', 'developer_conflict'",
        "'bad_row'",
        "tests/test_db_ratings_schema.py::test_замечание_журнала_developer_conflict_ложится",
    ),
    (
        "src/ratings/snapshot.py",
        "        if period.rating_type != RS:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_снимок_разобран",
    ),
    (
        "src/ratings/snapshot.py",
        '    if item.get("wow"):\n        return None\n',
        "",
        "tests/test_ratings_snapshot.py::test_снимок_разобран",
    ),
    (
        "src/ratings/snapshot.py",
        "        if not 0 <= score <= 100:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_испорченная_пиццерия_в_журнал_соседка_цела",
    ),
    (
        "src/ratings/snapshot.py",
        "        if key in periods:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_испорченная_пиццерия_в_журнал_соседка_цела",
    ),
    (
        "src/ratings/snapshot.py",
        "    if not _is_int(amount) or not 1 <= amount <= MAX_COUNT:",
        "    if not _is_int(amount) or amount < 1:",
        "tests/test_ratings_snapshot.py::test_испорченная_пиццерия_в_журнал_соседка_цела",
    ),
    (
        "src/ratings/snapshot.py",
        "    except OverflowError as exc:",
        "    except KeyError as exc:",
        "tests/test_ratings_snapshot.py::test_испорченная_пиццерия_в_журнал_соседка_цела",
    ),
    (
        "src/ratings/snapshot.py",
        "_is_int(country_id) else (None, None)",
        "_is_int(country_id) or True else (None, None)",
        "tests/test_ratings_snapshot.py::test_страна_пиццерии_не_числом_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "    except (RecursionError, ValueError) as exc:\n",
        "    except ValueError as exc:\n",
        "tests/test_ratings_snapshot.py::test_мусор_вместо_json_отказ_с_кодом",
    ),
    (
        "src/ratings/snapshot.py",
        '        or not _is_int(doc.get("version"))\n',
        "",
        "tests/test_ratings_snapshot.py::test_испорченный_документ_отказ_с_кодом_а_не_исключение",
    ),
    (
        "src/ratings/snapshot.py",
        '    return text if len(text) <= _CLIP else text[: _CLIP - 1] + "…"\n',
        "    return text\n",
        "tests/test_ratings_snapshot.py::test_огромная_строка_в_журнале_обрезана",
    ),
    (
        "src/ratings/snapshot.py",
        "    if _is_int(index) and _is_int(total) and 1 <= index <= total <= MAX_CHUNKS:",
        "    if True:",
        "tests/test_ratings_snapshot.py::test_chunk_невалиден_замечание_а_не_тихий_none",
    ),
    (
        "src/ratings/snapshot.py",
        "        if unit_id in seen_units:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_пиццерия_повторена_в_части_вторая_в_журнал_без_задвоения",
    ),
    (
        "src/ratings/snapshot.py",
        "        if known is not None and (",
        "        if False and (",
        "tests/test_ratings_snapshot.py::test_период_с_разными_датами_у_двух_пиццерий_вторая_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "            period.begin_on,\n            period.end_on,\n",
        "            period.begin_on,\n            known.end_on,\n",
        "tests/test_ratings_snapshot.py::test_период_с_разными_датами_у_двух_пиццерий_вторая_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "            period.rating_type,\n            period.begin_on,\n",
        "            known.rating_type,\n            period.begin_on,\n",
        "tests/test_ratings_snapshot.py::test_период_с_другим_типом_у_второй_пиццерии_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "        if owner is not None and owner != period_id:",
        "        if False:",
        "tests/test_ratings_snapshot.py::test_два_id_с_одним_типом_и_началом_вторая_пиццерия_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "        if conflict is not None:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_два_id_с_одним_типом_и_началом_вторая_пиццерия_в_журнал",
    ),
    (
        "src/ratings/snapshot.py",
        "    if chunk_problem is not None:\n",
        "    if False:\n",
        "tests/test_ratings_snapshot.py::test_chunk_невалиден_замечание_а_не_тихий_none",
    ),
    (
        "src/ratings/snapshot.py",
        "        if country_id in by_id:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_страна_повторена_в_справочнике_отказ",
    ),
    (
        "src/ratings/matching.py",
        "    candidates = [unit for unit in pool if _number(_canon(unit.name)) == number]\n",
        "    candidates = pool\n",
        "tests/test_ratings_matching.py::test_другой_номер_соседа_не_цепляется_и_без_ничьей",
    ),
    (
        "src/ratings/matching.py",
        "        return _only(exact)\n",
        "        return next(iter(exact))\n",
        "tests/test_ratings_matching.py::test_двусмысленность_нет",
    ),
    (
        "src/ratings/importer.py",
        "        if prior is not None:\n",
        "        if False:\n",
        "tests/test_db_ratings_import.py::test_тот_же_файл_дубль_со_ссылкой",
    ),
    (
        "src/db/ratings.py",
        "\"where not (ratings.scores.source = 'snapshot' and excluded.source = 'sheet') \"",
        '""',
        "tests/test_db_ratings_import.py::test_снимок_главнее_листа",
    ),
    (
        "src/db/ratings.py",
        '"delete from ratings.violations where rating_type = %s and checkup_dodo_id = %s"',
        '"select %s, %s"',
        "tests/test_db_ratings_import.py::test_те_же_строки_другими_байтами_обновляются",
    ),
    (
        "src/ratings/importer.py",
        "        pool = [known for known in self.known if known.country is not None]\n",
        "        pool = list(self.known)\n",
        "tests/test_db_ratings_import.py::test_пиццерия_без_страны_не_цепляется_к_чужой_стране",
    ),
    (
        "src/ratings/importer.py",
        "        issues = _journal_issues(writer.issues)\n",
        "        issues = [(max(i.row_no, 1), i.reason, i.detail) for i in writer.issues]\n",
        "tests/test_db_ratings_import.py::test_несопоставленная_строка_листа_считается_строкой_а_не_баллами",
    ),
    (
        "src/ratings/importer.py",
        "    except psycopg.Error as exc:\n        reason = _db_reason(exc)\n",
        "    except KeyError as exc:\n        reason = _db_reason(exc)\n",
        "tests/test_db_ratings_import.py::test_отказ_базы_посреди_файла_не_оставляет_половины",
    ),
    (
        "src/ratings/snapshot.py",
        "        if (period.rating_type, period.begin_on) in slots:\n",
        "        if False:\n",
        "tests/test_ratings_snapshot.py::test_два_id_с_одним_типом_и_началом_у_одной_пиццерии_в_журнал",
    ),
    (
        "src/ratings/importer.py",
        '    except Exception as exc:\n        failed(f"сбой загрузки:',
        '    except KeyError as exc:\n        failed(f"сбой загрузки:',
        "tests/test_db_ratings_import.py::test_сбой_не_базы_оставляет_failed_и_уходит_наружу",
    ),
    (
        "src/ratings/importer.py",
        '    except Exception as exc:\n        failed(f"сбой разбора:',
        '    except KeyError as exc:\n        failed(f"сбой разбора:',
        "tests/test_db_ratings_import.py::test_сбой_разборщика_оставляет_failed_и_уходит_наружу",
    ),
    (
        "src/ratings/importer.py",
        "    except Exception as exc:\n        logger.warning(",
        "    except psycopg.Error as exc:\n        logger.warning(",
        "tests/test_db_ratings_import.py::test_сбой_следа_не_подменяет_причину_отказа",
    ),
    (
        "src/db/ratings.py",
        '"  or ratings.periods.dodo_id = excluded.dodo_id "',
        '"  or true "',
        "tests/test_db_ratings_import.py::test_период_того_же_слота_с_другим_id_отказ_а_не_склейка",
    ),
    (
        "src/ratings/importer.py",
        "    return f\"{prefix}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}\"",
        '    return f"{prefix}:{normalized}"',
        "tests/test_db_ratings_import.py::test_длинный_текст_нарушения_ложится",
    ),
    (
        "src/ratings/importer.py",
        "            if r.unit.dodo_id is None:\n",
        "            if False:\n",
        "tests/test_db_ratings_import.py::test_замечание_без_id_пиццерии_в_журнал",
    ),
    (
        "src/ratings/periods.py",
        "    last = calendar.monthrange(year, first + 2)[1]\n",
        "    last = calendar.monthrange(year, first + 1)[1]\n",
        "tests/test_ratings_periods.py::test_квартал_и_месяц_по_ключу",
    ),
    (
        "src/ratings/periods.py",
        "        return month_period(year - 1, 12) if month == 1 "
        "else month_period(year, month - 1)\n",
        "        return month_period(year, max(month - 1, 1))\n",
        "tests/test_ratings_periods.py::test_прошлый_такой_же_период",
    ),
    (
        "src/ratings/periods.py",
        "    return _rating(max(earlier, key=lambda p: p.begin_on)) if earlier else None\n",
        "    return _rating(min(earlier, key=lambda p: p.begin_on)) if earlier else None\n",
        "tests/test_ratings_periods.py::test_прошлый_период_рейтинга_ближайший_а_не_первый",
    ),
    (
        "src/ratings/periods.py",
        'ReportPeriod(KIND_RATING, f"rs:{period.id}", period.begin_on, period.end_on)',
        'ReportPeriod(KIND_RATING, f"rs:{period.begin_on}", period.begin_on, period.end_on)',
        "tests/test_ratings_periods.py::test_прошлый_такой_же_период",
    ),
    (
        "src/ratings/periods.py",
        "    anchor = latest or today\n",
        "    anchor = today\n",
        "tests/test_ratings_periods.py::test_по_умолчанию_квартал_последних_данных",
    ),
    (
        "src/ratings/periods.py",
        "if year >= _MIN_YEAR and 1 <= month <= 12",
        "if 1 <= month <= 12",
        "tests/test_ratings_periods.py::test_год_ноль_и_нечестные_цифры_нет",
    ),
    (
        "src/ratings/periods.py",
        "    if found := _MONTH.fullmatch(key):\n",
        "    if found := _MONTH.match(key):\n",
        "tests/test_ratings_periods.py::test_год_ноль_и_нечестные_цифры_нет",
    ),
    (
        "src/ratings/periods.py",
        '_RATING = re.compile(r"rs:(\\d+)", re.ASCII)\n',
        '_RATING = re.compile(r"rs:(\\d+)")\n',
        "tests/test_ratings_periods.py::test_год_ноль_и_нечестные_цифры_нет",
    ),
    (
        "src/ratings/periods.py",
        "        if year == _MIN_YEAR and quarter == 1:\n            return None\n",
        "",
        "tests/test_ratings_periods.py::test_прошлый_у_первого_периода_эры_нет",
    ),
    (
        "src/ratings/summary.py",
        "        (u for u in scored if u.score > threshold), key=lambda u: (-u.score, u.unit_name, u.unit)\n",  # noqa: E501
        "        (u for u in scored if u.score >= threshold), key=lambda u: (-u.score, u.unit_name, u.unit)\n",  # noqa: E501
        "tests/test_ratings_summary.py::test_top_выше_порога_bottom_не_выше",
    ),
    (
        "src/ratings/summary.py",
        "        (u for u in scored if u.score <= threshold), key=lambda u: (u.score, u.unit_name, u.unit)\n",  # noqa: E501
        "        (u for u in scored if u.score < threshold), key=lambda u: (u.score, u.unit_name, u.unit)\n",  # noqa: E501
        "tests/test_ratings_summary.py::test_top_выше_порога_bottom_не_выше",
    ),
    (
        "src/ratings/summary.py",
        "    return tuple(top[:limit]), tuple(bottom[:limit])\n",
        "    return tuple(top), tuple(bottom)\n",
        "tests/test_ratings_summary.py::test_top_bottom_по_десять",
    ),
    (
        "src/ratings/summary.py",
        "    return tuple(top[:limit]), tuple(bottom[:limit])\n",
        "    return tuple(top[:limit]), tuple(bottom)\n",
        "tests/test_ratings_summary.py::test_bottom_ограничен_десятью_худшими",
    ),
    (
        "src/ratings/summary.py",
        "    return round(current - previous, DELTA_DIGITS) + 0.0  # + 0.0 убирает «-0.0»\n",
        "    return previous - current\n",
        "tests/test_ratings_summary.py::test_дельта_к_прошлому_периоду",
    ),
    (
        "src/ratings/summary.py",
        "        if fact.category in _COUNTED:\n",
        "        if True:\n",
        "tests/test_ratings_summary.py::test_топ5_и_на_одну_проверку",
    ),
    (
        "src/ratings/summary.py",
        "        if fact.category in _COUNTED:\n",
        "        if fact.category == CATEGORY_VIOLATION:\n",
        "tests/test_ratings_summary.py::test_замечание_считается_наравне_с_нарушением",
    ),
    (
        "src/ratings/summary.py",
        "        total / checkups if checkups else None,\n",
        "        total / checkups,\n",
        "tests/test_ratings_summary.py::test_ноль_проверок_не_деление_на_ноль",
    ),
    (
        "src/ratings/summary.py",
        "        if len(by_period) != len(period_ids):\n",
        "        if not by_period:\n",
        "tests/test_ratings_summary.py::test_зона_риска_три_подряд_строго_ниже",
    ),
    (
        "src/ratings/summary.py",
        "        if all(score < threshold for score in scores):\n",
        "        if any(score < threshold for score in scores):\n",
        "tests/test_ratings_summary.py::test_зона_риска_три_подряд_строго_ниже",
    ),
    (
        "src/ratings/summary.py",
        "        if all(score < threshold for score in scores):\n",
        "        if all(score <= threshold for score in scores):\n",
        "tests/test_ratings_summary.py::test_зона_риска_три_подряд_строго_ниже",
    ),
    (
        "src/ratings/summary.py",
        "    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]\n",
        "    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))\n",
        "tests/test_ratings_summary.py::test_топ5_и_на_одну_проверку",
    ),
    (
        "src/ratings/summary.py",
        "    text = normalize_text(fact.text)\n",
        "    text = fact.text.casefold()\n",
        "tests/test_ratings_summary.py::test_хард_пометка_автодетекции_и_пробелы_не_мешают",
    ),
    (
        "src/ratings/summary.py",
        '    return re.search(r"(?<!\\w)" + re.escape(pattern), haystack, re.IGNORECASE) is not None\n',  # noqa: E501
        "    return re.search(re.escape(pattern), haystack, re.IGNORECASE) is not None\n",
        "tests/test_ratings_summary.py::test_contains_с_начала_слова",
    ),
    (
        "src/ratings/summary.py",
        "if where[unit] in countries\n",
        "if True\n",
        "tests/test_ratings_summary.py::test_страны_вне_списка_не_входят_в_группу",
    ),
    (
        "src/ratings/summary.py",
        "                fact.unit,\n                normalize_text(fact.text),\n",
        "                normalize_text(fact.text),\n",
        "tests/test_ratings_summary.py::test_хард_порядок_не_зависит_от_входа",
    ),
    (
        "src/ratings/summary.py",
        "    return round(current - previous, DELTA_DIGITS) + 0.0  # + 0.0 убирает «-0.0»\n",
        "    return current - previous\n",
        "tests/test_ratings_summary.py::test_дельта_равных_средних_без_шума_и_минус_нуля",
    ),
    (
        "src/ratings/summary.py",
        "            key = normalize_text(fact.text)\n",
        "            key = fact.text\n",
        "tests/test_ratings_summary.py::test_нарушение_с_пометкой_и_без_одно_в_топе",
    ),
]

env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
failed = False
for path, original, broken, test in cases:
    file = pathlib.Path(path)
    text = file.read_text(encoding="utf-8")
    if original not in text:
        print(f"НЕ ПРИМЕНИЛАСЬ: {path}: {original.strip()!r}")
        failed = True
        continue
    file.write_text(text.replace(original, broken, 1), encoding="utf-8")
    try:
        # Через `make test-honest`: только он подставляет тестовую базу. Голый
        # pytest пропускает тесты блока db, и порча выглядит «не пойманной», а
        # контрольный прогон с пропуском — «пройденным».
        run = subprocess.run(  # noqa: S603
            ["make", "-s", "test-honest", f"ARGS=-q -rs -p no:cacheprovider {test}"],  # noqa: S607
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        file.write_text(text, encoding="utf-8")
    # Пропуск важен только у прошедшего прогона: упавший тест порчу поймал, а
    # слово «skipped» в его выводе бывает полем отчёта загрузки.
    if run.returncode == 0 and re.search(r"\b\d+ skipped\b", run.stdout):
        print(f"НЕ ПРОВЕРЕНА (тест пропущен): {path} -> {test}")
        failed = True
    elif run.returncode == 0:
        print(f"НЕ ПОЙМАНА: {path}: {original.strip()!r} -> {test}")
        failed = True
    else:
        print(f"поймана: {path} -> {test}")
sys.exit(1 if failed else 0)
