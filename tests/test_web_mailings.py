"""Вкладка «Письма и уведомления» (D608, #1130): права, список копий, ничего не отправляется.

Ядро — права: правят админ УК и главный админ (`mailing.manage`), остальным 404 и на чтение,
и на каждый POST. И граница «только хранение»: правка списка не зовёт ни почту, ни сеть, а
копия попадает в черновик только для проверок пространства УК. Двери базы подменены: что
держит сама таблица, проверяет `tests/test_db_mailing_cc.py`.
"""

from __future__ import annotations

import email as stdlib_email
from collections.abc import Iterator
from email import policy
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import mailing_cc
from src.db.errors import ConfigError, MailingCcError
from src.web import google_mail, letter_draft

РАЗДЕЛ = "/administration"
ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПОЧТА = "boss@dodobrands.io"
МОГУТ = [("HQ", "superadmin"), ("HQ", "admin")]
НЕ_МОГУТ = [
    ("HQ", "osb"),
    ("HQ", "developer"),
    ("HQ", "control"),
    ("HQ", "guest"),
    ("GE", "admin"),
    ("GE", "auditor"),
]


@pytest.fixture
def список(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Список копий в памяти и журнал обращений к нему."""
    хранилище: dict[str, list[str]] = {k: [] for k in mailing_cc.KINDS}
    журнал: dict[str, Any] = {"add": [], "remove": [], "store": хранилище}

    def add(kind: str, email: str, *, actor: str) -> bool:
        журнал["add"].append((kind, email, actor))
        адрес = mailing_cc.clean_email(email)
        if адрес in хранилище[kind]:
            return False
        хранилище[kind].append(адрес)
        return True

    def remove(kind: str, email: str) -> None:
        журнал["remove"].append((kind, email))
        if email not in хранилище[kind]:
            raise MailingCcError("Такого адреса в списке нет")
        хранилище[kind].remove(email)

    monkeypatch.setattr(mailing_cc, "read", lambda kind: tuple(хранилище[kind]))
    monkeypatch.setattr(mailing_cc, "counts", lambda: {k: len(v) for k, v in хранилище.items()})
    monkeypatch.setattr(mailing_cc, "add", add)
    monkeypatch.setattr(mailing_cc, "remove", remove)
    return журнал


def _вошёл(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.mark.parametrize(("tenant", "role"), МОГУТ)
def test_правят_админ_и_главный_админ(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any], tenant: str, role: str
) -> None:
    client = next(_вошёл(monkeypatch, tenant, role))
    assert client.get(f"{РАЗДЕЛ}?tab=mailings").status_code == 200
    ответ = client.post(
        f"{РАЗДЕЛ}/mailings/inspection/cc/add", data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 303
    assert список["store"]["inspection"] == [ПОЧТА]


@pytest.mark.parametrize(("tenant", "role"), НЕ_МОГУТ)
def test_остальным_404_на_чтение_и_на_каждое_действие(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any], tenant: str, role: str
) -> None:
    client = next(_вошёл(monkeypatch, tenant, role))
    assert client.get(f"{РАЗДЕЛ}?tab=mailings").status_code == 404
    for действие in ("add", "remove"):
        ответ = client.post(
            f"{РАЗДЕЛ}/mailings/inspection/cc/{действие}",
            data={"email": ПОЧТА},
            headers=ЗАГОЛОВКИ,
        )
        assert ответ.status_code in (403, 404), (role, действие)
    assert not список["add"] and not список["remove"], "без права база не тронута"


def test_панель_показывает_адреса_и_убирает(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any]
) -> None:
    список["store"]["inspection"].append(ПОЧТА)
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    страница = client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection").get_data(as_text=True)
    assert ПОЧТА in страница and "mailings/inspection/cc/remove" in страница
    ответ = client.post(
        f"{РАЗДЕЛ}/mailings/inspection/cc/remove", data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 303 and "saved=ok" in ответ.headers["Location"]
    assert список["store"]["inspection"] == []


def test_кривой_адрес_и_повтор_называются_словами(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any]
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    адрес = f"{РАЗДЕЛ}/mailings/inspection/cc/add"
    кривой = client.post(адрес, data={"email": "не почта"}, headers=ЗАГОЛОВКИ)
    assert "saved=invalid" in кривой.headers["Location"]
    два = client.post(адрес, data={"email": "a@x.io, b@x.io"}, headers=ЗАГОЛОВКИ)
    assert "saved=invalid" in два.headers["Location"]
    client.post(адрес, data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ)
    повтор = client.post(адрес, data={"email": ПОЧТА.upper()}, headers=ЗАГОЛОВКИ)
    assert "saved=exists" in повтор.headers["Location"]
    assert список["store"]["inspection"] == [ПОЧТА]


def test_неизвестный_вид_404(monkeypatch: pytest.MonkeyPatch, список: dict[str, Any]) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    assert client.get(f"{РАЗДЕЛ}?tab=mailings&kind=nope").status_code == 404
    ответ = client.post(f"{РАЗДЕЛ}/mailings/nope/cc/add", data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 404


def test_чужое_происхождение_не_пишет(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any]
) -> None:
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    ответ = client.post(
        f"{РАЗДЕЛ}/mailings/inspection/cc/add",
        data={"email": ПОЧТА},
        headers={"Origin": "https://evil.example"},
    )
    assert ответ.status_code == 403
    assert not список["add"]


def test_правка_списка_ничего_не_отправляет(
    monkeypatch: pytest.MonkeyPatch, список: dict[str, Any]
) -> None:
    """Вкладка только хранит: ни почта, ни сеть не вызываются (правило «без «да» не слать»)."""
    вызовы: list[str] = []

    def запретить(*_a: object, **_k: object) -> None:
        вызовы.append("вызван")
        raise AssertionError("правка списка копий не должна ничего отправлять")

    monkeypatch.setattr(google_mail, "create_draft", запретить)
    monkeypatch.setattr(letter_draft, "create_draft", запретить)
    monkeypatch.setattr(google_mail.urllib.request, "urlopen", запретить)
    client = next(_вошёл(monkeypatch, "HQ", "admin"))
    client.get(f"{РАЗДЕЛ}?tab=mailings&kind=inspection")
    client.post(f"{РАЗДЕЛ}/mailings/inspection/cc/add", data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ)
    client.post(f"{РАЗДЕЛ}/mailings/inspection/cc/remove", data={"email": ПОЧТА}, headers=ЗАГОЛОВКИ)
    assert вызовы == []


# --- копия в черновике -----------------------------------------------------------------------


def test_письмо_несёт_копию_в_заголовке_cc() -> None:
    письмо = google_mail.letter_message(
        to="p@x.io", subject="Тема", body="Здравствуйте!", cc=("a@dodobrands.io", ПОЧТА)
    )
    разобрано = stdlib_email.message_from_bytes(письмо.as_bytes(), policy=policy.default)
    assert разобрано["Cc"] == f"a@dodobrands.io, {ПОЧТА}"
    assert разобрано["To"] == "p@x.io"


def test_без_списка_заголовка_cc_нет() -> None:
    письмо = google_mail.letter_message(to="p@x.io", subject="Тема", body="Здравствуйте!")
    assert письмо["Cc"] is None


def test_копия_ук_только_для_проверок_пространства_ук(список: dict[str, Any]) -> None:
    список["store"]["inspection"].append(ПОЧТА)
    assert letter_draft._копия_ук("HQ") == (ПОЧТА,)
    assert letter_draft._копия_ук("default") == (ПОЧТА,), "старый код УК — тоже УК"
    assert letter_draft._копия_ук("GE") == (), "копия УК не уходит в письма партнёров"


@pytest.mark.parametrize("ошибка", [MailingCcError("база не ответила"), ConfigError("нет базы")])
def test_список_не_прочитался_черновик_без_копии(
    monkeypatch: pytest.MonkeyPatch, ошибка: Exception
) -> None:
    def сбой(_kind: str) -> tuple[str, ...]:
        raise ошибка

    monkeypatch.setattr(mailing_cc, "read", сбой)
    assert letter_draft._копия_ук("HQ") == ()
