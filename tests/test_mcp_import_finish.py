"""Приёмка загруженной «текущей» проверки сразу отдаёт отчёт и письмо (D334).

Как бот на сдаче: после `import_accept_inspection` у человека готовы ссылка на
PDF и текст письма. Приёмка не откатывается из-за сборки: сбой PDF — это
`pdf_error` в ответе. База подменена; письмо собирает настоящий движок на
оснастке методики, PDF-рендерер подменён (его гоняет отдельный смоук).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp_checklist_harness import build_edition, build_methodology, harness_edition

from src.db.models import (
    ORIGIN_IMPORT,
    ORIGIN_LEGACY,
    FindingRow,
    InspectionDetail,
    InspectionRow,
)
from src.mcp import imports
from src.report import detail_pdf, letters
from src.report.errors import ReportError

ВЕРСИЯ = harness_edition()
ID = "11111111-1111-1111-1111-111111111111"


def _детали(origin: str) -> InspectionDetail:
    строка = InspectionRow(
        id=ID,
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=0,
        kind="planned",
        inspection_date=date(2026, 8, 19),
        report_lang="ru",
        checklist_version=ВЕРСИЯ,
        pct=99.5,
        grade="A",
        findings_count=1,
        pushed_at="2026-08-19T18:00:00+02:00",
        origin=origin,
    )
    находка = FindingRow(
        id="22222222-2222-2222-2222-222222222222",
        inspection_id=ID,
        unit_name="Белград-1",
        inspection_date=date(2026, 8, 19),
        n=1,
        code="CLN01",
        level="D1",
        zone="fridge",
        zone_unusual=False,
        source="comment",
        lang="ru",
        text="Пол в холодильнике в разводах",
        comment="",
    )
    return InspectionDetail(
        inspection=replace(строка, on_review=True),
        deductions=0.5,
        counts={"D1": 1},
        by_zone={},
        findings=(находка,),
    )


class _Пусто:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def мир(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    build_edition(tmp_path / "store" / "versions" / ВЕРСИЯ)
    build_methodology(tmp_path / "live")
    monkeypatch.setenv("AUDIT_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("ADMIN_PUBLIC_URL", "https://audit.example.org")
    letters.clear_letter_cache()
    мир = SimpleNamespace(origin=ORIGIN_IMPORT, загружено=[], принято=[])

    def читать(ident: str, *, tenant: str) -> tuple[InspectionDetail, Any]:
        return _детали(мир.origin), SimpleNamespace(origin=мир.origin)

    def принять(ident: str, *, tenant: str, actor: str) -> None:
        мир.принято.append(ident)

    def выгрузить(ident: str, *, data: bytes, **_: object) -> None:
        мир.загружено.append((ident, data))

    monkeypatch.setattr(imports, "_read", читать)
    monkeypatch.setattr(imports, "_comparison", lambda *_: {})
    monkeypatch.setattr(imports, "_db", lambda **_: _Пусто())
    monkeypatch.setattr("src.db.accept.accept_inspection", принять)
    monkeypatch.setattr("src.db.reports.upload_report", выгрузить)
    monkeypatch.setattr(detail_pdf, "build_bytes", lambda *_, **__: b"%PDF-1.7 test")
    return мир


def _принять() -> dict[str, object]:
    return imports.import_accept_inspection(
        tenant="укашка",
        store=None,  # type: ignore[arg-type]
        actor="mcp:HQ",
        inspection_id=ID,
        confirm_unit="Белград-1",
        confirm_date="2026-08-19",
    )


def test_current_после_приёмки_ссылка_на_отчёт_и_письмо(мир: SimpleNamespace) -> None:
    ответ = _принять()

    assert мир.принято == [ID]
    assert мир.загружено == [(ID, b"%PDF-1.7 test")]
    assert ответ["report_url"] == f"https://audit.example.org/inspections/{ID}/report"
    assert ответ["pdf_error"] is None
    assert isinstance(ответ["letter"], str) and "Белград-1" in ответ["letter"]


def test_сбой_pdf_приёмку_не_откатывает(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def упасть(*_: object, **__: object) -> bytes:
        raise ReportError("рендерер недоступен")

    monkeypatch.setattr(detail_pdf, "build_bytes", упасть)

    ответ = _принять()

    assert мир.принято == [ID]
    assert ответ["report_url"] is None
    assert ответ["pdf_error"] == "рендерер недоступен"
    assert ответ["letter"]


def test_историческая_без_pdf_и_письма(мир: SimpleNamespace) -> None:
    мир.origin = ORIGIN_LEGACY

    ответ = _принять()

    assert мир.принято == [ID]
    assert мир.загружено == []
    assert "report_url" not in ответ and "letter" not in ответ


def test_письмо_загруженной_current_собирается_а_исторической_отказ(
    мир: SimpleNamespace,
) -> None:
    papers = letters.sources()
    assert "Белград-1" in str(
        letters.build(_детали(ORIGIN_IMPORT), lang=None, papers=papers)["letter"]
    )

    with pytest.raises(letters.LetterError, match="историческая"):
        letters.build(_детали(ORIGIN_LEGACY), lang=None, papers=papers)


def test_pdf_при_приёмке_собирается_с_кадрами_записей(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    получено: dict[str, Any] = {}

    def собрать(*_: object, **kw: Any) -> bytes:
        получено.update(kw)
        return b"%PDF-1.7 test"

    monkeypatch.setattr(imports, "_report_photos", lambda *_, **__: ({1: [b"jpeg"]}, 0))
    monkeypatch.setattr(detail_pdf, "build_bytes", собрать)

    ответ = _принять()

    assert получено["photos"] == {1: [b"jpeg"]}
    assert ответ["pdf_warning"] is None


def test_не_скачавшийся_кадр_не_отказ_а_предупреждение(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imports, "_report_photos", lambda *_, **__: ({}, 2))

    ответ = _принять()

    assert ответ["pdf_error"] is None
    assert "without them" in str(ответ["pdf_warning"])
    assert мир.загружено  # PDF собран и выгружен


def test_state_json_несёт_ссылки_кадров_только_когда_переданы() -> None:
    import json

    без = json.loads(letters.state_json(_детали(ORIGIN_IMPORT), lang="ru"))
    с = json.loads(letters.state_json(_детали(ORIGIN_IMPORT), lang="ru", photos={1: ["p.jpg"]}))

    assert без["findings"][0]["photos"] == []
    assert с["findings"][0]["photos"] == ["p.jpg"]


def _ссылка(monkeypatch: pytest.MonkeyPatch) -> Any:
    from src.mcp import import_photo_link

    monkeypatch.setattr(
        import_photo_link, "_only_import", lambda *a, **k: (_детали(ORIGIN_IMPORT), None)
    )
    return import_photo_link.import_photo_upload_link(
        tenant="укашка",
        store=None,  # type: ignore[arg-type]
        actor="mcp:HQ",
        inspection_id=ID,
    )


def test_ссылка_загрузки_подписана_и_привязана_к_черновику(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.domain import photo_upload_link

    monkeypatch.setenv("WEB_SECRET_KEY", "s" * 40)

    ответ = _ссылка(monkeypatch)

    токен = str(ответ["url"]).rsplit("/", 1)[1]
    право = photo_upload_link.verify("s" * 40, токен)
    assert право == photo_upload_link.UploadGrant(inspection_id=ID, tenant="укашка")
    assert str(ответ["url"]).startswith("https://audit.example.org/photo-upload/")
    assert "-F file=@/mnt/user-data/uploads/" in str(ответ["command"])


def test_ссылка_загрузки_без_ключа_подписи_отказ(
    мир: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.mcp.errors import ToolError

    monkeypatch.delenv("WEB_SECRET_KEY", raising=False)

    with pytest.raises(ToolError):
        _ссылка(monkeypatch)
