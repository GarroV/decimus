# ruff: noqa: F811
"""D465: на приёмке в панели добавляют запись и меняют кадры — поверхность и двери.

Что доходит до двери блока `db`, кто может отправить форму, как показан отказ и
что в панели (заголовок `X-Panel`) возвращается карточка, а не страница.
Сами записи в базу проверяет `test_db_review_edit.py`.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from flask.testing import FlaskClient
from PIL import Image
from test_web_acceptance import ORIGIN, _приёмка, админ, стенд  # noqa: F401
from test_web_partner_no_retro import ПАРТНЁР, _двери
from web_harness import войти, собрать

from src.db.errors import ReviseError
from src.domain.tenants import canonical_tenant
from src.web import revision
from src.web.app import PANEL_HEADER

ID = "11111111-1111-1111-1111-111111111111"
ЗАПИСЬ = "22222222-2222-2222-2222-222222222222"
КАДР = "33333333-3333-3333-3333-333333333333"
ФОРМА = {"code": "CLN05", "level": "D2", "zone": "KITCHEN", "text": "пол в зале"}


def _jpeg() -> bytes:
    буфер = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(буфер, format="JPEG")
    return буфер.getvalue()


def _файл(байты: bytes | None = None, имя: str = "p.jpg") -> tuple[io.BytesIO, str]:
    return io.BytesIO(_jpeg() if байты is None else байты), имя


def _двери_кадров(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    зовы: list[tuple[str, dict[str, Any]]] = []

    def запись(имя: str) -> Any:
        def дверь(*a: Any, **kw: Any) -> str:
            зовы.append((имя, {"args": a, **kw}))
            return "new-id"

        return дверь

    for имя in ("add_card", "attach_photo", "replace_photo", "detach_photo"):
        monkeypatch.setattr(revision, имя, запись(имя))
    return зовы


@админ
def test_добавление_записи_доходит_до_двери_и_показывает_итог(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _приёмка(monkeypatch)
    зовы = _двери_кадров(monkeypatch)

    # Act
    ответ = стенд.post(
        "/inspections/x/findings",
        data={**ФОРМА, "photo": _файл()},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )

    # Assert
    assert ответ.status_code == 200
    [(имя, поля)] = зовы
    assert имя == "add_card" and поля["args"] == ("x",)
    assert поля["tenant"] == canonical_tenant("HQ") and поля["code"] == "CLN05"
    assert поля["photo"] and поля["photo"][:2] == b"\xff\xd8"
    assert "Запись добавлена, оценка пересчитана." in ответ.get_data(as_text=True)


@админ
def test_из_панели_возвращается_карточка_а_не_страница(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    _двери_кадров(monkeypatch)
    ответ = стенд.post("/inspections/x/findings", data=ФОРМА, headers={**ORIGIN, PANEL_HEADER: "1"})
    тело = ответ.get_data(as_text=True)
    assert 'class="sdetail spanel' in тело and "<html" not in тело


@админ
def test_кадр_не_изображение_и_слишком_большой_отказ_до_двери(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch)
    зовы = _двери_кадров(monkeypatch)
    пустой = стенд.post(
        "/inspections/x/findings/f1/photos",
        data={"photo": _файл(b"", "empty.jpg")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    assert "Кадр не изменён" in пустой.get_data(as_text=True)
    assert зовы == []


@админ
def test_приложить_и_заменить_и_снять_кадр(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _приёмка(monkeypatch)
    зовы = _двери_кадров(monkeypatch)

    # Act
    приложен = стенд.post(
        "/inspections/x/findings/f1/photos",
        data={"photo": _файл()},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    заменён = стенд.post(
        "/inspections/x/findings/f1/photos",
        data={"photo": _файл(), "replace": КАДР},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    снят = стенд.post(f"/inspections/x/photos/{КАДР}/delete", headers=ORIGIN)

    # Assert
    assert [имя for имя, _ in зовы] == ["attach_photo", "replace_photo", "detach_photo"]
    assert "Кадр приложен." in приложен.get_data(as_text=True)
    assert "Кадр заменён." in заменён.get_data(as_text=True)
    assert "Кадр убран." in снят.get_data(as_text=True)
    assert зовы[1][1]["args"] == ("x", "f1", КАДР)


@админ
def test_отказ_двери_показан_текстом(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _приёмка(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> None:
        raise ReviseError("Проверка уже принята")

    monkeypatch.setattr(revision, "add_card", отказать)
    monkeypatch.setattr(revision, "detach_photo", отказать)
    запись = стенд.post("/inspections/x/findings", data=ФОРМА, headers=ORIGIN)
    снят = стенд.post(f"/inspections/x/photos/{КАДР}/delete", headers=ORIGIN)
    assert "Запись не добавлена: Проверка уже принята" in запись.get_data(as_text=True)
    assert "Кадр не изменён: Проверка уже принята" in снят.get_data(as_text=True)


@админ
def test_чужое_пространство_и_чужой_origin_закрыты(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _приёмка(monkeypatch, пространство="GE")
    зовы = _двери_кадров(monkeypatch)
    чужое = стенд.post("/inspections/x/findings", data=ФОРМА, headers=ORIGIN)
    снят = стенд.post(f"/inspections/x/photos/{КАДР}/delete", headers=ORIGIN)
    assert чужое.status_code == 403 and снят.status_code == 403
    _приёмка(monkeypatch)
    без_origin = стенд.post(
        "/inspections/x/findings", data=ФОРМА, headers={"Origin": "http://evil.example"}
    )
    assert без_origin.status_code in (400, 403)
    assert зовы == []


@pytest.mark.parametrize("стенд", ["guest"], indirect=True)
def test_гость_не_добавляет_и_не_снимает(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _приёмка(monkeypatch)
    зовы = _двери_кадров(monkeypatch)
    assert стенд.post("/inspections/x/findings", data=ФОРМА, headers=ORIGIN).status_code == 403
    assert стенд.post(f"/inspections/x/photos/{КАДР}/delete", headers=ORIGIN).status_code == 403
    assert зовы == []


# --- админ партнёра (D367) ----------------------------------------------------


def _партнёр(monkeypatch: pytest.MonkeyPatch, **случай: Any) -> list[str]:
    параметры: dict[str, Any] = {"tenant": ПАРТНЁР, "role": "admin", "ждёт": True, **случай}
    зовы = _двери(monkeypatch, **параметры)
    for имя in ("add_card", "detach_photo"):
        monkeypatch.setattr(revision, имя, lambda *_a, _и=имя, **_k: зовы.append(_и))
    return зовы


def _пост(адрес: str) -> Any:
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        return client.post(адрес, data=ФОРМА, headers=ORIGIN)


@pytest.mark.parametrize(
    ("адрес", "дверь"),
    [
        (f"/inspections/{ID}/findings", "add_card"),
        (f"/inspections/{ID}/photos/{КАДР}/delete", "detach_photo"),
    ],
)
def test_админ_партнёра_правит_свежую_проверку_своих(
    monkeypatch: pytest.MonkeyPatch, адрес: str, дверь: str
) -> None:
    зовы = _партнёр(monkeypatch)
    assert _пост(адрес).status_code == 200
    assert зовы == [дверь]


@pytest.mark.parametrize(
    "адрес", [f"/inspections/{ID}/findings", f"/inspections/{ID}/photos/{КАДР}/delete"]
)
@pytest.mark.parametrize(
    "случай",
    [{"ждёт": False}, {"владелец": "HQ"}, {"origin": "import"}, {"role": "auditor"}],
)
def test_партнёр_не_правит_чужое_и_принятое(
    monkeypatch: pytest.MonkeyPatch, адрес: str, случай: dict[str, Any]
) -> None:
    зовы = _партнёр(monkeypatch, **случай)
    assert _пост(адрес).status_code in (403, 404)
    assert зовы == []
