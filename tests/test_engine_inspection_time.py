"""D730: строка «Время проверки» в шапке отчёта — есть, когда есть начало, и нет, когда его нет."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Run

START = "2026-11-09T03:15:00+00:00"
END = "2026-11-09T05:40:30+00:00"
ПОДПИСЬ = {"ru": "Время проверки", "en": "Inspection time"}


def строка(html: str, lang: str) -> str | None:
    m = re.search(rf'<td class="k">{ПОДПИСЬ[lang]}</td><td>([^<]*)</td>', html)
    return m.group(1) if m else None


def html_of(report: Callable[..., Run], *args: str) -> str:
    r = report("html", *args)
    assert r.code == 0, r.text
    return r.out


@pytest.mark.parametrize(
    ("lang", "ожидание"),
    [("ru", "10:15–12:40 (2 ч 25 мин)"), ("en", "10:15–12:40 (2 h 25 min)")],
)
def test_строка_в_шапке_по_местному_времени(
    audit: Callable[..., Run], report: Callable[..., Run], lang: str, ожидание: str
) -> None:
    assert audit("init", "--unit", "Тестовая", "--lang", "ru").code == 0
    html = html_of(
        report, "--lang", lang, f"--started-at={START}", f"--finished-at={END}", "--tz=Asia/Jakarta"
    )
    assert строка(html, lang) == ожидание


def test_без_конца_только_начало(audit: Callable[..., Run], report: Callable[..., Run]) -> None:
    assert audit("init", "--unit", "Тестовая", "--lang", "ru").code == 0
    html = html_of(report, f"--started-at={START}", "--tz=Asia/Jakarta")
    assert строка(html, "ru") == "начало 10:15"


def test_без_зоны_utc_с_пометкой(audit: Callable[..., Run], report: Callable[..., Run]) -> None:
    assert audit("init", "--unit", "Тестовая", "--lang", "ru").code == 0
    html = html_of(report, f"--started-at={START}", f"--finished-at={END}")
    assert строка(html, "ru") == "03:15–05:40 UTC (2 ч 25 мин)"


def test_без_начала_строки_нет(audit: Callable[..., Run], report: Callable[..., Run]) -> None:
    assert audit("init", "--unit", "Тестовая", "--lang", "ru").code == 0
    # Конец без начала ничего не стоит: начала нет — строки нет, длительность не выдумывается.
    html = html_of(report, f"--finished-at={END}", "--tz=Asia/Jakarta")
    assert ПОДПИСЬ["ru"] not in html


def test_время_из_шапки_состояния_веб_путь(
    audit: Callable[..., Run], report: Callable[..., Run], workdir: Path
) -> None:
    """Веб собирает состояние из базы (`state_json`): время лежит в meta, флагов нет."""
    assert audit("init", "--unit", "Тестовая", "--lang", "ru").code == 0
    path = workdir / "inspection.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["meta"].update({"started_at": START, "finished_at": END, "tz": "Asia/Jakarta"})
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    assert строка(html_of(report), "ru") == "10:15–12:40 (2 ч 25 мин)"
