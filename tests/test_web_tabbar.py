"""Нижняя панель телефона: не больше пяти пунктов, остальное под «Ещё» (D518, #686).

На 390px девять разделов обрезали подписи многоточием. Базы нет: панель
смотрится на «Настройках» — они рисуются без неё, а панель общая на все экраны.
"""

from __future__ import annotations

import re

import pytest
from web_harness import войти, подменить_двери, собрать

from src.web.sections import TABBAR_MAX


def _панель(monkeypatch: pytest.MonkeyPatch, role: str) -> str:
    подменить_двери(monkeypatch, tenant="HQ", role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        страница = client.get("/settings").get_data(as_text=True)
    return страница.split('<nav class="tabbar"')[1].split("</nav>")[0]


def test_у_админа_ук_четыре_пункта_и_ещё_с_остальными(monkeypatch: pytest.MonkeyPatch) -> None:
    панель = _панель(monkeypatch, "admin")
    в_панели, ещё = панель.split('<details class="tabbar__more">')

    assert re.findall(r'class="tabbar__item[^"]*"\s+href="/(\w+)', в_панели) == [
        "overview",
        "inspections",
        "calendar",
        "actions",
    ]
    assert len(re.findall(r'class="tabbar__item', панель)) == TABBAR_MAX  # 4 + «Ещё»
    assert re.findall(r'class="tabbar__row[^"]*"\s+href="/(\w+)', ещё) == [
        "osb",
        "country",
        "ratings",
        "training",
        "admin",
        "administration",
    ]
    # «Настройки» не раздел панели: ничего не подсвечено.
    assert "is-current" not in панель


def test_открытый_раздел_из_ещё_подсвечивает_ещё(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        страница = client.get("/administration?tab=people&person=me").get_data(as_text=True)
    ещё = страница.split('<details class="tabbar__more">')[1].split("</details>")[0]

    assert '<summary class="tabbar__item is-current">' in ещё
    assert re.findall(r'class="tabbar__row is-current"\s+href="/(\w+)', ещё) == ["administration"]


def test_пять_и_меньше_разделов_без_ещё(monkeypatch: pytest.MonkeyPatch) -> None:
    панель = _панель(monkeypatch, "control")

    assert "tabbar__more" not in панель
    assert re.findall(r'class="tabbar__item[^"]*"\s+href="/(\w+)', панель) == [
        "ratings",
        "administration",
    ]
