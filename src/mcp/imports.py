"""Инструменты загрузки проверок задним числом поштучно (D305–D310, D332–D335).

Коллега УК с Claude разбирает отчёт — Битрикс, PDF Qvalon, таблица — и вносит его
через этот MCP: черновик → записи (и кадры, где есть, D309) → подтверждение.
Подтверждает тот же коллега (D308); после этого загруженная — проверка в истории
точки и аналитике рядом с обходами (D306), а запрос экшн-плана не открывается и
никому ничего не уходит (D310).

**Два режима, задаются при создании и не меняются (D334, `import_modes.py`).**
`history` — старый отчёт по прежней методике: оценка переносится как в отчёте и
движком НЕ пересчитывается нигде (D332), записи описательные. `current` —
недавняя проверка по действующей версии эталона: записи сверяет и оценку
считает движок, ровно как у обхода (`src/report/rescore.apply_command`), здесь
не переписано ни одного его правила.

**Модель предлагает, фиксирует человек.** Каждый инструмент — одно действие
коллеги; инструмента «загрузить отчёт целиком» нет и не будет.

**Только загруженные черновики своего пространства.** Проверку обхода эти
инструменты не правят, не удаляют и не подтверждают — условие стоит в замке
строки (`src/db/imports.py`), а не только здесь. Право на сами инструменты —
по пространству (`MCP_IMPORT_TENANTS`, только `HQ` — D335), спрашивается на входе
(`rpc._call_tool`).

Запросов к базе в этом модуле нет: черновик живёт в `src/db/imports.py`,
подтверждение — в `src/db/accept.py`, чтение — в `src/db/queries.py`.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import TYPE_CHECKING, Any

from ..db.models import ORIGIN_IMPORT, ORIGIN_LEGACY
from ..domain.kinds import INSPECTION_KINDS
from ..domain.models import TEXT_LANGS
from . import import_modes as modes
from .checklist_layout import Store
from .errors import ToolError
from .retraction import _same_unit
from .tools import _finding, _parse_date, _require_inspection_id

if TYPE_CHECKING:
    from ..db.models import InspectionDetail
    from ..db.storage import PhotoStorage
    from ..report.rescore import Applied

logger = logging.getLogger(__name__)

NOT_CONNECTED = (
    "Загрузка проверок на этом стенде не подключена к базе: не задана переменная "
    "окружения DATABASE_URL. Это отказ настройки, а не отказ в загрузке"
)

ACCEPT_NOT_CONNECTED = (
    "Подтверждение на этом стенде не настроено: не задана переменная окружения "
    "DATABASE_RETRACTION_URL. Подтверждает проверку только администратор истории "
    "(роль dodo_audit_admin), отдельным подключением. Черновик остался как был"
)

#: Предел кадра в байтах ПОСЛЕ разбора base64. Тело запроса MCP ограничено
#: мегабайтом (`server.MAX_BODY_BYTES`), а base64 раздувает байты на треть:
#: 700 КБ кадра — это ~933 КБ строки плюс обёртка JSON-RPC. Больше — сервер
#: отказал бы ещё до разбора, и отказ назвал бы тело, а не кадр.
MAX_PHOTO_BYTES = 700_000

#: Предел СТРОКИ base64 — проверяется до всякой обработки строки (разбора,
#: чистки переносов): ровно столько знаков даёт кадр в MAX_PHOTO_BYTES, плюс
#: запас на переносы строк каждые 76 знаков (MIME) и выравнивание.
_B64_LINE = 76
MAX_PHOTO_B64_CHARS = (MAX_PHOTO_BYTES + 2) // 3 * 4
MAX_PHOTO_B64_RAW = MAX_PHOTO_B64_CHARS + 2 * (MAX_PHOTO_B64_CHARS // _B64_LINE + 1)

#: Форматы кадров. Сжатую копию снимает `db.previews.make_preview`; формат,
#: которого она не прочтёт, отклоняется ещё до хранилища.
PHOTO_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})

#: Пределы полей шапки и записи. Формулировка печатается в отчёте строкой —
#: тот же порог, что у правки на приёмке (`web/revision.MAX_TEXT`). Слой базы
#: держит те же пределы сам (`db/imports.MAX_WORDING` и соседи): здесь они
#: повторены, чтобы отказ звучал до похода в базу, а модуль не тянул psycopg.
MAX_TEXT = 1000
MAX_AUDITOR = 200
MAX_UNIT = 200
MAX_SOURCE_REF = 1000
MAX_GRADE = 8

#: Язык формулировок — код из двух латинских букв: язык речи (D025) не обязан
#: совпадать с языками методики, старый отчёт мог быть написан на любом.
_LANG = re.compile(r"^[a-z]{2}$")


@contextmanager
def _db(*, accept: bool = False) -> Iterator[None]:
    """Отказы блока `db` — словами для агента, без текста драйвера."""
    from ..db.errors import AcceptError, HistoryImportError
    from ..db.errors import ConfigError as DbConfigError

    try:
        yield
    except DbConfigError:
        raise ToolError(ACCEPT_NOT_CONNECTED if accept else NOT_CONNECTED) from None
    except (HistoryImportError, AcceptError) as отказ:
        raise ToolError(str(отказ)) from None


def _papers() -> Any:
    from ..report.letters import sources

    return sources()


def _engine(args: Sequence[str]) -> Callable[[InspectionDetail], Applied]:
    """Команда движка над проверкой, прочитанной после замка, по её версии методики."""
    from ..report.letters import LetterError
    from ..report.rescore import apply_command

    бумаги = _papers()

    def применить(detail: InspectionDetail) -> Applied:
        try:
            return apply_command(detail, papers=бумаги, args=args)
        except LetterError as отказ:
            # Текст движка — тот же, что видит аудитор в боте; пути вычищены.
            raise ToolError(f"Движок не принял запись, ничего не изменено: {отказ}") from None

    return применить


def _rescorer() -> Callable[[InspectionDetail], Any]:
    from ..report.letters import LetterError
    from ..report.rescore import rescore

    бумаги = _papers()

    def посчитать(detail: InspectionDetail) -> Any:
        try:
            return rescore(detail, papers=бумаги)
        except LetterError as отказ:
            raise ToolError(f"Движок не посчитал проверку, черновик не заведён: {отказ}") from None

    return посчитать


def _text(value: str | None, *, field: str, limit: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ToolError(f"Не назван {field}")
        return None
    # Длина — по сырой строке, до чистки: предел обязан срабатывать раньше
    # любой работы над строкой, а пробелы по краям нужны только опечатке.
    if len(value) > limit:
        raise ToolError(f"Аргумент {field} длиннее {limit} знаков")
    чистое = value.strip()
    if required and not чистое:
        raise ToolError(f"Аргумент {field} пуст")
    return чистое


def _required(value: str, *, field: str, limit: int) -> str:
    чистое = _text(value, field=field, limit=limit, required=True)
    if not чистое:
        raise ToolError(f"Аргумент {field} пуст")
    return чистое


def _check_n(n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ToolError("Номер записи n — целое число от 1")
    return n


# --- черновик -----------------------------------------------------------------


def _reported(pct: float | int | None, grade: str | None) -> tuple[float | None, str | None]:
    if pct is not None:
        if isinstance(pct, bool) or not 0 <= float(pct) <= 100:
            raise ToolError("reported_pct — процент из старого отчёта, от 0 до 100")
        pct = round(float(pct), 2)
    буква = _text(grade, field="reported_grade", limit=MAX_GRADE)
    return pct, (буква.upper() if буква else None)


def import_create_inspection(
    *,
    tenant: str,
    store: Store,
    actor: str,
    mode: str,
    unit: str,
    date: str,
    auditor: str | None = None,
    checklist_code: str | None = None,
    checklist_version: str | None = None,
    kind: str = "planned",
    report_lang: str = "ru",
    text_lang: str | None = None,
    reported_pct: float | None = None,
    reported_grade: str | None = None,
    reported_status: str | None = None,
    legacy_method: str | None = None,
    source_ref: str | None = None,
) -> dict[str, object]:
    """Завести черновик без записей в названном режиме (D334).

    `current` — по действующей версии эталона, оценку считает движок.
    `history` — оценка из старого отчёта как есть (D332), движок не зовётся.
    """
    from ..db import imports as db

    del actor  # черновик подписывается на подтверждении (D199), а не здесь
    режим = modes.parse_mode(mode)
    день = _parse_date(date, field="date")
    if день is None:
        raise ToolError("Не названа дата проверки в date (ГГГГ-ММ-ДД)")
    if день > _today():
        raise ToolError(
            f"Дата {день.isoformat()} в будущем. Загружаются прошедшие проверки — дата обхода "
            f"из старого отчёта"
        )
    точка = _required(unit, field="unit", limit=MAX_UNIT)
    if kind not in INSPECTION_KINDS:
        raise ToolError(f"Вид проверки kind — один из: {', '.join(INSPECTION_KINDS)}")
    if report_lang not in TEXT_LANGS:
        raise ToolError(f"Язык отчёта report_lang — один из: {', '.join(TEXT_LANGS)}")
    язык_слов = report_lang if text_lang is None else text_lang.strip().lower()
    if not _LANG.match(язык_слов):
        raise ToolError("text_lang — код языка из двух латинских букв (ru, en, sr …)")
    процент, буква = _reported(reported_pct, reported_grade)
    ссылка = _text(source_ref, field="source_ref", limit=MAX_SOURCE_REF) or None
    шапка: dict[str, Any] = {
        "tenant": tenant,
        "unit": точка,
        "inspection_date": день,
        "kind": kind,
        "report_lang": report_lang,
        "speech_lang": язык_слов,
        "reported_pct": процент,
        "reported_grade": буква,
        "source_ref": ссылка,
    }
    if режим == modes.MODE_CURRENT:
        modes.refuse_history_fields(reported_status, legacy_method)
        эталон = modes.current_only(
            store, tenant=tenant, code=checklist_code, version=checklist_version
        )
        черновик = db.NewDraft(
            **шапка,
            origin=ORIGIN_IMPORT,
            checklist_code=эталон.code,
            checklist_version=эталон.version,
            auditor=_required(auditor or "", field="auditor", limit=MAX_AUDITOR),
        )
        with _db():
            ident = db.create_draft(черновик, apply_score=_rescorer())
        return _view(ident, tenant=tenant, note="current-mode draft created with no findings")
    modes.refuse_history_choice(checklist_code, checklist_version)
    if процент is None:
        raise ToolError(
            "В режиме history оценка из старого отчёта обязательна: reported_pct — процент, "
            "как напечатан в отчёте (например, Score 95.29 → 95.29). Она и станет оценкой "
            "проверки, без пересчёта (D332)"
        )
    метка = _text(legacy_method, field="legacy_method", limit=modes.MAX_LEGACY_METHOD) or None
    черновик = db.NewDraft(
        **шапка,
        origin=ORIGIN_LEGACY,
        checklist_code=modes.reference(store, tenant=tenant).code,
        checklist_version=modes.legacy_version(метка),
        auditor=_text(auditor, field="auditor", limit=MAX_AUDITOR) or "",
        reported_status=_text(
            reported_status, field="reported_status", limit=modes.MAX_REPORTED_STATUS
        )
        or None,
        legacy_method=метка,
    )
    with _db():
        ident = db.create_draft(черновик, apply_score=None)
    return _view(ident, tenant=tenant, note="history-mode draft created with no findings")


def _today() -> date:
    return date.today()


# --- чтение -------------------------------------------------------------------


def _read(ident: str, *, tenant: str) -> tuple[InspectionDetail, Any]:
    """Загруженная проверка своего пространства и её поля сверки. Нет — отказ."""
    from ..db import imports as db
    from ..db.models import UPLOADED_ORIGINS
    from ..db.queries import get_inspection
    from ..db.reach import own_reach

    with _db():
        шапка = db.import_head(ident, tenant=tenant)
        detail = get_inspection(ident, reach=own_reach(tenant), include_on_review=True)
    if шапка is None or detail is None:
        raise ToolError(
            f"Проверки {ident} у этого доступа нет. Черновики загрузки перечисляет "
            f"import_list_drafts"
        )
    if шапка.origin not in UPLOADED_ORIGINS:
        raise ToolError(
            f"Проверка {ident} — проверка обхода из бота, а не загруженная. Её читают "
            f"get_inspection; инструменты загрузки её не трогают"
        )
    return detail, шапка


def _only_import(ident: str, *, tenant: str) -> tuple[InspectionDetail, Any]:
    """Заслон в обработчике до записи: только загруженная проверка своего пространства.

    Второй, а не единственный: тот же заслон стоит в замке строки
    (`src/db/imports._LOCK_SQL`, `origin in ('import', 'legacy')`). Здесь он
    нужен, чтобы отказ на проверку обхода пришёл до движка и хранилища кадров, а
    забытое условие в одном из двух мест не открывало правку обхода молча.
    Возвращает прочитанное: по происхождению обработчик выбирает путь.
    """
    return _read(ident, tenant=tenant)


def _comparison(detail: InspectionDetail, шапка: Any) -> dict[str, object]:
    """Сверка с оценкой старого отчёта. Ничего не пересчитывает: обе цифры записаны."""
    pct, grade = detail.inspection.pct, detail.inspection.grade
    ждали_pct, ждали_букву = шапка.reported_pct, шапка.reported_grade
    if ждали_pct is None and ждали_букву is None:
        return {
            "reported_pct": None,
            "reported_grade": None,
            "matches_reported": None,
            "pct_diff": None,
            "comparison": "the original report's score was not given — nothing to compare",
        }
    сошёлся_pct = ждали_pct is None or round(pct, 2) == round(ждали_pct, 2)
    сошлась_буква = ждали_букву is None or grade.upper() == ждали_букву.upper()
    разница = None if ждали_pct is None else round(pct - ждали_pct, 2)
    return {
        "reported_pct": ждали_pct,
        "reported_grade": ждали_букву,
        "matches_reported": сошёлся_pct and сошлась_буква,
        "pct_diff": разница,
        "comparison": (
            "computed score matches the original report"
            if сошёлся_pct and сошлась_буква
            else "computed score DIFFERS from the original report: look for a missing, "
            "extra or mis-levelled finding, a missed repeat mark, or a different "
            "checklist version before accepting"
        ),
    }


def _mode_of(origin: str) -> str:
    return modes.MODE_HISTORY if origin == ORIGIN_LEGACY else modes.MODE_CURRENT


def _view(ident: str, *, tenant: str, note: str, warnings: Sequence[str] = ()) -> dict[str, object]:
    detail, шапка = _read(ident, tenant=tenant)
    if шапка.origin == ORIGIN_LEGACY:
        return _legacy_view(detail, шапка, note=note, warnings=warnings)
    строка = detail.inspection
    return {
        "id": строка.id,
        "mode": modes.MODE_CURRENT,
        "status": "draft" if строка.on_review else "accepted",
        "note": note,
        "unit": строка.unit_name,
        "inspection_date": строка.inspection_date.isoformat(),
        "kind": строка.kind,
        "auditor": строка.auditor,
        "checklist_code": строка.checklist_code,
        "checklist_version": строка.checklist_version,
        "report_lang": строка.report_lang,
        "source_ref": шапка.source_ref,
        "pct": строка.pct,
        "grade": строка.grade,
        "deductions": detail.deductions,
        "counts": detail.counts,
        "by_zone": detail.by_zone,
        **_comparison(detail, шапка),
        "findings": [
            {**_finding(f), "repeat": f.repeat} for f in sorted(detail.findings, key=lambda f: f.n)
        ],
    }


def _legacy_view(
    detail: InspectionDetail, шапка: Any, *, note: str, warnings: Sequence[str]
) -> dict[str, object]:
    """Историческая для агента: оценка как в отчёте, без вычетов и зон (D332)."""
    строка = detail.inspection
    return {
        "id": строка.id,
        "mode": modes.MODE_HISTORY,
        "status": "draft" if строка.on_review else "accepted",
        "note": note,
        **({"warnings": list(warnings)} if warnings else {}),
        "unit": строка.unit_name,
        "inspection_date": строка.inspection_date.isoformat(),
        "kind": строка.kind,
        "auditor": строка.auditor,
        "checklist_code": строка.checklist_code,
        "legacy_method": шапка.legacy_method,
        "report_lang": строка.report_lang,
        "source_ref": шапка.source_ref,
        "pct": строка.pct,
        "grade": строка.grade or None,
        "reported_status": шапка.reported_status,
        "score": (
            "historical inspection: the score is the old report's, transferred as is "
            "under the methodology of that time; it is NOT recomputed and findings do "
            "not change it (D332)"
        ),
        "counts": detail.counts,
        "findings": [
            modes.legacy_finding_view(f) for f in sorted(detail.findings, key=lambda f: f.n)
        ],
    }


def import_get_inspection(
    *, tenant: str, store: Store, actor: str, inspection_id: str
) -> dict[str, object]:
    """Загруженная проверка: режим, шапка, записи и оценка (как в отчёте или движка)."""
    del store, actor
    return _view(_require_inspection_id(inspection_id), tenant=tenant, note="read")


def import_list_drafts(*, tenant: str, store: Store, actor: str) -> dict[str, object]:
    """Черновики загрузки этого пространства, ждущие подтверждения."""
    from ..db import imports as db

    del store, actor
    with _db():
        строки = db.list_drafts(tenant=tenant)
    return {
        "tenant": tenant,
        "count": len(строки),
        "drafts": [
            {
                "id": r.id,
                "mode": _mode_of(r.origin),
                "unit": r.unit_name,
                "inspection_date": r.inspection_date.isoformat(),
                "checklist_code": r.checklist_code,
                "checklist_version": r.checklist_version,
                "pct": r.pct,
                "grade": r.grade,
                "reported_pct": r.reported_pct,
                "reported_grade": r.reported_grade,
                "source_ref": r.source_ref,
                "findings_count": r.findings_count,
                "created_at": r.pushed_at,
            }
            for r in строки
        ],
    }


# --- записи -------------------------------------------------------------------


def _wording(text: str | None, comment: str | None) -> Any:
    from ..db.imports import Wording

    return Wording(
        text=_text(text, field="text", limit=MAX_TEXT),
        comment=_text(comment, field="comment", limit=MAX_TEXT),
    )


def import_add_finding(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    text: str,
    code: str | None = None,
    level: str | None = None,
    zone: str | None = None,
    comment: str | None = None,
    repeat: bool = False,
) -> dict[str, object]:
    """Добавить запись в черновик: текущая — через движок, историческая — как в отчёте."""
    from ..db import imports as db
    from ..db import imports_legacy as legacy

    del actor
    ident = _require_inspection_id(inspection_id)
    _, шапка = _only_import(ident, tenant=tenant)
    слова = _wording(text, comment)
    if not (слова.text or ""):
        raise ToolError("Формулировка записи text пуста — запись без слов в отчёт не идёт")
    if шапка.origin == ORIGIN_LEGACY:
        запись = legacy.LegacyFinding(
            code=modes.legacy_code(code),
            level=modes.legacy_level(level),
            zone=modes.legacy_zone(zone),
            repeat=bool(repeat),
        )
        with _db():
            n = legacy.add_legacy_finding(ident, tenant=tenant, finding=запись, wording=слова)
        return _view(
            ident,
            tenant=tenant,
            note=f"finding #{n} added",
            warnings=modes.soft_warnings(store, code=запись.code, zone=запись.zone),
        )
    code, level, zone = _engine_triple(code, level, zone)
    args = [
        "add",
        f"--qid={code.strip()}",
        f"--level={level.strip()}",
        f"--zone={zone.strip()}",
        # Зону называет человек по старому отчёту (D206): вне списка пункта
        # она принимается с пометкой «необычная», как в боте.
        "--zone-by-person",
        f"--evidence={слова.text}",
        *([f"--comment={слова.comment}"] if слова.comment else []),
        *(["--repeat"] if repeat else []),
    ]
    with _db():
        n, _ = db.add_finding(ident, tenant=tenant, wording=слова, apply=_engine(args))
    return _view(ident, tenant=tenant, note=f"finding #{n} added")


def _engine_triple(code: str | None, level: str | None, zone: str | None) -> tuple[str, str, str]:
    """Текущей записи код, класс и зона обязательны: их сверяет движок."""
    if not (code or "").strip() or not (level or "").strip() or not (zone or "").strip():
        raise ToolError(
            "Проверка в режиме current: у записи обязательны code, level и zone — их сверяет "
            "движок по действующей версии, как в боте. Пересказ без пункта и класса — только "
            "у исторической (режим history)"
        )
    return str(code), str(level), str(zone)


def import_edit_finding(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    n: int,
    code: str | None = None,
    level: str | None = None,
    zone: str | None = None,
    text: str | None = None,
    comment: str | None = None,
    repeat: bool | None = None,
) -> dict[str, object]:
    """Исправить запись по номеру: текущая — с пересчётом движком, историческая — без."""
    from ..db import imports as db

    del actor
    ident = _require_inspection_id(inspection_id)
    detail, шапка = _only_import(ident, tenant=tenant)
    номер = _check_n(n)
    слова = _wording(text, comment)
    if слова.text is not None and not слова.text:
        raise ToolError("Формулировка записи text пуста — запись без слов в отчёт не идёт")
    if шапка.origin == ORIGIN_LEGACY:
        return _edit_legacy(
            store,
            detail,
            номер,
            tenant=tenant,
            wording=слова,
            fields={"code": code, "level": level, "zone": zone, "repeat": repeat},
        )
    args = [
        "edit",
        f"--n={номер}",
        *([f"--qid={code.strip()}"] if code is not None else []),
        *([f"--level={level.strip()}"] if level is not None else []),
        *([f"--zone={zone.strip()}", "--zone-by-person"] if zone is not None else []),
        *([f"--evidence={слова.text}"] if слова.text is not None else []),
        *([f"--comment={слова.comment}"] if слова.comment is not None else []),
        *([] if repeat is None else ["--repeat" if repeat else "--no-repeat"]),
    ]
    if len(args) == 2:
        raise ToolError(
            "Нечего менять: назовите хотя бы одно из code, level, zone, text, comment, repeat"
        )
    with _db():
        db.edit_finding(ident, номер, tenant=tenant, wording=слова, apply=_engine(args))
    return _view(ident, tenant=tenant, note=f"finding #{номер} edited")


def _edit_legacy(
    store: Store,
    detail: InspectionDetail,
    n: int,
    *,
    tenant: str,
    wording: Any,
    fields: dict[str, Any],
) -> dict[str, object]:
    """Правка исторической записи: поверх прежней, без движка (D332)."""
    from ..db import imports_legacy as legacy

    if all(v is None for v in fields.values()) and wording.text is None and wording.comment is None:
        raise ToolError(
            "Нечего менять: назовите хотя бы одно из code, level, zone, text, comment, repeat"
        )
    прежняя = next((f for f in detail.findings if f.n == n), None)
    if прежняя is None:
        raise ToolError(f"Записи #{n} в этом черновике нет")
    итог = modes.merged(прежняя, **fields)
    with _db():
        legacy.edit_legacy_finding(
            detail.inspection.id,
            n,
            tenant=tenant,
            finding=legacy.LegacyFinding(**итог),
            wording=wording,
        )
    return _view(
        detail.inspection.id,
        tenant=tenant,
        note=f"finding #{n} edited",
        warnings=modes.soft_warnings(store, code=итог["code"], zone=итог["zone"]),
    )


def import_remove_finding(
    *, tenant: str, store: Store, actor: str, inspection_id: str, n: int
) -> dict[str, object]:
    """Снять запись вместе с её кадрами; у текущей — пересчитать оценку движком."""
    from ..db import imports as db
    from ..db import imports_legacy as legacy

    del store, actor
    ident = _require_inspection_id(inspection_id)
    _, шапка = _only_import(ident, tenant=tenant)
    номер = _check_n(n)
    with _db():
        if шапка.origin == ORIGIN_LEGACY:
            кадры = legacy.remove_legacy_finding(ident, номер, tenant=tenant)
        else:
            _, кадры = db.remove_finding(
                ident, номер, tenant=tenant, apply=_engine(["drop", str(номер)])
            )
    _forget(кадры)
    return _view(ident, tenant=tenant, note=f"finding #{номер} removed")


# --- кадры (D309) -------------------------------------------------------------


def _photo_storage() -> PhotoStorage:
    """Хранилище кадров — то же, куда кладёт кадры обход (`S3_*`, D054)."""
    from ..db.config import load_storage_settings
    from ..db.storage import S3PhotoStorage

    return S3PhotoStorage(load_storage_settings(), fail_fast=True)


def _forget(кадры: Sequence[str]) -> None:
    """Убрать из хранилища объекты снятых кадров. Сбой — в журнал, сирот найдёт сверка."""
    if not кадры:
        return
    from ..db.errors import ConfigError as DbConfigError
    from ..db.imports import forget_objects

    try:
        хранилище = _photo_storage()
    except DbConfigError:
        logger.warning(
            "хранилище кадров не настроено — %d объектов снятых кадров остались", len(кадры)
        )
        return
    не_убрано = forget_objects(хранилище, кадры)
    if не_убрано:
        logger.warning("объекты снятых кадров загрузки не убраны: %d", не_убрано)


def import_add_photo(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    n: int,
    image_base64: str,
    mime: str,
) -> dict[str, object]:
    """Приложить кадр к записи загруженного черновика (D309: по возможности, не обязательно)."""
    from ..db import imports as db
    from ..db.errors import ConfigError as DbConfigError

    del store, actor
    ident = _require_inspection_id(inspection_id)
    _only_import(ident, tenant=tenant)
    номер = _check_n(n)
    if mime.strip().lower() not in PHOTO_MIMES:
        raise ToolError(f"Формат кадра mime — один из: {', '.join(sorted(PHOTO_MIMES))}")
    # Предел — по длине строки ДО всякой работы над ней: ни чистка переносов,
    # ни разбор base64 не начинаются над строкой сверх предела.
    if len(image_base64) > MAX_PHOTO_B64_RAW:
        raise ToolError(_too_big())
    сырое = "".join(image_base64.split())
    if len(сырое) > MAX_PHOTO_B64_CHARS:
        raise ToolError(_too_big())
    try:
        байты = base64.b64decode(сырое, validate=True)
    except (binascii.Error, ValueError):
        raise ToolError("image_base64 не разбирается как base64 — кадр не приложен") from None
    if not байты:
        raise ToolError("image_base64 пуст — кадр не приложен")
    if len(байты) > MAX_PHOTO_BYTES:
        raise ToolError(_too_big())
    try:
        хранилище = _photo_storage()
    except DbConfigError:
        raise ToolError(
            "Хранилище кадров на этом стенде не настроено (S3_*). Кадр не приложен; "
            "запись без кадра допустима (D309)"
        ) from None
    with _db():
        db.add_photo(ident, номер, tenant=tenant, data=байты, storage=хранилище)
    return _view(ident, tenant=tenant, note=f"photo attached to finding #{номер}")


def _too_big() -> str:
    return (
        f"Кадр больше {MAX_PHOTO_BYTES // 1000} КБ после разбора base64 — не приложен. "
        f"Уменьшите его (например, до 1600 пикселей по длинной стороне, JPEG): тело "
        f"запроса MCP ограничено мегабайтом"
    )


# --- подтверждение и удаление -------------------------------------------------


def _confirm(detail: InspectionDetail, *, unit: str, day: str, что: str) -> None:
    """Названные точка и дата обязаны совпасть с записанными — как у снятия (T211)."""
    точка = (unit or "").strip()
    if not точка:
        raise ToolError(f"Не названа точка в confirm_unit — {что} вслепую не делается")
    дата = _parse_date(day, field="confirm_date")
    if дата is None:
        raise ToolError(f"Не названа дата обхода в confirm_date — {что} вслепую не делается")
    строка = detail.inspection
    if _same_unit(строка.unit_name, точка) and строка.inspection_date == дата:
        return
    raise ToolError(
        f"Подтверждение не сошлось, {что} не выполнено. Названы точка «{точка}» и дата "
        f"{дата.isoformat()}, а проверка {строка.id} — это «{строка.unit_name}» от "
        f"{строка.inspection_date.isoformat()}, {строка.pct:g}% {строка.grade}, записей — "
        f"{len(detail.findings)}"
    )


def import_accept_inspection(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    confirm_unit: str,
    confirm_date: str,
) -> dict[str, object]:
    """Подтвердить загруженный черновик (D308): он входит в историю точки рядом с обходами."""
    from ..db.accept import accept_inspection

    del store
    ident = _require_inspection_id(inspection_id)
    detail, шапка = _read(ident, tenant=tenant)
    if not detail.inspection.on_review:
        raise ToolError(f"Проверка {ident} уже подтверждена — второй раз подтверждать нечего")
    _confirm(detail, unit=confirm_unit, day=confirm_date, что="подтверждение")
    with _db(accept=True):
        accept_inspection(ident, tenant=tenant, actor=actor)
    история = шапка.origin == ORIGIN_LEGACY
    return {
        "id": ident,
        "mode": _mode_of(шапка.origin),
        "unit": detail.inspection.unit_name,
        "inspection_date": detail.inspection.inspection_date.isoformat(),
        "pct": detail.inspection.pct,
        "grade": detail.inspection.grade or None,
        "accepted_by": actor,
        **({} if история else _comparison(detail, шапка)),
        "status": (
            "accepted: the inspection is now in the unit's history next to the others "
            "(get_inspection, unit_history, network_summary). "
            + (
                "Its score stays exactly as in the old report — it is never recomputed. "
                if история
                else ""
            )
            + "No action-plan request was opened, there is no partner letter for it, and "
            "nothing was sent to anyone. It can no longer be edited or discarded"
        ),
    }


def import_discard_draft(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    confirm_unit: str,
    confirm_date: str,
) -> dict[str, object]:
    """Удалить загруженный черновик целиком — никогда проверку обхода и никогда принятую."""
    from ..db import imports as db

    del store, actor
    ident = _require_inspection_id(inspection_id)
    detail, _ = _read(ident, tenant=tenant)
    if not detail.inspection.on_review:
        raise ToolError(
            f"Проверка {ident} уже подтверждена — принятая не удаляется. Неверную принятую "
            f"отклоняют (retract_inspection) и загружают заново"
        )
    _confirm(detail, unit=confirm_unit, day=confirm_date, что="удаление")
    with _db():
        кадры = db.discard_draft(ident, tenant=tenant)
    _forget(кадры)
    return {
        "id": ident,
        "unit": detail.inspection.unit_name,
        "inspection_date": detail.inspection.inspection_date.isoformat(),
        "status": "draft discarded with all its findings and photos",
    }
