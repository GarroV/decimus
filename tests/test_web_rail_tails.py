"""Доделки колонки чек-листов (#425): то, что молча мешает работать.

Отказ заведения, стерев введённое, заставляет набирать заново и путает, что
именно отвергнуто. Ссылки режима выбора, подставившие чек-лист по умолчанию,
закрывают панель не туда, откуда её открыли.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import methodology as method

ТЕНАНТ = "default"


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")  # D344
    методика = tmp_path / "живая-методика"
    build_edition(методика, name="imf", day="2026-09-01")
    monkeypatch.setenv(method.STORE_VAR, str(tmp_path / "хранилище"))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        войти(client)
        yield client


def test_отказ_заведения_оставляет_введённое(клиент: FlaskClient) -> None:
    клиент.get("/admin")
    ответ = клиент.post(
        "/admin/checklists",
        data={"back": "admin", "code": "bizdev", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        headers={"Origin": СВОЙ},
    )

    текст = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert 'value="Аудит РНД"' in текст and 'value="RnD audit"' in текст
    assert 'value="bizdev"' in текст


def test_пустая_форма_на_открытии_пуста(клиент: FlaskClient) -> None:
    текст = клиент.get("/admin?panel=new").get_data(as_text=True)

    assert 'name="name_ru" required autocomplete="off" value=""' in текст


def _ссылка_нового(текст: str) -> str:
    import re

    найдено = re.search(r'href="([^"]*panel=new[^"]*)"', текст)
    assert найдено, "ссылки «+ Новый» нет"
    return найдено.group(1)


@pytest.mark.parametrize(
    ("адрес", "назван"),
    [("/admin", False), ("/admin?checklist=bizdev", True)],
)
def test_ссылки_называют_чек_лист_только_если_он_назван(
    клиент: FlaskClient, адрес: str, назван: bool
) -> None:
    ссылка = _ссылка_нового(клиент.get(адрес).get_data(as_text=True))

    assert ("checklist=bizdev" in ссылка) is назван, ссылка
