"""Предписания на экране: заслоны разделов, кто что может отправить, выдача файла (волна 3).

Ядро здесь — заслоны (D264, D284): раздел УК отказывает партнёру на каждом
маршруте, а не только в панели; ответ — только партнёру; чужое предписание и
файл — тот же 404, что несуществующие. Двери блока `db` подменены: что держит
база, проверяет `tests/test_db_prescriptions.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import prescriptions as rx
from src.db import prescriptions_write as rxw
from src.web import prescriptions as web_rx

ORIGIN = {"Origin": "http://localhost"}
ИД = "11111111-1111-1111-1111-111111111111"
ОТВЕТ = "22222222-2222-2222-2222-222222222222"


def предписание(*, status: str = "issued") -> rx.Prescription:
    отправлено = status != "draft"
    return rx.Prescription(
        id=ИД,
        country="GE",
        due_on=date(2030, 1, 1),
        recipients="ops@ge.example.com",
        subject="Предписание · Грузия",
        body="Строка один\n<script>alert(1)</script>",
        status=status,
        created_by="hq-lead",
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
        issued_by="hq-lead" if отправлено else None,
        issued_at=datetime(2026, 10, 5, tzinfo=UTC) if отправлено else None,
        closed_by="hq-lead" if status == "closed" else None,
        closed_at=datetime(2026, 10, 6, tzinfo=UTC) if status == "closed" else None,
        close_comment="выполнено" if status == "closed" else None,
    )


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Двери блока `db` предписаний, подменённые и пишущие, кого звали."""
    журнал: dict[str, list[dict[str, Any]]] = {
        имя: [] for имя in ("list", "get", "create", "update", "close", "reply", "file", "issue")
    }

    def записать(имя: str, результат: Any = None) -> Any:
        def дверь(*args: Any, **kw: Any) -> Any:
            журнал[имя].append({"args": args, **kw})
            return результат

        return дверь

    monkeypatch.setattr(
        rx,
        "list_prescriptions",
        записать("list", rx.PrescriptionList(rows=(предписание(),), truncated=False)),
    )
    monkeypatch.setattr(rx, "get_prescription", записать("get", предписание()))
    monkeypatch.setattr(rx, "file_for_download", записать("file", None))
    monkeypatch.setattr(rx, "choices", lambda *_a, **_k: ((), ()))
    monkeypatch.setattr(rx, "remembered_recipients", lambda _c: "ops@ge.example.com")
    monkeypatch.setattr(rxw, "create_draft", записать("create", ИД))
    monkeypatch.setattr(rxw, "update_draft", записать("update"))
    monkeypatch.setattr(rxw, "close", записать("close"))
    monkeypatch.setattr(rxw, "reply", записать("reply", ОТВЕТ))
    monkeypatch.setattr(rxw, "issue", записать("issue"))
    monkeypatch.setattr("src.web.country.countries", lambda **_: (("GE", 2), ("AM", 1)))
    return журнал


def _стенд(monkeypatch: pytest.MonkeyPatch, tenant: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role="admin")
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def уК(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "HQ")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, "GE")


ФОРМА = {
    "country": "GE",
    "due": "2030-01-01",
    "recipients": "ops@ge.example.com",
    "subject": "Тема",
    "body": "Текст",
    "comment": "закрыто",
}

МАРШРУТЫ_УК = [
    ("get", "/actions/prescriptions"),
    ("get", "/actions/prescriptions/new?country=GE"),
    ("post", "/actions/prescriptions"),
    ("get", f"/actions/prescriptions/{ИД}"),
    ("get", f"/actions/prescriptions/{ИД}/edit"),
    ("post", f"/actions/prescriptions/{ИД}/edit"),
    ("post", f"/actions/prescriptions/{ИД}/send"),
    ("post", f"/actions/prescriptions/{ИД}/close"),
]


@pytest.mark.parametrize(("метод", "адрес"), МАРШРУТЫ_УК)
def test_раздел_уК_отказывает_партнёру_на_каждом_маршруте(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], метод: str, адрес: str
) -> None:
    ответ = getattr(партнёр, метод)(адрес, data=ФОРМА, headers=ORIGIN)
    assert ответ.status_code == 404
    assert зовы["create"] == зовы["update"] == зовы["close"] == зовы["issue"] == []


@pytest.mark.parametrize(("метод", "адрес"), МАРШРУТЫ_УК)
def test_второй_заслон_держит_и_без_флага_в_реестре(
    партнёр: FlaskClient,
    зовы: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    метод: str,
    адрес: str,
) -> None:
    """Флаг `hq_only` сняли по ошибке — маршрут всё равно отказывает сам."""
    monkeypatch.setattr("src.web.app.refused_for", lambda *_: False)
    ответ = getattr(партнёр, метод)(адрес, data=ФОРМА, headers=ORIGIN)
    assert ответ.status_code == 404
    assert зовы["create"] == зовы["update"] == зовы["close"] == зовы["issue"] == []


def test_уК_ответ_за_партнёра_не_кладёт(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(f"/prescriptions/{ИД}/reply", data={"comment": "x"}, headers=ORIGIN)
    assert ответ.status_code == 403
    assert зовы["reply"] == []


def test_уК_в_разделе_партнёра_уходит_в_свой(уК: FlaskClient) -> None:
    assert уК.get("/prescriptions").headers["Location"].startswith("/actions/prescriptions")
    assert (
        уК.get(f"/prescriptions/{ИД}")
        .headers["Location"]
        .startswith(f"/actions/prescriptions/{ИД}")
    )


def test_чужое_предписание_это_404(партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rx, "get_prescription", lambda *_a, **_k: None)
    нет = партнёр.get(f"/prescriptions/{ИД}?lang=ru")
    assert нет.status_code == 404
    # Отказ говорит о предписании и ведёт к предписаниям, а не к проверкам.
    assert "Предписание не найдено" in нет.get_data(as_text=True)
    assert 'href="/prescriptions?lang=ru"' in нет.get_data(as_text=True)
    ответ = партнёр.post(f"/prescriptions/{ИД}/reply", data={"comment": "x"}, headers=ORIGIN)
    assert ответ.status_code in (400, 404)


def test_чужой_файл_это_404(партнёр: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    assert партнёр.get(f"/prescriptions/files/{ОТВЕТ}").status_code == 404
    assert зовы["file"][-1]["reach"].tenant == "GE"


def test_панель_партнёру_зовёт_в_предписания_а_не_в_действия(партнёр: FlaskClient) -> None:
    страница = партнёр.get("/prescriptions?lang=ru").get_data(as_text=True)
    assert 'href="/prescriptions' in страница
    assert 'href="/actions' not in страница


def test_письмо_выводится_текстом_а_не_разметкой(партнёр: FlaskClient) -> None:
    страница = партнёр.get(f"/prescriptions/{ИД}?lang=ru").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in страница
    assert "&lt;script&gt;" in страница


def test_партнёр_отвечает_своим_охватом(партнёр: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = партнёр.post(
        f"/prescriptions/{ИД}/reply?lang=ru", data={"comment": "сделали"}, headers=ORIGIN
    )
    assert ответ.status_code == 200
    assert "Ответ сохранён" in ответ.get_data(as_text=True)
    вызов = зовы["reply"][-1]
    assert (вызов["tenant"], вызов["reach"].tenant, вызов["attachment"]) == ("GE", "GE", None)


def test_ответ_на_закрытое_формы_не_показывает(
    партнёр: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rx, "get_prescription", lambda *_a, **_k: предписание(status="closed"))
    страница = партнёр.get(f"/prescriptions/{ИД}?lang=ru").get_data(as_text=True)
    assert "Отправить ответ" not in страница
    assert "ответить на него уже нельзя" in страница


# --- раздел УК -------------------------------------------------------------


def test_уК_видит_очередь_и_вкладки(уК: FlaskClient) -> None:
    страница = уК.get("/actions/prescriptions?lang=ru").get_data(as_text=True)
    assert "Предписание · Грузия" in страница
    assert "Черновики · 0" in страница and "Просрочены · 0" in страница
    assert 'href="/actions?lang=ru"' in страница, "вкладки «Экшн-планы» нет"


def test_форма_подставляет_адресатов_страны(уК: FlaskClient) -> None:
    страница = уК.get("/actions/prescriptions/new?country=GE&lang=ru").get_data(as_text=True)
    assert 'value="ops@ge.example.com"' in страница


def test_сохранить_черновик_ведёт_на_карточку(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.post(
        "/actions/prescriptions?lang=ru", data={**ФОРМА, "then": "save"}, headers=ORIGIN
    )
    assert ответ.status_code == 303
    assert ответ.headers["Location"].startswith(f"/actions/prescriptions/{ИД}")
    черновик = зовы["create"][-1]["args"][0]
    assert (черновик.country, черновик.subject, черновик.unit_ids) == ("GE", "Тема", ())


def test_без_реквизитов_google_экран_говорит_словами(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    for имя in ("GOOGLE_CLIENT_ID", "GOOGLE_MAIL_REDIRECT_URI"):
        monkeypatch.delenv(имя, raising=False)
    ответ = уК.post(f"/actions/prescriptions/{ИД}/send?lang=ru", headers=ORIGIN)
    assert ответ.status_code == 303 and "gmail=unavailable" in ответ.headers["Location"]
    assert зовы["issue"] == [], "без почты предписание не отправляется"


def test_отправленное_нельзя_открыть_на_правку(уК: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = уК.get(f"/actions/prescriptions/{ИД}/edit?lang=ru")
    assert ответ.status_code == 303
    assert ответ.headers["Location"].endswith(f"/actions/prescriptions/{ИД}?lang=ru")


def test_у_отправленного_нет_кнопки_в_gmail_а_есть_закрыть(уК: FlaskClient) -> None:
    страница = уК.get(f"/actions/prescriptions/{ИД}?lang=ru").get_data(as_text=True)
    assert "Положить в Gmail" not in страница and "Изменить черновик" not in страница
    assert "Закрыть предписание" in страница


def _кука_похода(клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch, state: str = "м") -> str:
    """Подписанная кука похода за почтой — собрана секретом стенда."""
    import hashlib

    from itsdangerous import URLSafeTimedSerializer
    from web_harness import СЕКРЕТ

    from src.web import letter_draft

    for имя, значение in {
        "GOOGLE_CLIENT_ID": "клиент",
        "GOOGLE_CLIENT_SECRET": "секрет",
        "GOOGLE_REDIRECT_URI": "https://стенд/auth/google/callback",
        "GOOGLE_MAIL_REDIRECT_URI": "https://стенд/auth/google/mail",
    }.items():
        monkeypatch.setenv(имя, значение)
    monkeypatch.setattr(letter_draft, "exchange_code_for_token", lambda _s, *, code: "токен")
    подписант = URLSafeTimedSerializer(
        СЕКРЕТ,
        salt=letter_draft.MAIL_STATE_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )
    клиент.set_cookie(
        letter_draft.MAIL_STATE_COOKIE,
        подписант.dumps({"state": state, "kind": web_rx.MAIL_KIND, "id": ИД, "lang": "ru"}),
    )
    return letter_draft.MAIL_STATE_COOKIE


def _кука_снята(ответ: Any, имя: str) -> bool:
    return any(
        h.startswith(f"{имя}=;") and ("Max-Age=0" in h or "1970" in h)
        for h in ответ.headers.getlist("Set-Cookie")
    )


def test_возврат_от_google_партнёру_не_отправляет(
    партнёр: FlaskClient, зовы: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Возврат — общий адрес `/auth/google/mail`; раздел УК его не прикрывает.

    Кука похода подписана секретом стенда — здесь она собрана им же, как будто
    партнёр как-то её получил: возврат всё равно отказывает сам.
    """
    кука = _кука_похода(партнёр, monkeypatch)

    ответ = партнёр.get("/auth/google/mail?state=м&code=к")

    assert ответ.status_code == 404
    assert зовы["issue"] == []
    assert _кука_снята(ответ, кука), "кука похода пережила отказ"


@pytest.mark.parametrize(
    "запрос",
    [
        "/auth/google/mail?state=м&error=access_denied",
        "/auth/google/mail?state=чужая&code=к",
        "/auth/google/mail?state=м",
    ],
    ids=["отказ в доступе", "не та метка", "нет кода"],
)
def test_кука_похода_снимается_на_любом_исходе(
    уК: FlaskClient, зовы: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch, запрос: str
) -> None:
    кука = _кука_похода(уК, monkeypatch)

    ответ = уК.get(запрос)

    assert ответ.status_code in (302, 303)
    assert зовы["issue"] == []
    assert _кука_снята(ответ, кука), "кука похода пережила исход без отправки"


def test_форма_говорит_сколько_проверок_показано(
    уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    основание = rx.Choice(id=ИД, title="Batumi-1 · 2026-09-02", detail="A")
    monkeypatch.setattr(rx, "choices", lambda *_a, **_k: ((), (основание,)))
    страница = уК.get("/actions/prescriptions/new?country=GE&lang=ru").get_data(as_text=True)
    assert f"Последние {rx.BASES_LIMIT} принятых проверок" in страница
