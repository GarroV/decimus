"""Снятие кадров у записи черновика загрузки и список кадров с размерами (D627, #1206).

База и хранилище подменены: проверяется граница — чей черновик, какой вид, принят ли,
чей кадр — и что снятие идёт тем же путём, что вычитка в вебе
(`db.review_edit.detach_photo`). Строки и объекты хранилища (оригинал и превью) держит
`tests/test_db_review_edit.py`, он гоняется на тестовой базе.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.db import review_edit
from src.db.errors import ConfigError as DbConfigError
from src.db.errors import ReviseError
from src.mcp import import_photos, imports
from src.mcp.errors import ToolError

ID = "11111111-1111-1111-1111-111111111111"
P1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
P2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
P_OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"


def _jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def мир(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    мир = SimpleNamespace(on_review=True, detached=[], fail_on=None, views=[])
    детали = lambda: SimpleNamespace(  # noqa: E731
        inspection=SimpleNamespace(on_review=мир.on_review),
        findings=[SimpleNamespace(n=1, id="f1"), SimpleNamespace(n=2, id="f2")],
    )
    monkeypatch.setattr(import_photos, "_only_import", lambda ident, *, tenant: (детали(), None))
    monkeypatch.setattr(
        import_photos,
        "_shots",
        lambda ident, *, tenant: {"f1": ((P1, P2), 0), "f2": ((P_OTHER,), 1)},
    )
    monkeypatch.setattr(import_photos, "_photo_storage", lambda: object())

    def detach(ident: str, photo: str, *, tenant: str, storage: object) -> None:
        if мир.fail_on == photo:
            raise ReviseError(
                "Кадр не снят — проверка перестала ждать приёмки", code="revise_stale"
            )
        мир.detached.append((ident, photo, tenant))

    monkeypatch.setattr(review_edit, "detach_photo", detach)
    monkeypatch.setattr(
        import_photos,
        "_short_view",
        lambda ident, *, tenant, note, n=None, **_: мир.views.append(note) or {"note": note},
    )
    return мир


def _remove(**kw: Any) -> dict[str, object]:
    args: dict[str, Any] = {"inspection_id": ID, "n": 1, "photo": P1}
    return import_photos.import_remove_photo(
        tenant="укашка", store=None, actor="a", **{**args, **kw}
    )  # type: ignore[arg-type]


def _clear(**kw: Any) -> dict[str, object]:
    args: dict[str, Any] = {"inspection_id": ID, "n": 1}
    return import_photos.import_clear_photos(
        tenant="укашка", store=None, actor="a", **{**args, **kw}
    )  # type: ignore[arg-type]


def test_снимает_один_кадр_своей_записи_путём_вычитки(мир: SimpleNamespace) -> None:
    ответ = _remove()

    assert мир.detached == [(ID, P1, "укашка")]
    assert "photo removed from finding #1" in str(ответ["note"])


def test_чужой_кадр_другой_записи_не_снимается(мир: SimpleNamespace) -> None:
    with pytest.raises(ToolError, match="нет такого кадра"):
        _remove(n=1, photo=P_OTHER)

    assert мир.detached == []


def test_принятая_проверка_отказ(мир: SimpleNamespace) -> None:
    мир.on_review = False

    with pytest.raises(ToolError, match="уже подтверждена"):
        _remove()
    with pytest.raises(ToolError, match="уже подтверждена"):
        _clear()

    assert мир.detached == []


def test_нет_такой_записи_отказ(мир: SimpleNamespace) -> None:
    with pytest.raises(ToolError, match="нет записи #7"):
        _remove(n=7)


def test_чужой_черновик_отказ_до_снятия(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Настоящий `_only_import`: чужого пространства или не загруженной проверки у доступа нет."""
    monkeypatch.undo()  # вернуть настоящие `_only_import`, `_shots`, `detach_photo`
    from src.db import imports as db_imports
    from src.db import queries

    monkeypatch.setattr(db_imports, "import_head", lambda ident, *, tenant: None)
    monkeypatch.setattr(queries, "get_inspection", lambda *a, **k: None)
    снято: list[str] = []
    monkeypatch.setattr(review_edit, "detach_photo", lambda *a, **k: снято.append("x"))

    with pytest.raises(ToolError, match="у этого доступа нет"):
        _remove()

    assert снято == []


def test_снимает_все_кадры_записи(мир: SimpleNamespace) -> None:
    ответ = _clear()

    assert [d[1] for d in мир.detached] == [P1, P2]
    assert "2 photos removed from finding #1" in str(ответ["note"])


def test_снятие_всех_называет_кадры_без_копии(мир: SimpleNamespace) -> None:
    ответ = import_photos.import_clear_photos(
        tenant="укашка",
        store=None,
        actor="a",
        inspection_id=ID,
        n=2,  # type: ignore[arg-type]
    )

    assert [d[1] for d in мир.detached] == [P_OTHER]
    assert "no stored copy" in str(ответ["warnings"])


def test_отказ_на_середине_называет_сколько_уже_снято(мир: SimpleNamespace) -> None:
    мир.fail_on = P2

    with pytest.raises(ToolError, match="уже снято кадров: 1"):
        _clear()

    assert [d[1] for d in мир.detached] == [P1]


def test_хранилище_не_настроено_кадры_не_сняты(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def нет() -> object:
        raise DbConfigError("нет S3_*")

    monkeypatch.setattr(import_photos, "_photo_storage", нет)

    with pytest.raises(ToolError, match="не настроено"):
        _remove()

    assert мир.detached == []


def test_кадры_в_чтении_с_размером_и_low_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db import previews

    monkeypatch.setattr(
        import_photos,
        "_shots",
        lambda ident, *, tenant: {"f1": ((P1, P2), 0), "f2": ((P_OTHER,), 0)},
    )
    monkeypatch.setattr(import_photos, "_photo_storage", lambda: object())
    размеры = {P1: _jpeg(420, 560), P2: _jpeg(1600, 1200), P_OTHER: b"not an image"}
    monkeypatch.setattr(previews, "preview_bytes", lambda i, p, *, reach, storage: размеры[p])

    кадры = import_photos.frames_by_finding(ID, tenant="укашка")

    assert кадры is not None
    assert [
        (f["photo"], f["frame"], f["width"], f["height"], f["low_resolution"]) for f in кадры["f1"]
    ] == [
        (P1, 1, 420, 560, True),
        (P2, 2, 1600, 1200, False),
    ]
    # копия не прочиталась — размер неизвестен, но кадр в списке и снимается
    assert кадры["f2"] == [
        {"photo": P_OTHER, "frame": 1, "width": None, "height": None, "low_resolution": None}
    ]


def test_размер_читается_от_имени_пространства_обращения(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Потоки пула не наследуют пространство сами: на проде база отказывала всем 51 кадру."""
    from src.db import previews, space

    monkeypatch.setattr(import_photos, "_shots", lambda ident, *, tenant: {"f1": ((P1, P2), 0)})
    monkeypatch.setattr(import_photos, "_photo_storage", lambda: object())

    def копия(i: str, p: str, *, reach: Any, storage: Any) -> bytes:
        if space.current_space() != "HQ":
            raise previews.DbError("decimus.space is not set")
        return _jpeg(420, 560)

    monkeypatch.setattr(previews, "preview_bytes", копия)

    with space.acting_space("HQ"):
        кадры = import_photos.frames_by_finding(ID, tenant="HQ")

    assert кадры is not None
    assert [f["width"] for f in кадры["f1"]] == [420, 420]


def test_полное_чтение_несёт_frames_а_короткие_ответы_нет(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from src.mcp import import_modes as modes

    запись = SimpleNamespace(id="f1", n=1, repeat=False)
    строка = SimpleNamespace(
        id=ID,
        on_review=True,
        unit_name="U",
        inspection_date=date(2026, 8, 19),
        kind="planned",
        auditor="a",
        checklist_code="c",
        checklist_version="v",
        report_lang="ru",
        pct=99.0,
        grade="A",
    )
    detail = SimpleNamespace(
        inspection=строка, findings=[запись], deductions=[], counts={}, by_zone={}
    )
    шапка = SimpleNamespace(origin="import", source_ref=None)
    вызовы: list[str] = []
    monkeypatch.setattr(imports, "_read", lambda ident, *, tenant: (detail, шапка))
    monkeypatch.setattr(imports, "_item_texts_of", lambda v: {})
    monkeypatch.setattr(imports, "_finding", lambda f, t, lang: {"n": f.n})
    monkeypatch.setattr(imports, "_comparison", lambda d, h: {})
    monkeypatch.setattr(imports, "_photo_counts", lambda ident, *, tenant: {"f1": 1})
    monkeypatch.setattr(
        import_photos,
        "frames_by_finding",
        lambda ident, *, tenant: вызовы.append(ident) or {"f1": [{"photo": P1, "frame": 1}]},
    )
    assert modes  # режим читается из `imports`, подмена выше его не трогает

    полный = imports.import_get_inspection(tenant="t", store=None, actor="a", inspection_id=ID)  # type: ignore[arg-type]
    короткий = imports._view(ID, tenant="t", note="x")

    assert полный["findings"][0]["frames"] == [{"photo": P1, "frame": 1}]  # type: ignore[index]
    assert "frames" not in короткий["findings"][0]  # type: ignore[index]
    assert вызовы == [ID], "размеры кадров читались и в коротком ответе"
