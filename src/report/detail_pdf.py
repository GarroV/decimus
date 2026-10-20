"""PDF-отчёт по записанной в базе проверке — для загруженной «текущей» (D334).

У проверки из бота отчёт собирается из состояния чата (`build.build_pdf`). У
загруженной через MCP чата нет, есть только строки базы, поэтому состояние для
движка собирается из них во временном каталоге — тем же `state_json`, что и
письмо, и по тому же снимку методики, которым помечена проверка. Оценка перед
печатью сверяется с записанной: отчёт с другой буквой под прежней датой хуже
отсутствующего.

Кадров в отчёте нет: у записей загрузки они лежат в хранилище за ссылками, а
движок печатает кадр только по карте «ссылка → файл» (`--photo-map`). Это
названная цена, а не умолчание: отчёт честно без фотографий.
"""

from __future__ import annotations

import tempfile
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


def build_bytes(detail: InspectionDetail, *, lang: str | None, papers: Papers) -> bytes:
    """Собрать PDF по записанной проверке и вернуть его байты — или `LetterError`."""
    язык = _lang(detail, lang)
    каталог, _ = _methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="mcp-report-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        состояние.write_text(state_json(detail, lang=язык), encoding="utf-8")
        _verify(detail, каталог, состояние)
        файл = Path(рядом) / REPORT_FILE
        код, вывод, ошибки = _run(
            REPORT_SCRIPT,
            ["pdf", f"--lang={язык}", "--out", str(файл)],
            data_dir=каталог,
            state=состояние,
        )
        if код != 0 or not файл.is_file():
            raise LetterError(
                f"Движок не собрал отчёт: {_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
        данные = файл.read_bytes()
    if not данные:
        raise LetterError("Движок отчитался об успехе, но отчёт пуст")
    return данные
