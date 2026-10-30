"""PDF-отчёт из актуального снимка проверки в базе, по её версии методики.

У проверки из бота отчёт собирается из состояния чата (`build.build_pdf`). У
загруженной через MCP чата нет, есть только строки базы, поэтому состояние для
движка собирается из них во временном каталоге — тем же `state_json`, что и
письмо, и по тому же снимку методики, которым помечена проверка. Оценка перед
печатью сверяется с записанной: отчёт с другой буквой под прежней датой хуже
отсутствующего.

Кадры записей передаёт вызывающий (`photos`: номер записи → байты копий из
хранилища): здесь они ложатся файлами во временный каталог, а движок печатает кадр
только по карте «ссылка → файл» (`--photo-map`). Без `photos` отчёт честно без фото.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..db.models import InspectionDetail
from .engine_call import clean as _clean
from .letters import (
    REPORT_SCRIPT,
    LetterError,
    Papers,
    _lang,
    _methodology,
    _run,
    _verify,
    state_json,
)

REPORT_FILE = "report.pdf"


def build_bytes(
    detail: InspectionDetail,
    *,
    lang: str | None,
    papers: Papers,
    photos: Mapping[int, Sequence[bytes]] | None = None,
    info_photos: Mapping[str, Sequence[bytes]] | None = None,
) -> bytes:
    """Собрать PDF по записанной проверке и вернуть его байты — или `LetterError`."""
    язык = _lang(detail, lang)
    каталог, _ = _methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="mcp-report-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        ссылки: dict[int, list[str]] = {}
        инфо_ссылки: dict[str, list[str]] = {}
        карта: dict[str, str] = {}
        for n, кадры in (photos or {}).items():
            for i, байты in enumerate(кадры, 1):
                файл_кадра = Path(рядом) / f"photo-{n}-{i}.jpg"
                файл_кадра.write_bytes(байты)
                ссылки.setdefault(n, []).append(файл_кадра.name)
                карта[файл_кадра.name] = str(файл_кадра)
        for field_index, (code, frames) in enumerate((info_photos or {}).items(), 1):
            for frame_index, data in enumerate(frames, 1):
                photo_file = Path(рядом) / f"info-{field_index}-{frame_index}.jpg"
                photo_file.write_bytes(data)
                инфо_ссылки.setdefault(code, []).append(photo_file.name)
                карта[photo_file.name] = str(photo_file)
        состояние.write_text(
            state_json(detail, lang=язык, photos=ссылки, info_photos=инфо_ссылки), encoding="utf-8"
        )
        аргументы = ["pdf", f"--lang={язык}", "--out", str(Path(рядом) / REPORT_FILE)]
        if карта:
            файл_карты = Path(рядом) / "photo-map.json"
            файл_карты.write_text(json.dumps(карта, ensure_ascii=False), encoding="utf-8")
            аргументы += ["--photo-map", str(файл_карты)]
        _verify(detail, каталог, состояние)
        файл = Path(рядом) / REPORT_FILE
        код, вывод, ошибки = _run(
            REPORT_SCRIPT,
            аргументы,
            data_dir=каталог,
            state=состояние,
        )
        if код != 0 or not файл.is_file():
            raise LetterError(
                f"Движок не собрал отчёт: {_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
        данные = файл.read_bytes()
    if not данные.startswith(b"%PDF-"):
        raise LetterError("Движок отчитался об успехе, но файл не является PDF")
    return данные
