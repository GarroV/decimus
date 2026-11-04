"""Постоянная проверка покрытия данных рейтингов «страна × источник» (D704, D706, #1444).

Оповещения D641 (`src/health/alerts.py`) ловят упавший сбор. Эта проверка ловит то, что они не
видят: сбор «прошёл», а по стране источник пуст или заполнен наполовину. Правила — чистые, в
`src/domain/coverage_rules.py`; счётчики из базы — `src/db/coverage_store.py`; здесь сборка
фактов, текст, учёт оповещённого и суточный заход.

**Заход.** Раз в сутки после `COVERAGE_HOUR` (когда ночные сборы уже прошли): бот зовёт
`run_daily_safely` на каждом круге проверок здоровья (`src/bot/health_loader.py`), а заход сам
решает по записи `coverage_check` в `health.checks`, был ли он сегодня. Не дошло до владельца
(канал упал) — запись не пишется, следующий круг повторит.

**Оповещение — как D678.** За заход не больше двух сообщений: тревога (`alert`) — только о
дырах, которых владелец ещё не видел или у которых сменился цвет; отбой (`done`) — о закрытых.
Страны в сообщении сгруппированы по источнику и причине, красное выше жёлтого. Состояние пары
лежит в `health.alerts` под кодом `cov_<источник>:<страна>`; пока оно то же — тишина.
Первый заход не молчит: владелец просил знать о нынешних дырах, и они уходят одним сообщением.

Адресат — только владелец (D706), канал — FURCA. Канала нет или демо — не пишется ничего.
"""

from __future__ import annotations

import logging
import os
import urllib.error
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.db import coverage_store, health_store
from src.db import ratings_read as ratings
from src.db.coverage_store import Counts, Raw
from src.db.errors import DbError
from src.db.job_lock import HEALTH_ALERTS_LOCK_KEY, job_lock
from src.domain import coverage_rules as rules
from src.domain import health_alerts as decisions
from src.domain.coverage_rules import Fact, Finding
from src.domain.health import GREEN
from src.domain.public_urls import ADMIN_PUBLIC_URL_VAR, parse_public_url
from src.notify import furca
from src.ratings import countries as ratings_countries
from src.ratings import freshness, pointer

from . import alerts
from . import coverage_texts as texts

logger = logging.getLogger(__name__)

#: Код записи «когда проверка покрытия шла в последний раз» в `health.checks`.
CHECK_CODE = "coverage_check"
CHECK_REASON = "health.reason.coverage_checked"
#: Не раньше этого часа (по часовому поясу сервера): ночные сборы к нему уже прошли.
COVERAGE_HOUR = 10
#: Первые дни месяца оценок клиентов за текущий месяц ещё может не быть — это не дыра.
KR_GRACE_DAYS = 3
OWNER_LANG = "ru"
CONNECTIONS_TAB_PATH = "/administration?tab=connections"

Send = Callable[[tuple[str, str], str, str], None]


# ── Факты ──


def _age(latest: date | None, today: date) -> int | None:
    return None if latest is None else (today - latest).days


def _counted(counts: Counts | None) -> Counts:
    return counts or Counts(0, 0, None)


def _kr_fact(country: str, raw: Raw, today: date) -> Fact:
    current = today.replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    in_current = raw.kr.get((country, current), 0)
    in_previous = raw.kr.get((country, previous), 0)
    missing = tuple(
        name
        for name, n, skip in (
            (rules.CURRENT, in_current, today.day <= KR_GRACE_DAYS),
            (rules.PREVIOUS, in_previous, False),
        )
        if n == 0 and not skip
    )
    best = max(in_current, in_previous)
    return Fact(
        country, rules.SRC_KR, raw.base[country], best, best,
        connected=country in raw.kr_logins, missing=missing,
    )  # fmt: skip


def _period_fact(source: str, country: str, raw: Raw, today: date, green_days: int) -> Fact:
    counts = _counted(raw.periods.get((source, country)))
    return Fact(
        country, source, raw.base[country], counts.covered, counts.ever,
        _age(counts.latest, today), green_days,
    )  # fmt: skip


def _maps_fact(source: str, provider: int, country: str, raw: Raw, today: date) -> Fact:
    counts = _counted(raw.maps.get((provider, country)))
    return Fact(
        country, source, raw.base[country], counts.covered, counts.ever,
        _age(counts.latest, today), rules.FRESH_DAYS,
    )  # fmt: skip


def _agg_fact(aggregator: str, country: str, raw: Raw, today: date) -> Fact:
    counts = _counted(raw.aggs.get((aggregator, country)))
    base = raw.base[country] - raw.agg_absent.get((aggregator, country), 0)
    return Fact(
        country, rules.agg_source(aggregator), base, counts.covered, counts.ever,
        _age(counts.latest, today), rules.FRESH_DAYS,
    )  # fmt: skip


def build_facts(raw: Raw, today: date, enrolled: Collection[tuple[str, str]]) -> list[Fact]:
    """Факт на каждую пару «страна × источник». `enrolled` — пары (агрегатор, страна), для
    которых агрегатор заведён по списку стран сборщика; к ним добавляются страны, где у
    агрегатора уже есть точки в справочнике (сборщики «известной точки» без списка стран).
    Агрегатор, не заведённый для страны, фактов не даёт — это не дыра."""
    pairs = set(enrolled) | set(raw.agg_points)
    out: list[Fact] = []
    for country in sorted(raw.base):
        out.append(_period_fact("rs", country, raw, today, freshness.RS_GREEN_DAYS))
        out.append(_period_fact("rko", country, raw, today, freshness.RKO_GREEN_DAYS))
        out.append(_kr_fact(country, raw, today))
        out.append(_maps_fact(rules.SRC_GOOGLE, pointer.GOOGLE, country, raw, today))
        out.append(_maps_fact(rules.SRC_YANDEX, pointer.YANDEX, country, raw, today))
        out.extend(_agg_fact(a, country, raw, today) for a, c in sorted(pairs) if c == country)
    return out


def enrolled_from_collectors() -> frozenset[tuple[str, str]]:
    """Пары (агрегатор, страна) из списков стран работающих сборщиков; приостановленный
    сборщик (Yandex Eda без ретранслятора, D397) не заведён — его пустота не дыра."""
    from src.ratings.aggregators import collect

    return frozenset(
        (module.KEY, country) for module in collect.SEARCHERS for country in module.COUNTRIES
    )


# ── Таблица для вкладки «Подключения» ──


@dataclass(frozen=True)
class Cell:
    """Ячейка таблицы: цвет, доля пиццерий с данными, дата самых новых данных, причина дыры."""

    light: str
    percent: int
    on: date | None
    reason: str | None


@dataclass(frozen=True)
class Matrix:
    """Источники (колонки) и страны (строки); `None` в ячейке — от пары ничего не ждём."""

    sources: tuple[str, ...]
    rows: tuple[tuple[str, tuple[Cell | None, ...]], ...]


_FIXED_SOURCES = (rules.SRC_RS, rules.SRC_RKO, rules.SRC_KR, rules.SRC_GOOGLE, rules.SRC_YANDEX)


def _cell(fact: Fact, today: date) -> Cell | None:
    if not fact.enrolled or fact.base <= 0:
        return None
    finding = rules.judge(fact)
    on = None if fact.age_days is None else today - timedelta(days=fact.age_days)
    percent = round(rules.share_of(fact) * 100)
    if finding is None:
        return Cell(GREEN, percent, on, None)
    return Cell(finding.level, percent, on, finding.reason)


def matrix(facts: list[Fact], today: date) -> Matrix:
    """Таблица «страна × источник» из тех же фактов и тех же правил, что у оповещения."""
    extra = sorted({f.source for f in facts} - set(_FIXED_SOURCES))
    sources = (*_FIXED_SOURCES, *extra)
    by_pair = {(f.country, f.source): f for f in facts}
    countries = sorted({f.country for f in facts})
    rows = tuple(
        (
            country,
            tuple(
                _cell(by_pair[(country, source)], today) if (country, source) in by_pair else None
                for source in sources
            ),
        )
        for country in countries
    )
    return Matrix(sources, rows)


def read_matrix(now: datetime | None = None) -> Matrix | None:
    """Таблица на сегодня; `None` — база не ответила."""
    today = (now or datetime.now(UTC)).astimezone(freshness.local_zone()).date()
    try:
        facts = build_facts(read_raw(today), today, enrolled_from_collectors())
    except DbError:
        logger.warning("Покрытие данных рейтингов не прочиталось для экрана", exc_info=True)
        return None
    return matrix(facts, today)


# ── Текст ──


def _entry(finding: Finding, names: Mapping[str, str], lang: str) -> str:
    name = names.get(finding.country, finding.country)
    if finding.reason == rules.LOW:
        return texts.text("cov.detail.share", lang, name=name, percent=round(finding.share * 100))
    if finding.reason == rules.STALE and finding.age_days is not None:
        return texts.text("cov.detail.age", lang, name=name, days=finding.age_days)
    return name


def _rank(source: str) -> tuple[int, str]:
    """Порядок строк в сообщении: сначала фиксированные источники, потом площадки по алфавиту."""
    return (
        _FIXED_SOURCES.index(source) if source in _FIXED_SOURCES else len(_FIXED_SOURCES),
        source,
    )


def _reason(reason: str, lang: str) -> str:
    return texts.text(f"cov.reason.{reason}", lang, percent=round(rules.MIN_SHARE * 100))


def _tail(url: str | None, lang: str) -> str:
    return "" if not url else "\n" + texts.text("cov.tail", lang, url=url)


def compose_alert(
    found: list[Finding], *, country_names: Mapping[str, str], url: str | None,
    lang: str = OWNER_LANG,
) -> str:  # fmt: skip
    """Одно сообщение о новых дырах: строка на (источник, причина), страны в ней списком."""
    groups: dict[tuple[str, str, str], list[Finding]] = {}
    for f in sorted(
        found, key=lambda f: (f.level != rules.RED, _rank(f.source), f.reason, f.country)
    ):
        groups.setdefault((f.level, f.source, f.reason), []).append(f)
    lines = [
        texts.text(
            "cov.line", lang,
            source=texts.source_name(source, lang), reason=_reason(reason, lang),
            countries=", ".join(_entry(f, country_names, lang) for f in members),
        )
        for (_, source, reason), members in groups.items()
    ]  # fmt: skip
    frame = "cov.red" if any(f.level == rules.RED for f in found) else "cov.yellow"
    return texts.text(frame, lang, lines="\n".join(lines)) + _tail(url, lang)


def compose_done(
    closed: list[tuple[str, str]], *, country_names: Mapping[str, str], url: str | None,
    lang: str = OWNER_LANG,
) -> str:  # fmt: skip
    """Отбой: пары (источник, страна), у которых дыра закрылась, по источникам."""
    by_source: dict[str, list[str]] = {}
    for source, country in sorted(closed):
        by_source.setdefault(source, []).append(country_names.get(country, country))
    lines = [
        texts.text(
            "cov.line_done", lang,
            source=texts.source_name(source, lang), countries=", ".join(names),
        )
        for source, names in by_source.items()
    ]  # fmt: skip
    return texts.text("cov.done", lang, lines="\n".join(lines)) + _tail(url, lang)


# ── Решение и отправка ──


@dataclass(frozen=True)
class Result:
    sent: int
    failed: bool


def _split(code: str) -> tuple[str, str]:
    source, country = code.removeprefix(rules.STATE_PREFIX).split(":")
    return source, country


def process(
    found: list[Finding],
    previous: Mapping[str, str],
    *,
    target: tuple[str, str],
    send: Send,
    country_names: Mapping[str, str],
    url: str | None,
    now: datetime,
) -> Result:
    """Решить и отправить; записать оповещённые состояния. `previous` — только коды покрытия."""
    current = {rules.state_code(f.source, f.country): f for f in found}
    fresh: list[Finding] = []
    saved: dict[str, str] = {}
    for code, finding in current.items():
        if decisions.decide(previous.get(code), finding.level, baseline=False):
            fresh.append(finding)
        elif previous.get(code) != finding.level:
            saved[code] = finding.level
    closed = [
        code for code, level in previous.items() if level != decisions.OK and code not in current
    ]
    batches: list[tuple[str, str, list[str]]] = []
    if fresh:
        text = compose_alert(fresh, country_names=country_names, url=url)
        batches.append((furca.ALERT, text, [rules.state_code(f.source, f.country) for f in fresh]))
    if closed:
        text = compose_done([_split(c) for c in closed], country_names=country_names, url=url)
        batches.append((furca.DONE, text, closed))
    sent, failed = 0, False
    for kind, text, codes in batches:
        try:
            send(target, text, kind)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Состояние не помечено оповещённым — следующий заход повторит.
            logger.warning("Оповещение о покрытии данных не ушло (%s), повтор позже", exc)
            failed = True
            break
        sent += 1
        for code in codes:
            saved[code] = current[code].level if code in current else decisions.OK
    health_store.save_alert_levels(saved, now)
    return Result(sent, failed)


# ── Суточный заход ──


def is_due(now: datetime, last: datetime | None) -> bool:
    """Пора ли: после `COVERAGE_HOUR` и сегодня (по часовому поясу сервера) ещё не шли."""
    zone = freshness.local_zone()
    local = now.astimezone(zone)
    if local.hour < COVERAGE_HOUR:
        return False
    return last is None or last.astimezone(zone).date() < local.date()


def coverage_levels(levels: Mapping[str, str]) -> dict[str, str]:
    """Из всех оповещённых состояний — только состояния проверки покрытия."""
    return {k: v for k, v in levels.items() if k.startswith(rules.STATE_PREFIX)}


def _country_names() -> dict[str, str]:
    try:
        return {c.code: c.name_ru for c in ratings.countries()}
    except DbError:
        return {}


def _url(env: Mapping[str, str]) -> str | None:
    try:
        base = parse_public_url(env.get(ADMIN_PUBLIC_URL_VAR) or "", var=ADMIN_PUBLIC_URL_VAR)
    except ValueError:
        return None
    return None if base is None else f"{base}{CONNECTIONS_TAB_PATH}"


def read_raw(today: date) -> Raw:
    """Счётчики из базы для сегодняшних суток."""
    current = today.replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    return coverage_store.read(
        excluded=sorted(ratings_countries.EXCLUDED),
        months=[current, previous],
        since=today - timedelta(days=rules.FRESH_DAYS),
        providers=[pointer.GOOGLE, pointer.YANDEX],
    )


def run_daily(
    now: datetime | None = None,
    *,
    env: Mapping[str, str] | None = None,
    send: Send = furca.send,
) -> int:
    """Суточный заход; возвращает число отправленных сообщений."""
    env = os.environ if env is None else env
    moment = now or datetime.now(UTC)
    target = None if alerts.is_demo(env) else furca.channel(env)
    if target is None:
        return 0
    last = health_store.probes().get(CHECK_CODE)
    if not is_due(moment, last.checked_at if last else None):
        return 0
    with job_lock(HEALTH_ALERTS_LOCK_KEY, what="покрытие данных рейтингов") as got:
        if not got:
            return 0
        today = moment.astimezone(freshness.local_zone()).date()
        facts = build_facts(read_raw(today), today, enrolled_from_collectors())
        previous = coverage_levels(health_store.alert_levels())
        result = process(
            rules.judge_all(facts), previous, target=target, send=send,
            country_names=_country_names(), url=_url(env), now=moment,
        )  # fmt: skip
        if not result.failed:
            health_store.record(CHECK_CODE, GREEN, CHECK_REASON, moment)
        return result.sent


def run_daily_safely() -> None:
    """Заход для цикла бота: что бы ни случилось, цикл живёт дальше."""
    try:
        run_daily()
    except Exception:
        logger.exception("Проверка покрытия данных рейтингов: заход упал")
