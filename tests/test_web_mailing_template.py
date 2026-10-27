"""Шаблон письма во вкладке «Письма и уведомления» (#977, #1130, этап 1б): права и границы.

Ядро: правят админ УК и главный админ, остальным 404 на чтение и на сохранение; неизвестная
подстановка отклоняется с причиной, а введённый текст остаётся в поле; письмо по сохранённому
тексту собирается только для проверок пространства УК; вкладка ничего не отправляет. Двери
базы подменены: версии и права таблицы проверяет `tests/test_db_mailing_templates.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import mailing_templates as store
from src.web import google_mail, inspections, mailings_template

РАЗДЕЛ = "/administration"
ЗАГОЛОВКИ = {"Origin": СВОЙ}
АДРЕС = f"{РАЗДЕЛ}/mailings/inspection/template"
ВСТРОЕННЫЙ = "Встроенный текст {unit}"
МОГУТ = [("HQ", "superadmin"), ("HQ", "admin")]
НЕ_МОГУТ = [("HQ", "osb"), ("HQ", "guest"), ("GE", "admin"), ("GE", "auditor")]


@pytest.fixture
def шаблоны(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Версии шаблонов в памяти и журнал обращений к ним."""
    версии: dict[tuple[str, str], list[store.Version]] = {}
    журнал: dict[str, Any] = {"save": [], "версии": версии}

    def save(
        slot: str, lang: str, body: str | None, *, actor: str, kind: str = "inspection"
    ) -> int:
        журнал["save"].append((slot, lang, body, actor))
        ряд = версии.setdefault((slot, lang), [])
        ряд.append(store.Version(len(ряд) + 1, body, actor, datetime.now(UTC)))
        return len(ряд)

    monkeypatch.setattr(
        store, "current", lambda kind="inspection": {k: v[-1] for k, v in версии.items()}
    )
    monkeypatch.setattr(
        store,
        "history",
        lambda slot, lang, kind="inspection", limit=10: tuple(
            reversed(версии.get((slot, lang), []))
        ),
    )
    monkeypatch.setattr(store, "save", save)
    monkeypatch.setattr(
        mailings_template,
        "builtin_bodies",
        lambda: {
            s: {"ru": ВСТРОЕННЫЙ, "en": "Built-in {unit}"} for s in ("plan", "clean", "empty")
        },
    )
    return журнал


def _вошёл(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _сохранить(client: FlaskClient, тело: str, **extra: str) -> Any:
    данные = {"slot": "plan", "lang": "ru", "body": тело, "action": "save", **extra}
    return client.post(АДРЕС, data=данные, headers=ЗАГОЛОВКИ)


@pytest.mark.parametrize(("tenant", "role"), МОГУТ)
def test_правят_админ_и_главный_админ(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any], tenant: str, role: str
) -> None:
    client = next(_вошёл(monkeypatch, tenant, role))
    страница = client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection&slot=plan&tlang=ru")
    assert страница.status_code == 200
    assert ВСТРОЕННЫЙ in страница.get_data(as_text=True), "в поле — встроенный текст движка"
    ответ = _сохранить(client, "Новый текст {unit}, оценка {grade}")
    assert ответ.status_code == 303
    assert шаблоны["save"][0][:3] == ("plan", "ru", "Новый текст {unit}, оценка {grade}")


@pytest.mark.parametrize(("tenant", "role"), НЕ_МОГУТ)
def test_остальным_404_на_чтение_и_на_сохранение(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any], tenant: str, role: str
) -> None:
    client = next(_вошёл(monkeypatch, tenant, role))
    assert client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection").status_code == 404
    assert _сохранить(client, "Текст {unit}").status_code in (403, 404)
    assert шаблоны["save"] == [], "без права база не тронута"


def test_неизвестная_подстановка_отклонена_текст_остаётся_в_поле(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any]
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    ответ = _сохранить(client, "Мой текст про {bogus}")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 400
    assert "Мой текст про {bogus}" in html, "введённое не пропадает"
    assert "{bogus}" in html and "неизвестный блок" in html.lower()
    assert шаблоны["save"] == [], "отклонённый текст в базу не идёт"


def test_вернуть_встроенный_пишет_версию_без_текста(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any]
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    _сохранить(client, "Свой {unit}")
    ответ = client.post(
        АДРЕС, data={"slot": "plan", "lang": "ru", "action": "reset"}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 303
    assert [v.body for v in шаблоны["версии"][("plan", "ru")]] == ["Свой {unit}", None]


@pytest.mark.parametrize(("slot", "lang"), [("nope", "ru"), ("plan", "de")])
def test_неизвестный_слот_или_язык_404(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any], slot: str, lang: str
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    ответ = client.post(
        АДРЕС, data={"slot": slot, "lang": lang, "body": "x {unit}"}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 404
    assert (
        client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection&slot={slot}&tlang={lang}").status_code
        == 404
    )


def test_чужое_происхождение_не_пишет(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any]
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    ответ = client.post(
        АДРЕС,
        data={"slot": "plan", "lang": "ru", "body": "x {unit}"},
        headers={"Origin": "https://evil.example"},
    )
    assert ответ.status_code == 403
    assert шаблоны["save"] == []


def test_сохранение_и_показ_ничего_не_отправляют(
    monkeypatch: pytest.MonkeyPatch, шаблоны: dict[str, Any]
) -> None:
    """Вкладка только хранит: ни почта, ни сеть не вызываются (правило «без «да» не слать»)."""

    def запретить(*_a: object, **_k: object) -> None:
        raise AssertionError("шаблон письма не должен ничего отправлять")

    monkeypatch.setattr(google_mail, "create_draft", запретить)
    monkeypatch.setattr(google_mail.urllib.request, "urlopen", запретить)
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection&slot=plan&tlang=ru")
    assert _сохранить(client, "Текст {unit}").status_code == 303


def test_хранимый_текст_идёт_в_письма_только_пространства_ук(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "bodies", lambda kind="inspection": {"ru": {"plan": "Свой {unit}"}})
    assert inspections.stored_letter_bodies("HQ") == {"ru": {"plan": "Свой {unit}"}}
    assert inspections.stored_letter_bodies("GE") == {}


def test_база_шаблонов_недоступна_письмо_идёт_по_встроенному(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.db.errors import MailingTemplateError

    def упасть(kind: str = "inspection") -> dict[str, Any]:
        raise MailingTemplateError("нет базы")

    monkeypatch.setattr(store, "bodies", упасть)
    assert inspections.stored_letter_bodies("HQ") == {}
