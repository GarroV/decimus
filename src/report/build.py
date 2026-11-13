"""Сборка отчёта и письма партнёру.

Контракт блока — `docs/furca/blocks/report.md`. Наружу торчат две функции, и обе
проверяют наблюдаемый результат, а не отсутствие исключения: `build_pdf`
убеждается, что файл есть и это PDF, `build_letter` — что письмо не пустое.
Ни одна операция не возвращает код успеха, не сделав работу (конституция).

Разметка отчёта, выбор шаблона письма и расчёт оценки живут в движке. Здесь их
нет и быть не может: вторая копия правил разойдётся с первой, и увидит это
только партнёр.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.domain.config import Settings
from src.domain.engine import chat_dir, state_file
from src.domain.state import read_state
from src.domain.timing import parse_timestamp, zone_for_country

from .engine import run_report, settings
from .errors import PdfNotBuilt, PhotoMissing, ReportError
from .photos import FetchPhoto, misses_text, resolve_photos

#: Поле записи в переводе (`translations.field`) → ключ записи в файле состояния движка.
_STATE_KEYS = {"text": "evidence", "comment": "comment"}

#: Меньше этого не бывает даже у пустого отчёта — значит, собралась заглушка.
PDF_MIN_BYTES = 1000


def _pdf_problem(path: Path) -> str | None:
    """Почему собранное не является отчётом. `None` — отчёт на месте."""
    if not path.is_file():
        return f"файла нет: {path}"
    size = path.stat().st_size
    if size < PDF_MIN_BYTES:
        return f"файл слишком мал ({size} байт)"
    with path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            return "собран файл, но это не PDF"
    return None


@contextmanager
def _translated_state(
    chat_id: int, env: Settings, texts: Mapping[int, Mapping[str, str]] | None
) -> Iterator[dict[str, str] | None]:
    """Копия состояния проверки с переведённым текстом записей — только для этой сборки (D744).

    Исходник в состоянии не меняется: слив запишет его на языке речи, а перевод уйдёт в
    `translations` рядом. Движку копия подаётся переменной `INSPECTION_FILE`; лежит она в
    папке чата, потому что отчёт движок кладёт рядом с файлом состояния. Переводов нет —
    `None`, сборка идёт по настоящему состоянию.
    """
    if not texts:
        yield None
        return
    path = state_file(chat_id, env)
    state = json.loads(path.read_text(encoding="utf-8"))
    for finding in state.get("findings", []):
        for name, text in texts.get(int(finding.get("n", 0)), {}).items():
            finding[_STATE_KEYS[name]] = text
    copy = path.with_name(f".{path.stem}-translated-{uuid.uuid4().hex}.json")
    copy.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    try:
        yield {"INSPECTION_FILE": str(copy)}
    finally:
        copy.unlink(missing_ok=True)


def build_pdf(
    chat_id: int,
    *,
    fetch_photo: FetchPhoto | None = None,
    allow_missing_photos: bool = False,
    finished_at: datetime | None = None,
    country: str | None = None,
    texts: Mapping[int, Mapping[str, str]] | None = None,
) -> Path:
    """Собрать отчёт по проверке этого чата и вернуть путь к файлу.

    Имя файла даёт движок — `Аудит <пиццерия> - <аудитор> - <дд.мм.гггг>.pdf`;
    здесь оно не повторяется, иначе две копии правила разъедутся при первой же
    правке. Отчёт кладётся в папку проверки, рядом с состоянием.

    Провал сборки — `PdfNotBuilt`, а не путь к тому, чего нет.

    `fetch_photo` — как получить файл кадра по идентификатору телеграма; без
    него ссылка читается как путь. Потерянный кадр по умолчанию отменяет
    сборку (`PhotoMissing` с номерами записей): отчёт без доказательства
    партнёр справедливо оспорит. `allow_missing_photos` оставляет решение
    аудитору — он уже уехал с точки и переснять не может; тогда на месте кадра
    печатается видимая отметка, а не пустота.

    Время проверки в шапке (D730): начало берётся из состояния, конец — зафиксированный
    там же (повторная сборка), иначе `finished_at` вызывающего: бот фиксирует конец
    ПОСЛЕ отдачи отчёта, и без этого аргумента отчёт вышел бы без конца. `country` —
    страна пиццерии, по ней выбирается часовой пояс; неизвестна — движок печатает UTC.

    `texts` — перевод свободного текста записей на язык отчёта (номер записи → поле → текст,
    D744): печатается он, а исходник в проверке остаётся нетронутым.
    """
    env = settings(chat_id)
    plan = resolve_photos(chat_id, env, fetch_photo)
    if plan.misses and not allow_missing_photos:
        raise PhotoMissing(misses_text(plan.misses), misses=plan.misses)
    # Карта уходит движку всегда, даже пустая: ссылка резолвится в одном месте,
    # и идентификатор телеграма ни при каких условиях не уедет в него путём.
    with tempfile.TemporaryDirectory(prefix="report-photos-") as tmp:
        photo_map = Path(tmp) / "photo-map.json"
        photo_map.write_text(json.dumps(plan.mapping, ensure_ascii=False), encoding="utf-8")
        try:
            with _translated_state(chat_id, env, texts) as extra:
                printed = run_report(
                    [
                        "pdf",
                        "--photo-map",
                        str(photo_map),
                        *_speech_args(chat_id, env),
                        *_time_args(chat_id, env, finished_at, country),
                    ],
                    chat_id=chat_id,
                    settings=env,
                    env_extra=extra,
                ).strip()
        except PdfNotBuilt:
            raise
        except ReportError as exc:
            raise PdfNotBuilt(f"Отчёт не собран: {exc}") from exc
    if not printed:
        raise PdfNotBuilt("Сборщик отчёта отчитался об успехе, но не назвал файл")
    out = Path(printed)
    if not out.is_absolute():
        out = chat_dir(chat_id, env) / out
    bad = _pdf_problem(out)
    if bad:
        raise PdfNotBuilt(f"Сборщик отчёта отчитался об успехе, но отчёта нет: {bad}")
    return out


def _time_args(
    chat_id: int, env: Settings, finished_at: datetime | None, country: str | None
) -> list[str]:
    """Время проверки для шапки отчёта (D730). Начала нет — аргументов нет, строки в шапке нет."""
    started = read_state(chat_id, env)
    if started is None or started.started_at is None:
        return []
    end = started.finished_at or parse_timestamp(finished_at)
    args = [f"--started-at={started.started_at.isoformat()}"]
    if end is not None:
        args.append(f"--finished-at={end.isoformat()}")
    zone = zone_for_country(country)
    if zone:
        args.append(f"--tz={zone}")
    return args


def _speech_args(chat_id: int, env: Settings) -> list[str]:
    """Язык речи аудитора для движка: на нём записана обратная связь (D663).

    Язык отчёта не годится — до конца обхода он равен языку чек-листа, а потом его
    выбирают отдельно. Состояния нет — аргумента нет, движок возьмёт язык шапки.
    """
    started = read_state(chat_id, env)
    return [] if started is None else [f"--speech-lang={started.speech_lang}"]


@dataclass(frozen=True)
class BuiltLetter:
    """Письмо и то, чего в него не вставили."""

    text: str
    #: Роли обратной связи (`strengths`, `growth`), записанной не на языке письма
    #: и потому не вставленной (D663). Непусто — отправителя надо предупредить.
    feedback_skipped: tuple[str, ...]
    #: Язык, на котором обратная связь записана.
    feedback_lang: str


def build_letter_notes(
    chat_id: int, template: int = 1, *, texts: Mapping[int, Mapping[str, str]] | None = None
) -> BuiltLetter:
    """Собрать письмо партнёру и вернуть вместе с перечнем не вставленного.

    Шаблон выбирает движок по наличию D2 и D3: чистая проверка не требует плана
    действий по нарушениям, которых нет. `template` — порядок обратной связи
    аудитора (D664): 1 — сильные стороны до нарушений, зоны роста после; 2 — обе
    части в конце. Бот собирает шаблон 1. `texts` — перевод текста записей, как у `build_pdf`.
    """
    env = settings(chat_id)
    with _translated_state(chat_id, env, texts) as extra:
        raw = run_report(
            ["letter", f"--template={template}", "--json", *_speech_args(chat_id, env)],
            chat_id=chat_id,
            settings=env,
            env_extra=extra,
        )
    try:
        answer = json.loads(raw)
        text = str(answer["text"]).strip()
        skipped = tuple(str(role) for role in answer["feedback_skipped"])
        recorded = str(answer["feedback_lang"])
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ReportError(
            "Сборщик письма ответил не разбираемым JSON — отправлять нечего"
        ) from None
    if not text:
        raise ReportError("Сборщик письма вернул пустой текст — отправлять партнёру нечего")
    return BuiltLetter(text, skipped, recorded)


def build_letter(chat_id: int, template: int = 1) -> str:
    """Текст письма партнёру. Предупреждение о не вставленном — `build_letter_notes`."""
    return build_letter_notes(chat_id, template).text
