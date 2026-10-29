"""Оповещения о подключениях (D641): оповещать ли, первый заход, повтор, отбой, демо, сбой отправки.

Без базы: сохранение состояний подменено словарём, отправка — списком. Ядро здесь — решение
«слать или молчать» и то, что состояние помечается оповещённым только после успешной отправки.
"""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from src.db import health_store
from src.domain.health import GREEN, GREY, RED, YELLOW, Status
from src.health import alerts, checks
from src.health.rows import Row

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
LAST_OK = datetime(2026, 10, 25, 3, 10, tzinfo=UTC)
TARGET = ("http://ch:8090/notify", "секрет-канала")
NAMES = {"RS": "Сербия", "SI": "Словения", "ME": "Черногория"}
URL = "https://decimus.example/administration?tab=dodois"


def _dodois(country: str, light: str, reason: str, **params: int) -> Row:
    return Row("dodo_is", checks.DODOIS, Status(light, reason, NOW, params), "dodo_is", country)


def _load(code: str, light: str, reason: str, at: datetime | None = LAST_OK) -> Row:
    return Row(code, checks.LOAD, Status(light, reason, at, {"error": "x"}), "ratings")


def _probe(code: str, light: str, reason: str) -> Row:
    return Row(code, checks.PROBE, Status(light, reason, NOW), "system")


class Box:
    """Что бот записал бы в базу и отправил бы в канал."""

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

    def run(self, rows: list[Row]) -> int:
        return alerts.process(
            alerts.signals(tuple(rows)),
            dict(self.levels),
            target=TARGET,
            send=self.send,
            country_names=NAMES,
            url=URL,
            now=NOW,
        )


@pytest.fixture
def box(monkeypatch: pytest.MonkeyPatch) -> Box:
    return Box(monkeypatch)


RS_OK = _dodois("RS", GREEN, "health.reason.dodois_ok", open=5, total=5)
RS_EXPIRED = _dodois("RS", RED, "health.reason.dodois_expired")


def test_первый_заход_фиксирует_и_молчит(box: Box) -> None:
    sent = box.run([RS_EXPIRED, _load("maps", RED, "health.reason.failed")])
    assert sent == 0 and box.sent == []
    assert box.levels == {"dodo_is:RS": "red", "maps": "red"}


def test_после_первого_захода_поломка_даёт_одно_сообщение_alert(box: Box) -> None:
    box.run([RS_OK])
    assert box.run([RS_EXPIRED]) == 1
    assert [kind for kind, _ in box.sent] == ["alert"]


def test_пока_состояние_то_же_повторов_нет(box: Box) -> None:
    box.run([RS_OK])
    box.run([RS_EXPIRED])
    box.run([RS_EXPIRED])
    box.run([RS_EXPIRED])
    assert len(box.sent) == 1


def test_починилось_одно_сообщение_done_и_потом_тишина(box: Box) -> None:
    box.run([RS_OK])
    box.run([RS_EXPIRED])
    box.run([RS_OK])
    box.run([RS_OK])
    assert [kind for kind, _ in box.sent] == ["alert", "done"]


def test_перезапуск_не_повторяет_тревогу_состояние_берётся_из_базы(box: Box) -> None:
    box.run([RS_OK])
    box.run([RS_EXPIRED])
    # «Перезапуск»: новый заход с тем же сохранённым состоянием.
    box.run([RS_EXPIRED])
    assert len(box.sent) == 1


def test_страны_оповещают_отдельно(box: Box) -> None:
    si_ok = _dodois("SI", GREEN, "health.reason.dodois_ok", open=3, total=3)
    box.run([RS_OK, si_ok])
    box.run([RS_EXPIRED, si_ok])
    assert len(box.sent) == 1
    si_failed = _dodois("SI", RED, "health.reason.dodois_failed")
    box.run([RS_EXPIRED, si_failed])
    assert len(box.sent) == 2 and "Словения" in box.sent[1][1]


def test_неполный_вход_dodo_is_оповещает_жёлтым(box: Box) -> None:
    box.run([RS_OK])
    partial = _dodois("RS", YELLOW, "health.reason.dodois_partial", open=3, total=5)
    box.run([partial])
    assert box.sent[0][1].startswith("🟡") and "открыто 3 из 5" in box.sent[0][1]


def test_проба_жёлтая_не_оповещает_красная_оповещает(box: Box) -> None:
    box.run([_probe("openai", GREEN, "health.reason.ok")])
    box.run([_probe("openai", YELLOW, "health.reason.unverified")])
    assert box.sent == []
    box.run([_probe("openai", RED, "health.reason.rejected")])
    assert len(box.sent) == 1 and box.sent[0][1].startswith("🔴")


def test_жёлтая_проба_не_отменяет_красную_и_не_шлёт_ложный_отбой(box: Box) -> None:
    box.run([_probe("openai", GREEN, "health.reason.ok")])
    box.run([_probe("openai", RED, "health.reason.rejected")])
    box.run([_probe("openai", YELLOW, "health.reason.unverified")])
    box.run([_probe("openai", RED, "health.reason.rejected")])
    assert [kind for kind, _ in box.sent] == ["alert"]


def test_сбор_жёлтый_оповещает(box: Box) -> None:
    box.run([_load("aggregators", GREEN, "health.reason.ran")])
    box.run([_load("aggregators", YELLOW, "health.reason.late")])
    assert box.sent[0][1].startswith("🟡 Decimus · Агрегаторы")


def test_pointer_ключ_и_серое_не_оповещают(box: Box) -> None:
    box.run([_probe("openai", GREEN, "health.reason.ok")])
    box.run(
        [
            _probe("pointer", RED, "health.reason.rejected"),
            Row("backup", checks.PENDING, Status(GREY, "health.reason.backup_host")),
            _probe("openai", GREEN, "health.reason.ok"),
        ]
    )
    assert box.sent == []


def test_сбой_отправки_не_помечает_состояние_и_следующий_заход_повторит(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = Box(monkeypatch, fail=True)
    box.run([RS_OK])
    assert box.run([RS_EXPIRED]) == 0  # не упало
    assert box.levels["dodo_is:RS"] == "ok"  # не помечено оповещённым
    box.fail = False
    assert box.run([RS_EXPIRED]) == 1
    assert box.levels["dodo_is:RS"] == "red"


def test_после_сбоя_отправки_остальные_сообщения_захода_не_шлются(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = Box(monkeypatch, fail=True)
    box.run([RS_OK, _load("maps", GREEN, "health.reason.ran")])
    box.run([RS_EXPIRED, _load("maps", RED, "health.reason.failed")])
    assert box.levels == {"dodo_is:RS": "ok", "maps": "ok"}


# --- канал и демо ---------------------------------------------------------------------

CHANNEL_ENV = {"FURCA_NOTIFY_URL": "http://ch:8090", "FURCA_SECRET": "s"}


def test_без_адреса_или_ключа_оповещения_выключены() -> None:
    for env in ({}, {"FURCA_NOTIFY_URL": "http://ch:8090"}, {"FURCA_SECRET": "s"}):
        target, status = alerts.channel_state(env)
        assert target is None and status.reason == "health.reason.alerts_off"


def test_канал_задан_оповещения_включены() -> None:
    target, status = alerts.channel_state(CHANNEL_ENV)
    assert target == ("http://ch:8090/notify", "s") and status.light == GREEN


@pytest.mark.parametrize("demo", ["1", " 1 ", "true"])
def test_в_демо_оповещения_не_уходят_даже_при_заданном_канале(demo: str) -> None:
    target, status = alerts.channel_state({**CHANNEL_ENV, "WEB_DEMO": demo})
    assert target is None and status.reason == "health.reason.alerts_demo"


def test_заход_в_демо_ничего_не_отправляет_и_не_читает_состояний(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(health_store, "record", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "build_rows", lambda *a, **k: pytest.fail("демо читает базу"))
    count = alerts.run_pass(
        NOW, env={**CHANNEL_ENV, "WEB_DEMO": "1"}, send=lambda t, x, k: sent.append(x)
    )
    assert count == 0 and sent == []


# --- тексты ---------------------------------------------------------------------------


def test_три_сообщения_как_в_решении(box: Box) -> None:
    box.run([RS_OK, _load("aggregators", GREEN, "health.reason.ran")])
    box.run([RS_EXPIRED, _load("aggregators", YELLOW, "health.reason.late")])
    box.run([RS_OK])
    texts = [text for _, text in box.sent]
    assert len(texts) == 3
    red = next(t for t in texts if t.startswith("🔴"))
    assert red.startswith("🔴 Decimus · Dodo IS, Сербия: вход не работает — ")
    assert red.endswith(f"Администрирование → Dodo IS: {URL}")
    assert texts[0] == (
        "🟡 Decimus · Агрегаторы: сбор не пришёл в срок, последний удачный 25.10 03:10."
    )
    assert texts[2] == "🟢 Decimus · Dodo IS, Сербия: снова работает."


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_в_тексте_нет_кодов_причин(lang: str) -> None:
    rows = [
        RS_EXPIRED,
        _dodois("RS", RED, "health.reason.dodois_failed"),
        _dodois("RS", YELLOW, "health.reason.dodois_partial", open=1, total=2),
        _dodois("RS", YELLOW, "health.reason.stale"),
        _load("maps", RED, "health.reason.failed"),
        _load("maps", RED, "health.reason.stopped"),
        _load("maps", YELLOW, "health.reason.late"),
        _probe("storage", RED, "health.reason.unreachable"),
        _probe("openai", RED, "health.reason.rejected"),
    ]
    for row in rows:
        (signal,) = alerts.signals((row,))
        for kind in ("alert", "done"):
            text = alerts.compose(signal, kind, country_names=NAMES, url=URL, lang=lang)
            assert "health.reason" not in text and "dodois." not in text
            assert "{" not in text and "_" not in text.replace(URL, "")


def test_без_адреса_админки_сообщение_всё_равно_читается() -> None:
    (signal,) = alerts.signals((RS_EXPIRED,))
    text = alerts.compose(signal, "alert", country_names=NAMES, url=None)
    assert text.endswith("Администрирование → Dodo IS.") and "None" not in text


def test_время_последнего_удачного_берётся_из_строки_сбора() -> None:
    (signal,) = alerts.signals(
        (_load("sheet", YELLOW, "health.reason.late", LAST_OK + timedelta(hours=1)),)
    )
    assert "26.10" not in alerts.compose(signal, "alert", country_names={}, url=None)
    assert "25.10 04:10" in alerts.compose(signal, "alert", country_names={}, url=None)


@pytest.mark.parametrize("code", ["aggregators", "learning"])
def test_у_сборов_со_своей_тревогой_ошибка_не_оповещает_и_отбоя_без_нашей_тревоги_нет(
    box: Box, code: str
) -> None:
    box.run([_load(code, GREEN, "health.reason.ran")])
    box.run([_load(code, RED, "health.reason.failed")])
    box.run([_load(code, GREEN, "health.reason.ran")])
    assert box.sent == []


@pytest.mark.parametrize("code", ["aggregators", "learning"])
def test_у_сборов_со_своей_тревогой_срок_оповещает_и_отбой_после_нашей_тревоги(
    box: Box, code: str
) -> None:
    box.run([_load(code, GREEN, "health.reason.ran")])
    box.run([_load(code, YELLOW, "health.reason.late")])
    box.run([_load(code, RED, "health.reason.failed")])  # ошибка состояния не меняет
    box.run([_load(code, GREEN, "health.reason.ran")])
    assert [kind for kind, _ in box.sent] == ["alert", "done"]


def test_у_карт_без_своей_тревоги_ошибка_оповещает(box: Box) -> None:
    box.run([_load("maps", GREEN, "health.reason.ran")])
    box.run([_load("maps", RED, "health.reason.failed")])
    assert len(box.sent) == 1


# --- склейка (D678) -------------------------------------------------------------------

ME_OK = _dodois("ME", GREEN, "health.reason.dodois_ok", open=2, total=2)
RS_FAILED = _dodois("RS", RED, "health.reason.dodois_failed")
ME_FAILED = _dodois("ME", RED, "health.reason.dodois_failed")


def test_общий_сбой_нескольких_стран_одно_сообщение_со_списком(box: Box) -> None:
    box.run([RS_OK, ME_OK])
    sent = box.run([RS_FAILED, ME_FAILED])
    assert sent == 1 and len(box.sent) == 1
    kind, text = box.sent[0]
    assert kind == "alert"
    assert text.startswith("🔴 Decimus · Dodo IS: вход не работает — сбой связи")
    assert text.count("Администрирование → Dodo IS") == 1
    assert "Сербия" in text and "Черногория" in text


def test_учёт_отправленного_остаётся_на_каждую_страну(box: Box) -> None:
    box.run([RS_OK, ME_OK])
    box.run([RS_FAILED, ME_FAILED])
    assert box.levels == {"dodo_is:RS": "red", "dodo_is:ME": "red"}
    box.run([RS_FAILED, ME_FAILED])  # повтора нет
    assert len(box.sent) == 1


def test_снова_работает_нескольких_стран_одно_сообщение(box: Box) -> None:
    box.run([RS_OK, ME_OK])
    box.run([RS_FAILED, ME_FAILED])
    box.run([RS_OK, ME_OK])
    kind, text = box.sent[-1]
    assert len(box.sent) == 2 and kind == "done"
    assert text == "🟢 Decimus · Dodo IS снова работает: Черногория, Сербия."


def test_разные_причины_одна_строка_на_причину_и_один_хвост(box: Box) -> None:
    box.run([RS_OK, ME_OK])
    box.run([RS_EXPIRED, ME_FAILED])
    assert len(box.sent) == 1
    text = box.sent[0][1]
    lines = text.splitlines()
    assert lines[0] == "🔴 Decimus · Dodo IS:"
    # страны идут по коду: ME раньше RS
    assert lines[1].startswith("• вход не работает — сбой связи") and lines[1].endswith(
        ": Черногория."
    )
    assert lines[2].startswith("• вход не работает — вход истёк") and lines[2].endswith(": Сербия.")
    assert lines[3].startswith("Администрирование → Dodo IS: ") and len(lines) == 4


def test_разный_цвет_и_разный_вид_не_склеиваются(box: Box) -> None:
    box.run([RS_OK, ME_OK, _load("maps", GREEN, "health.reason.ran")])
    partial = _dodois("ME", YELLOW, "health.reason.dodois_partial", open=1, total=2)
    box.run([RS_FAILED, partial, _load("maps", RED, "health.reason.failed")])
    assert len(box.sent) == 3
    assert sorted(t.split()[0] for _, t in box.sent) == ["🔴", "🔴", "🟡"]


def test_один_сигнал_в_виде_остаётся_прежним_текстом(box: Box) -> None:
    box.run([RS_OK, ME_OK])
    box.run([RS_FAILED, ME_OK])
    assert box.sent[0][1].startswith("🔴 Decimus · Dodo IS, Сербия: вход не работает — ")


def test_сбой_отправки_склейки_не_помечает_ни_одну_страну(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(monkeypatch)
    box.run([RS_OK, ME_OK])
    box.fail = True
    box.run([RS_FAILED, ME_FAILED])
    assert box.levels == {"dodo_is:RS": "ok", "dodo_is:ME": "ok"}
    box.fail = False
    box.run([RS_FAILED, ME_FAILED])
    assert len(box.sent) == 1 and box.levels["dodo_is:RS"] == "red"
