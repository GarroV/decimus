"""Загрузка кадров к черновику по подписанной ссылке: токен, сигнатура, HEIC, принятый черновик.

База и хранилище подменены: проверяется граница — кто и что может приложить, а
не SQL (его держит `tests/test_db_imports.py`).
"""

from __future__ import annotations

import io
import time
from types import SimpleNamespace
from typing import Any

import pillow_heif
import pytest
from flask import Flask
from PIL import Image

from src.db.errors import HistoryImportError
from src.domain import photo_upload_link
from src.web import photo_upload

SECRET = "k" * 40
ID = "11111111-1111-1111-1111-111111111111"
OTHER_ID = "22222222-2222-2222-2222-222222222222"


def _image(fmt: str) -> bytes:
    pillow_heif.register_heif_opener()
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def мир(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    app = Flask(__name__)
    conf: Any = SimpleNamespace(secret_key=SECRET, secret_key_is_ephemeral=False)
    photo_upload.install(app, conf)
    мир = SimpleNamespace(client=app.test_client(), status="draft", added=[])

    def head(ident: str, *, tenant: str) -> Any:
        return SimpleNamespace(origin="import", status=мир.status, retracted=False)

    def add_photo(ident: str, n: int, *, tenant: str, data: bytes, storage: object) -> str:
        from src.db.previews import make_preview

        make_preview(data)  # не картинка — отказ, как в настоящем add_photo
        мир.added.append((ident, n, tenant))
        return "photo-id"

    monkeypatch.setattr(photo_upload.db_imports, "import_head", head)
    monkeypatch.setattr(photo_upload.db_imports, "add_photo", add_photo)
    monkeypatch.setattr(photo_upload, "_storage", lambda: object())
    photo_upload.RATE._seen.clear()
    return мир


def _post(мир: SimpleNamespace, token: str, files: list[tuple[str, bytes]], n: str = "1") -> Any:
    data: dict[str, Any] = {"n": n, "file": [(io.BytesIO(b), name) for name, b in files]}
    return мир.client.post(f"/photo-upload/{token}", data=data, content_type="multipart/form-data")


def _token(**kw: str) -> str:
    return photo_upload_link.issue(
        SECRET, inspection_id=kw.get("inspection_id", ID), tenant=kw.get("tenant", "укашка")
    )


def test_jpeg_и_heic_прикладываются_к_черновику_из_токена(мир: SimpleNamespace) -> None:
    ответ = _post(мир, _token(), [("a.jpg", _image("JPEG")), ("b.heic", _image("HEIF"))])

    assert ответ.status_code == 200
    assert [x["file"] for x in ответ.json["attached"]] == ["a.jpg", "b.heic"]
    assert ответ.json["refused"] == []
    # Черновик и пространство — только из токена, а не из запроса.
    assert мир.added == [(ID, 1, "укашка"), (ID, 1, "укашка")]


def test_не_картинка_отказ_даже_с_именем_jpg(мир: SimpleNamespace) -> None:
    ответ = _post(мир, _token(), [("evil.jpg", b"<html>not an image</html>")])

    assert ответ.status_code == 422
    assert "not an image" in ответ.json["refused"][0]["reason"]
    assert мир.added == []


def test_отказ_базы_по_файлу_попадает_в_ответ(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(*_: object, **__: object) -> str:
        raise HistoryImportError("У записи #1 уже 10 кадров")

    monkeypatch.setattr(photo_upload.db_imports, "add_photo", отказ)
    ответ = _post(мир, _token(), [("a.jpg", _image("JPEG"))])

    assert ответ.status_code == 422
    assert "10 кадров" in ответ.json["refused"][0]["reason"]


@pytest.mark.parametrize("token", ["garbage", "x.y.z"])
def test_неверный_токен_403_без_подробностей(мир: SimpleNamespace, token: str) -> None:
    ответ = _post(мир, token, [("a.jpg", _image("JPEG"))])

    assert ответ.status_code == 403
    assert ответ.data == b""
    assert мир.added == []


def test_токен_чужого_ключа_403(мир: SimpleNamespace) -> None:
    чужой = photo_upload_link.issue("z" * 40, inspection_id=ID, tenant="укашка")

    assert _post(мир, чужой, [("a.jpg", _image("JPEG"))]).status_code == 403


def test_месячный_токен_работает_до_приёмки(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Срока у ссылки нет (D573): держит только приёмка черновика."""
    токен = _token()
    сейчас = time.time()
    monkeypatch.setattr(time, "time", lambda: сейчас + 30 * 24 * 3600)

    assert _post(мир, токен, [("a.jpg", _image("JPEG"))]).status_code != 403
    assert мир.added


def test_принятый_черновик_410(мир: SimpleNamespace) -> None:
    мир.status = "accepted"

    ответ = _post(мир, _token(), [("a.jpg", _image("JPEG"))])

    assert ответ.status_code == 410
    assert мир.added == []


def test_токен_привязан_к_своему_черновику(мир: SimpleNamespace) -> None:
    _post(мир, _token(inspection_id=OTHER_ID, tenant="другое"), [("a.jpg", _image("JPEG"))])

    assert мир.added == [(OTHER_ID, 1, "другое")]


def test_сессионная_кука_ничего_не_даёт(мир: SimpleNamespace) -> None:
    мир.client.set_cookie("decimus_session", "anything")

    assert _post(мир, "forged", [("a.jpg", _image("JPEG"))]).status_code == 403


def test_без_номера_находки_400(мир: SimpleNamespace) -> None:
    assert _post(мир, _token(), [("a.jpg", _image("JPEG"))], n="abc").status_code == 400


def test_предел_частоты_по_токену(мир: SimpleNamespace) -> None:
    токен = _token()
    коды = [
        _post(мир, токен, [("a.jpg", b"x")]).status_code for _ in range(photo_upload.PER_MINUTE + 1)
    ]

    assert коды[-1] == 429
    assert 429 not in коды[:-1]


# --- replace=1 (D627, #1206): старые снимаются, только если легли все новые ---------


@pytest.fixture
def замена(мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    мир.detached = []
    мир.refuse_marker = None
    счётчик = iter(range(1, 100))

    def add_photo(ident: str, n: int, *, tenant: str, data: bytes, storage: object) -> str:
        if мир.refuse_marker is not None and len(мир.added) == мир.refuse_marker:
            raise HistoryImportError("У записи #1 уже 10 кадров")
        мир.added.append((ident, n, tenant))
        return f"new-{next(счётчик)}"

    def detach(ident: str, photo_id: str, *, tenant: str, storage: object) -> None:
        мир.detached.append((ident, photo_id, tenant))

    monkeypatch.setattr(photo_upload.db_imports, "add_photo", add_photo)
    monkeypatch.setattr(photo_upload.revision, "detach_photo", detach)
    monkeypatch.setattr(photo_upload, "_frames_of", lambda grant, n: ["old-1", "old-2"])
    return мир


def _post_replace(мир: SimpleNamespace, files: list[tuple[str, bytes]]) -> Any:
    data: dict[str, Any] = {
        "n": "1",
        "replace": "1",
        "file": [(io.BytesIO(b), name) for name, b in files],
    }
    return мир.client.post(
        f"/photo-upload/{_token()}", data=data, content_type="multipart/form-data"
    )


def test_замена_успех_снимает_прежние_кадры_записи(замена: SimpleNamespace) -> None:
    ответ = _post_replace(замена, [("a.jpg", _image("JPEG")), ("b.jpg", _image("PNG"))])

    assert ответ.status_code == 200
    assert ответ.json["replaced"] is True
    assert len(ответ.json["attached"]) == 2
    assert [d[1] for d in замена.detached] == ["old-1", "old-2"]


def test_замена_с_отказом_оставляет_старое_и_откатывает_новое(замена: SimpleNamespace) -> None:
    замена.refuse_marker = 1  # первый кадр ляжет, второй — отказ базы

    ответ = _post_replace(замена, [("a.jpg", _image("JPEG")), ("b.jpg", _image("PNG"))])

    assert ответ.status_code == 422
    assert ответ.json["replaced"] is False
    assert ответ.json["attached"] == []
    # снят только лёгший новый кадр; старые на месте
    assert [d[1] for d in замена.detached] == ["new-1"]
    assert {r["file"] for r in ответ.json["refused"]} == {"a.jpg", "b.jpg"}


def test_без_replace_старые_не_трогаются(замена: SimpleNamespace) -> None:
    ответ = _post(замена, _token(), [("a.jpg", _image("JPEG"))])

    assert ответ.status_code == 200
    assert "replaced" not in ответ.json
    assert замена.detached == []


def test_замена_без_годного_кадра_старое_не_снимает(замена: SimpleNamespace) -> None:
    ответ = _post_replace(замена, [("evil.jpg", b"<html>not an image</html>")])

    assert ответ.status_code == 422
    assert ответ.json["replaced"] is False
    assert замена.detached == []
