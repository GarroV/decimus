"""Настройки разбора. Имя модели — параметр, никогда не константа в коде.

Смена провайдера или модели должна быть правкой `.env`, а не рефакторингом
(решение D010). Поэтому всё, что относится к вызову, собрано здесь, а сам вызов
живёт в единственном модуле `client.py`.

Значения по умолчанию заданы для тех параметров, у которых есть осмысленный
дефолт (модель, таймаут, пороги). Ключ по умолчанию не подставляется: без него
разбор обязан честно сказать, что не работает, а не молча вернуть пустоту.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from src.db import model_key

from .errors import RecognizeConfigError

MODEL_VAR = "RECOGNIZE_MODEL"
TRANSCRIBE_MODEL_VAR = "RECOGNIZE_TRANSCRIBE_MODEL"
MERGE_MODEL_VAR = "RECOGNIZE_MERGE_MODEL"
REASONING_EFFORT_VAR = "RECOGNIZE_REASONING_EFFORT"
API_KEY_VAR = "OPENAI_API_KEY"
TIMEOUT_VAR = "RECOGNIZE_TIMEOUT"
MIN_CONFIDENCE_VAR = "RECOGNIZE_MIN_CONFIDENCE"
MAX_CANDIDATES_VAR = "RECOGNIZE_MAX_CANDIDATES"
FFMPEG_VAR = "FFMPEG_BIN"

#: Флагман линейки — решение D013. Дешёвая модель экономит 93 цента на проверке,
#: которая занимает у человека четыре часа; цена ошибки несопоставима. Выбор
#: подтверждён замером на боевых данных — таблица в `docs/furca/blocks/recognize.md`.
DEFAULT_MODEL = "gpt-5.6-sol"

#: Транскрипция голосовых — решение D008.
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

#: Сведение комментария записи, когда к ней лёг ещё один кадр (#443, D247):
#: прежний текст и новые слова аудитора — в одну фразу. Задача текстовая и
#: короткая, картинок в ней нет, поэтому владелец просил дешёвую модель, а не
#: флагман. Самая дешёвая текстовая модель провайдера по его каталогу на
#: 30.09.2026 (developers.openai.com/api/docs/models): $0.1 / $0.5 за 1M токенов.
DEFAULT_MERGE_MODEL = "gpt-6-luna"

#: Глубина рассуждения модели разбора (`reasoning.effort`, #1267, D646). Значения
#: `gpt-5.6-sol` — по документации провайдера (developers.openai.com/api/docs/models/
#: gpt-5.6-sol, 26.10.2026): none, low, medium, high, xhigh, max; умолчание провайдера —
#: medium, и именно на нём разбор работал до #1267 (параметр не передавался).
#: Умолчание — `low`: замер на стенде точности (три прогона на вариант, 31 кадр) точности
#: не потерял и сократил ответ; цифры и оговорки — `docs/05-calibration.md`. `none` на том
#: же наборе точность роняет (77% против 87–97%), поэтому умолчанием не стал.
#: `default` — не передавать параметр вовсе (глубину выберет провайдер).
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
REASONING_PROVIDER_DEFAULT = "default"
DEFAULT_REASONING_EFFORT = "low"

DEFAULT_TIMEOUT = 90.0

#: Ниже этого — предложение показывается, но помечается «нужен человек».
#: Разведка дала 0.55 там, где правильного кода в перечне не было, и 0.99 там,
#: где он был: уверенность различает эти случаи и потому используется как сигнал.
DEFAULT_MIN_CONFIDENCE = 0.6

#: Больше пяти кнопок аудитор на телефоне не разберёт — контракт блока.
DEFAULT_MAX_CANDIDATES = 5

#: Язык формулировок и текста пунктов по умолчанию. Параметр, а не константа
#: смысла: у проверки язык отчёта хранится отдельно от языка интерфейса и языка
#: речи (принцип проекта «язык — параметр»), это лишь запасное значение, когда
#: вызывающий код его не передал.
DEFAULT_LANG = "ru"

#: «Проверки нет» — законное значение `chat_id` там, где справочники и карта
#: слов читаются вне выезда: замеры по выгрузкам `examples/`, команды методики
#: MCP, справочники до начала проверки. Правильный ответ там — действующий
#: каталог, и сказать это надо вслух.
#:
#: Умолчанием это НЕ является и становиться не должно (T226): `chat_id` во всём
#: блоке обязателен, потому что молчаливый откат на действующую методику и есть
#: тот дефект, ради которого всё делается. Забытый параметр обязан не
#: собираться, а «проверки нет» — быть названо. Приём взят у `src/bot/zones.py`
#: (T225), где та же константа стоила блоку десяти упавших тестов замера, пока
#: разница между двумя случаями не была названа явно.
NO_CHAT: int | None = None


@dataclass(frozen=True)
class RecognizeSettings:
    """Разобранное окружение блока разбора."""

    model: str
    transcribe_model: str
    api_key: str
    timeout: float
    min_confidence: float
    max_candidates: int
    ffmpeg: str
    #: С умолчанием, а не обязательным полем: настройки собирают и тесты, и
    #: замеры, и сведению комментария (#443) они не нужны.
    merge_model: str = DEFAULT_MERGE_MODEL
    #: Пусто — параметр в запрос не передаётся (глубину выберет провайдер).
    reasoning_effort: str = DEFAULT_REASONING_EFFORT


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RecognizeConfigError(
            f"Переменная {name} должна быть числом, а в окружении «{raw}». "
            f"Молчаливый откат на {default} означал бы, что разбор работает не на тех "
            f"настройках, которые человек задал"
        ) from exc


def _reasoning_effort(env: Mapping[str, str]) -> str:
    raw = (env.get(REASONING_EFFORT_VAR) or "").strip().lower()
    if not raw:
        return DEFAULT_REASONING_EFFORT
    if raw == REASONING_PROVIDER_DEFAULT:
        return ""
    if raw not in REASONING_EFFORTS:
        raise RecognizeConfigError(
            f"Переменная {REASONING_EFFORT_VAR} должна быть одной из "
            f"{', '.join((*REASONING_EFFORTS, REASONING_PROVIDER_DEFAULT))} или пустой, а в "
            f"окружении «{raw}». Молчаливый откат на умолчание означал бы, что разбор "
            f"работает не на той глубине рассуждения, которую человек задал"
        )
    return raw


def resolve_api_key(env: Mapping[str, str] | None = None) -> str:
    """Ключ модели: из базы (вставлен на экране «Подключения», D491), иначе из окружения.

    Явный `env` (тесты, замеры) — только он, базы нет: подставленное окружение не должно
    уходить к настоящему ключу. Без `env` — база, затем `OPENAI_API_KEY`: площадка работает
    на прежнем ключе, пока на экране ничего не вставляли. Кэш на минуту — в `model_key`.
    """
    if env is not None:
        return (env.get(API_KEY_VAR) or "").strip()
    return (model_key.stored_key() or os.environ.get(API_KEY_VAR) or "").strip()


def load_recognize_settings(env: Mapping[str, str] | None = None) -> RecognizeSettings:
    """Собрать настройки. Отсутствующий ключ — не отказ здесь, а отказ при вызове."""
    src = os.environ if env is None else env
    return RecognizeSettings(
        model=(src.get(MODEL_VAR) or "").strip() or DEFAULT_MODEL,
        transcribe_model=(src.get(TRANSCRIBE_MODEL_VAR) or "").strip() or DEFAULT_TRANSCRIBE_MODEL,
        api_key=resolve_api_key(env),
        timeout=_number(src, TIMEOUT_VAR, DEFAULT_TIMEOUT),
        min_confidence=_number(src, MIN_CONFIDENCE_VAR, DEFAULT_MIN_CONFIDENCE),
        max_candidates=int(_number(src, MAX_CANDIDATES_VAR, DEFAULT_MAX_CANDIDATES)),
        ffmpeg=(src.get(FFMPEG_VAR) or "").strip() or "ffmpeg",
        merge_model=(src.get(MERGE_MODEL_VAR) or "").strip() or DEFAULT_MERGE_MODEL,
        reasoning_effort=_reasoning_effort(src),
    )
