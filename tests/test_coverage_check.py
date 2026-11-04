"""Проверка покрытия данных рейтингов (D704, D706): сборка фактов, склейка сообщения, повтор.

Без базы и сети: сохранение состояний подменено словарём, отправка — списком.
"""

from __future__ import annotations

import urllib.error
from datetime import UTC, date, datetime

import pytest

from src.db import health_store
from src.db.coverage_store import Counts, Raw
from src.domain import coverage_rules as rules
from src.health import alerts
from src.health import coverage_check as cc

TODAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
TARGET = ("http://ch:8090/notify", "секрет")
NAMES = {"RS": "Сербия", "SI": "Словения", "AT": "Австрия", "ME": "Черногория"}
URL = "https://decimus.example/administration?tab=connections"
OCT, NOV = date(2026, 10, 1), date(2026, 11, 1)


def _raw(**kw: object) -> Raw:
    return Raw(**{"base": {"SI": 10}, **kw})  # type: ignore[arg-type]


def _facts(raw: Raw, enrolled: frozenset[tuple[str, str]] = frozenset()) -> dict[str, rules.Fact]:
    return {f"{f.source}:{f.country}": f for f in cc.build_facts(raw, TODAY, enrolled)}


def _finding(country: str, source: str, level: str, reason: str, share: float = 0.0):
    return rules.Finding(country, source, level, reason, share, 14)


class Box:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> None:
        self.levels: dict[str, str] = {}
        self.sent: list[tuple[str, str]] = []
        self.fail = fail
        monkeypatch.setattr(
            health_store, "save_alert_levels", lambda levels, at: self.levels.update(levels)
        )

    def send(self, target: tuple[str, str], text: str, kind: str) -> None:
        if self.fail:
            raise urllib.error.URLError("канал недоступен")
        self.sent.append((kind, text))

    def run(self, found: list[rules.Finding]) -> int:
        return cc.process(
            found, dict(self.levels), target=TARGET, send=self.send,
            country_names=NAMES, url=URL, now=NOW,
        ).sent  # fmt: skip


# ── Сборка фактов ──


def test_пустые_источники_страны_дают_красные_факты() -> None:
    found = {f.source for f in rules.judge_all(_facts(_raw()).values())}
    assert {
        rules.SRC_RS,
        rules.SRC_RKO,
        rules.SRC_KR,
        rules.SRC_GOOGLE,
    } == found  # Яндекс Карт в Словении нет


def test_клиентские_оценки_без_входа_dodo_is_не_подключены() -> None:
    kr = _facts(_raw())["kr:SI"]
    assert kr.connected is False
    assert _facts(_raw(kr_logins=frozenset({"SI"})))["kr:SI"].connected is True


def test_клиентские_оценки_оба_месяца_есть_не_дыра() -> None:
    raw = _raw(kr={("SI", NOV): 10, ("SI", OCT): 10}, kr_logins=frozenset({"SI"}))
    assert rules.judge(_facts(raw)["kr:SI"]) is None


def test_клиентские_оценки_нет_прошлого_месяца_жёлтое() -> None:
    raw = _raw(kr={("SI", NOV): 10}, kr_logins=frozenset({"SI"}))
    f = rules.judge(_facts(raw)["kr:SI"])
    assert f is not None and f.reason == rules.MISSING_PREVIOUS


def test_клиентские_оценки_нет_текущего_месяца_жёлтое_но_не_в_первые_дни() -> None:
    raw = _raw(kr={("SI", OCT): 10}, kr_logins=frozenset({"SI"}))
    f = rules.judge(_facts(raw)["kr:SI"])
    assert f is not None and f.reason == rules.MISSING_CURRENT
    early = cc.build_facts(raw, date(2026, 11, 2), frozenset())
    assert rules.judge(next(x for x in early if x.source == "kr")) is None


def test_рс_свежесть_считается_по_порогу_из_freshness() -> None:
    from src.ratings import freshness

    end = date(2026, 11, 4)
    ok = _raw(periods={("rs", "SI"): Counts(10, 10, end.replace(day=4))})
    assert rules.judge(_facts(ok)["rs:SI"]) is None
    old_end = date.fromordinal(TODAY.toordinal() - freshness.RS_GREEN_DAYS - 1)
    old = _raw(periods={("rs", "SI"): Counts(10, 10, old_end)})
    assert rules.judge(_facts(old)["rs:SI"]).reason == rules.STALE  # type: ignore[union-attr]


def test_карты_свежесть_семь_дней_и_покрытие() -> None:
    fresh = _raw(maps={(2, "SI"): Counts(10, 9, TODAY)})
    assert rules.judge(_facts(fresh)["maps_google:SI"]) is None
    low = _raw(maps={(2, "SI"): Counts(10, 5, TODAY)})
    assert rules.judge(_facts(low)["maps_google:SI"]).reason == rules.LOW  # type: ignore[union-attr]
    old = Raw(base={"BG": 10}, maps={(1, "BG"): Counts(10, 0, date(2026, 10, 20))})
    assert rules.judge(_facts(old)["maps_yandex:BG"]).reason == rules.STALE  # type: ignore[union-attr]


def test_агрегатор_не_заведён_для_страны_факта_нет() -> None:
    assert "agg_wolt:SI" not in _facts(_raw())


def test_агрегатор_заведён_без_точек_красный() -> None:
    facts = _facts(_raw(), frozenset({("wolt", "SI")}))
    assert rules.judge(facts["agg_wolt:SI"]).reason == rules.EMPTY  # type: ignore[union-attr]


def test_отметка_нет_на_площадке_вычитается_из_базы() -> None:
    raw = _raw(aggs={("wolt", "SI"): Counts(9, 9, TODAY)}, agg_absent={("wolt", "SI"): 1})
    facts = _facts(raw, frozenset({("wolt", "SI")}))
    assert facts["agg_wolt:SI"].base == 9
    assert rules.judge(facts["agg_wolt:SI"]) is None


def test_все_пиццерии_отмечены_нет_на_площадке_не_дыра() -> None:
    raw = _raw(agg_absent={("wolt", "SI"): 10})
    assert rules.judge(_facts(raw, frozenset({("wolt", "SI")}))["agg_wolt:SI"]) is None


def test_страна_с_точками_агрегатора_заведена_без_списка_модулей() -> None:
    facts = _facts(_raw(agg_points=frozenset({("glovo", "SI")})))
    assert "agg_glovo:SI" in facts


# ── Не обслуживается: не дыра ──


def test_яндекс_карты_в_стране_без_карточек_не_заведены_а_в_других_ждутся() -> None:
    raw = Raw(base={"SI": 10, "BG": 10})
    facts = _facts(raw)
    assert "maps_yandex:SI" not in facts and "maps_yandex:BG" in facts
    assert "maps_google:SI" in facts  # другие источники страны ждутся как прежде


def test_устаревшие_яндекс_карты_болгарии_остаются_дырой() -> None:
    raw = Raw(base={"BG": 10}, maps={(1, "BG"): Counts(10, 0, date(2025, 1, 1))})
    f = rules.judge(_facts(raw)["maps_yandex:BG"])
    assert f is not None and f.reason == rules.STALE


def test_агрегатор_не_обслуживающий_страну_не_факт_даже_если_заведён() -> None:
    raw = Raw(base={"RS": 4, "SI": 4})
    facts = _facts(raw, frozenset({("wolt", "RS"), ("wolt", "SI"), ("yandex_eda", "KG")}))
    assert "agg_wolt:RS" not in facts and "agg_wolt:SI" in facts


def test_исключение_живёт_и_при_точках_в_справочнике() -> None:
    raw = Raw(base={"GE": 3}, agg_points=frozenset({("wolt", "GE"), ("wolt", "SI")}))
    assert "agg_wolt:GE" not in _facts(raw)


def test_таблица_экрана_не_показывает_не_обслуживаемое() -> None:
    facts = cc.build_facts(Raw(base={"SI": 10}), TODAY, frozenset())
    table = cc.matrix(facts, TODAY)
    row = dict(table.rows)["SI"]
    assert row[table.sources.index("maps_yandex")] is None


def test_пиццерии_без_площадки_уходят_в_запрос_по_имени_и_без_префикса_источника(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_read(**kw: object) -> Raw:
        seen.update(kw)
        return Raw()

    monkeypatch.setattr(cc.coverage_store, "read", fake_read)
    cc.read_raw(TODAY)
    pairs = set(seen["unit_exempt"])  # type: ignore[call-overload]
    assert ("bolt_food", "Pleven-1") in pairs and ("yandex_eda", "Лида-1") in pairs
    assert ("yandex_eda", "Минск-6") not in pairs  # эти остаются дырой


def test_список_не_обслуживаемого_заполнен_с_датой_и_причиной() -> None:
    from src.domain import coverage_exempt as ex

    keys = [(n.source, n.country, n.units) for n in ex.NOT_SERVED]
    assert len(keys) == len(set(keys))
    for n in ex.NOT_SERVED:
        assert n.reason.strip() and n.checked_on and len(n.country) == 2
        assert n.source in {rules.SRC_YANDEX} or n.source.startswith(rules.AGG_PREFIX)
        assert all(u.strip() for u in n.units)


def test_список_не_обслуживаемого_совпадает_с_разведкой_04_11_2026() -> None:
    from src.domain import coverage_exempt as ex

    assert ex.country_pairs() == {
        ("agg_wolt", "RS"), ("agg_wolt", "GE"), ("agg_bolt_food", "GE"), ("agg_yandex_eda", "KG"),
        *{(rules.SRC_YANDEX, c) for c in ("EE", "ES", "ME", "PL", "RO", "SI", "NG", "HR")},
    }  # fmt: skip
    units = {(s, n) for s, n in ex.unit_pairs()}
    assert {n for s, n in units if s == "agg_bolt_food"} == {"Pleven-1", "Stara Zagora-1"}
    assert {n for s, n in units if s == "agg_yandex_eda"} == {
        "Борисов-1", "Жлобин-1", "Жодино-1", "Лида-1", "Мозырь-1", "Молодечно-1",
        "Новополоцк-1", "Орша-1", "Пинск-1", "Полоцк-1", "Речица-1", "Солигорск-1",
    }  # fmt: skip


# ── Формат ──


def test_число_дней_склоняется_по_правилам() -> None:
    from src.health import coverage_texts as t

    words = {n: t.days(n, "ru") for n in (1, 2, 3, 4, 5, 11, 12, 14, 21, 22, 24, 25, 101, 111, 687)}
    assert words == {
        1: "1 день", 2: "2 дня", 3: "3 дня", 4: "4 дня", 5: "5 дней", 11: "11 дней",
        12: "12 дней", 14: "14 дней", 21: "21 день", 24: "24 дня",
        22: "22 дня", 25: "25 дней", 101: "101 день", 111: "111 дней", 687: "687 дней",
    }  # fmt: skip
    assert t.days(1, "en") == "1 day" and t.days(7, "en") == "7 days"


def test_названия_площадок_по_русски_где_они_есть() -> None:
    from src.health import coverage_texts as t

    assert t.source_name("agg_yandex_eda", "ru") == "Яндекс Еда"
    assert t.source_name("agg_yandex_eda", "en") == "Yandex Eda"
    assert t.source_name("agg_wolt", "ru") == "Wolt"
    assert t.source_name("maps_yandex", "en") == "Yandex Maps"


def test_доля_без_запятой_после_страны_а_возраст_в_скобках() -> None:
    found = [
        _finding("SI", "maps_google", rules.YELLOW, rules.LOW, 0.25),
        _finding("RS", "maps_google", rules.YELLOW, rules.LOW, 0.75),
        _finding("AT", "maps_yandex", rules.YELLOW, rules.STALE),
    ]
    found[2] = rules.Finding("AT", "maps_yandex", rules.YELLOW, rules.STALE, 0.0, 687)
    text = cc.compose_alert(found, country_names=NAMES, url=None)
    assert "Сербия 75%, Словения 25%." in text
    assert "Австрия (687 дней)." in text


def test_английский_текст_собирается_для_всех_причин() -> None:
    for reason in (
        rules.EMPTY, rules.NOT_CONNECTED, rules.STALE,
        rules.MISSING_CURRENT, rules.MISSING_PREVIOUS, rules.LOW,
    ):  # fmt: skip
        level = rules.RED if reason in (rules.EMPTY, rules.NOT_CONNECTED) else rules.YELLOW
        text = cc.compose_alert(
            [rules.Finding("SI", "agg_yandex_eda", level, reason, 0.5, 9)],
            country_names=NAMES, url=None, lang="en",
        )  # fmt: skip
        assert "Yandex Eda" in text and "Яндекс" not in text.replace("Словения", "")


# ── Сообщение ──


def test_сообщение_склеивает_страны_по_источнику_и_причине_красное_первым() -> None:
    found = [
        _finding("AT", "kr", rules.RED, rules.NOT_CONNECTED),
        _finding("SI", "kr", rules.RED, rules.NOT_CONNECTED),
        _finding("RS", "maps_yandex", rules.RED, rules.EMPTY),
        _finding("ME", "agg_wolt", rules.YELLOW, rules.LOW, 0.4),
    ]
    text = cc.compose_alert(found, country_names=NAMES, url=URL)
    assert text.startswith("🔴")
    assert "• Клиентские оценки: не подключён вход Dodo IS — Австрия, Словения." in text
    assert "• Яндекс Карты: данных нет совсем — Сербия." in text
    assert "• Wolt: заполнено меньше 80% пиццерий — Черногория 40%." in text
    assert text.index("Клиентские") < text.index("Wolt")
    assert text.rstrip().endswith(URL)
    assert "kr" not in text.replace("Клиентские", "") and "RS" not in text


def test_сообщение_только_жёлтое_с_жёлтой_рамкой() -> None:
    text = cc.compose_alert(
        [_finding("SI", "maps_google", rules.YELLOW, rules.STALE)], country_names=NAMES, url=None
    )
    assert text.startswith("🟡") and "Google Карты: данные устарели — Словения (14 дней)." in text
    assert "Администрирование" not in text


# ── Повтор и отбой ──


def test_первый_заход_шлёт_одно_сообщение_за_заход(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    found = [
        _finding("SI", "kr", rules.RED, rules.NOT_CONNECTED),
        _finding("AT", "rs", rules.RED, rules.EMPTY),
    ]
    assert box.run(found) == 1
    assert [k for k, _ in box.sent] == ["alert"]
    assert box.levels == {"cov_kr:SI": "red", "cov_rs:AT": "red"}


def test_та_же_дыра_повторно_не_пишется(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    found = [_finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)]
    box.run(found)
    assert box.run(found) == 0
    assert len(box.sent) == 1


def test_в_сообщение_идут_только_изменившиеся_дыры(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    old = _finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)
    box.run([old])
    box.run([old, _finding("AT", "rs", rules.RED, rules.EMPTY)])
    assert "Австрия" in box.sent[1][1] and "Словения" not in box.sent[1][1]


def test_дыра_ушла_отдельный_сигнал_done_и_потом_тишина(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    box.run([_finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)])
    assert box.run([]) == 1
    kind, text = box.sent[1]
    assert kind == "done" and text.startswith("🟢") and "Клиентские оценки: Словения." in text
    assert box.levels["cov_kr:SI"] == "ok"
    assert box.run([]) == 0


def test_красное_стало_жёлтым_это_новое_сообщение(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    box.run([_finding("SI", "rs", rules.RED, rules.EMPTY)])
    assert box.run([_finding("SI", "rs", rules.YELLOW, rules.LOW, 0.5)]) == 1
    assert box.sent[1][0] == "alert" and box.levels["cov_rs:SI"] == "yellow"


def test_сбой_отправки_не_помечает_дыру_оповещённой(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch, fail=True)
    assert box.run([_finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)]) == 0
    assert box.levels == {}


def test_сбой_отправки_виден_вызывающему_чтобы_не_отметить_сутки_пройденными(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = Box(monkeypatch, fail=True)
    found = [_finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)]
    result = cc.process(
        found, {}, target=TARGET, send=box.send, country_names=NAMES, url=None, now=NOW
    )
    assert result == cc.Result(sent=0, failed=True)


def test_из_общей_таблицы_берутся_только_состояния_покрытия() -> None:
    levels = {"cov_kr:SI": "red", "dodo_is:RS": "red", "aggregators": "yellow"}
    assert cc.coverage_levels(levels) == {"cov_kr:SI": "red"}


def test_отбой_и_тревога_в_одном_заходе_два_сообщения(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    box.run([_finding("SI", "kr", rules.RED, rules.NOT_CONNECTED)])
    assert box.run([_finding("AT", "rs", rules.RED, rules.EMPTY)]) == 2
    assert [k for k, _ in box.sent[1:]] == ["alert", "done"]


def test_состояния_покрытия_не_ломают_первый_заход_оповещений_о_подключениях() -> None:
    levels = {"cov_kr:SI": "red", "dodo_is:RS": "red"}
    assert alerts.connection_levels(levels) == {"dodo_is:RS": "red"}
    assert alerts.connection_levels({"cov_kr:SI": "red"}) == {}


# ── Суточный заход ──


def test_заход_раз_в_сутки_после_утреннего_часа() -> None:
    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 11, day, hour, 0, tzinfo=UTC)

    assert cc.is_due(at(4, 11), None)
    assert not cc.is_due(at(4, cc.COVERAGE_HOUR - 1), at(3, 11))  # рано
    assert cc.is_due(at(4, 11), at(3, 11))
    assert not cc.is_due(at(4, 15), at(4, 11))  # сегодня уже был
