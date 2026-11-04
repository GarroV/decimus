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
    assert {rules.SRC_RS, rules.SRC_RKO, rules.SRC_KR, rules.SRC_GOOGLE, rules.SRC_YANDEX} == found


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
    old = _raw(maps={(1, "SI"): Counts(10, 0, date(2026, 10, 20))})
    assert rules.judge(_facts(old)["maps_yandex:SI"]).reason == rules.STALE  # type: ignore[union-attr]


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
    assert "• Wolt: заполнено меньше 80% пиццерий — Черногория, 40%." in text
    assert text.index("Клиентские") < text.index("Wolt")
    assert text.rstrip().endswith(URL)
    assert "kr" not in text.replace("Клиентские", "") and "RS" not in text


def test_сообщение_только_жёлтое_с_жёлтой_рамкой() -> None:
    text = cc.compose_alert(
        [_finding("SI", "maps_google", rules.YELLOW, rules.STALE)], country_names=NAMES, url=None
    )
    assert text.startswith("🟡") and "Google Карты: данные устарели — Словения, 14 дн." in text
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
