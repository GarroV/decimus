"""Информационные поля проверки — блок `info` состояния (T158, решения D069, D070).

Это не находки и не замеры: сильные стороны, зоны роста, отзыв о тестовом
заказе, даты созвона и плана действий. На оценку они не влияют вовсе — движок
считает процент по `findings`, а эти поля печатаются в отчёте партнёру
отдельным блоком и один из них (срок плана действий) читает письмо.

Команда движка `audit.py info --qid --text` существовала с самого начала, и
блок ею не пользовался: до T158 информационную часть никто не спрашивал.
Отдельным модулем, а не строкой в `findings.py`, потому что это другая
сущность: у находки есть номер, класс и зона, у информационного поля — код
пункта, текст и кадры (T179), и правило «одна пара пункт + зона на проверку» к
нему не относится. Повторная запись того же кода просто заменяет прежний текст,
и это именно то, что нужно после правки расшифровки голоса; приложенные кадры
она при этом не трогает.
"""

from __future__ import annotations

from collections.abc import Sequence

from .checklist import get_item
from .engine import option, run_audit
from .errors import EngineError, ValidationError
from .handover import guard_writable
from .info_fields import FIELDS, KIND_TEXT
from .state import read_state, settings_for


def set_info(chat_id: int, code: str, text: str, *, photos: Sequence[str] = ()) -> None:
    """Записать информационное поле проверки: `code` — пункт чек-листа, `text` — ответ.

    `photos` — кадры, которые печатаются в отчёте рядом с текстом этого поля
    (T179, вторая половина требования D069). До T172 движок хранил поле строкой,
    и передавать кадр было некуда; теперь поле это пара «текст + кадры».

    Кадр хранится ССЫЛКОЙ — в боте это идентификатор телеграма, — и проверяется
    она тем же правилом, что и кадр записи (`findings.attach_photo`): движок
    режет список по запятой, и один кадр молча стал бы двумя несуществующими.

    Пустой список кадров прежние НЕ снимает: повторной записью того же поля
    правят расшифровку голоса (D069), и кадр к этой правке отношения не имеет —
    так же читает свой `--photo` и движок.

    Пустой текст допустим только для реального текстового поля с кадрами:
    фотография — ответ, а подпись за аудитора не сочиняется. Пустота без кадров
    остаётся отказом. Даты и да/нет требуют собственного ответа: фотография
    не должна превращаться в пустую дату плана или выдуманное согласие.

    Код приводится к верхнему регистру самим движком; здесь он только
    проверяется на непустоту, потому что пустой `--qid` движок принял бы за
    ключ без значения и отказал бы невнятно.
    """
    guard_writable(chat_id)
    clean_code = code.strip()
    if not clean_code:
        raise ValidationError("Код информационного пункта пустой: записывать нечего")
    shots = [str(ref).strip() for ref in photos]
    for ref in shots:
        if not ref:
            raise ValidationError(
                f"Пустая ссылка на кадр информационного поля {clean_code}: приложить нечего, "
                f"а поле выглядело бы записанным с кадром"
            )
        if "," in ref:
            raise ValidationError(
                f"В ссылке на кадр поля {clean_code} запятая: «{ref}». Движок разрежет её "
                f"по запятой на два кадра, и оба окажутся несуществующими"
            )
    if not text.strip():
        field = next((field for field in FIELDS if field.code == clean_code.upper()), None)
        if not shots or field is None or field.kind != KIND_TEXT:
            raise ValidationError(
                f"Пустой ответ поля {clean_code} допустим только для текстового поля с фотографиями"
            )
        if get_item(clean_code, chat_id=chat_id).kind != "info":
            raise ValidationError("Фотоответ должен относиться к информационному пункту методики")
    settings = settings_for(chat_id)
    run_audit(
        ["info", option("qid", clean_code), option("text", text)]
        + [option("photo", ref) for ref in shots],
        chat_id=chat_id,
        settings=settings,
    )
    if not shots:
        return
    # Успех движка проверяется наблюдаемым результатом, а не кодом возврата
    # (конституция, тот же приём у `attach_photo`): именно молчаливая потеря
    # кадра и была дефектом, ради которого задача заведена.
    state = read_state(chat_id, settings)
    saved = None if state is None else state.info.get(clean_code)
    missing = [ref for ref in shots if saved is None or ref not in saved.photos]
    if missing:
        raise EngineError(
            f"Движок отчитался об успехе, но кадров нет в поле {clean_code}: {', '.join(missing)}",
            code=0,
            command="info",
        )
