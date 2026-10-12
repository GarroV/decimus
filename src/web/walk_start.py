"""Начало проверки из мини-аппа (D392): те же шаги, что у мастера бота, — полями на одном экране.

`POST /tg/walk/start` — одно действие за запрос (`op`):

- `options` — что показать в мастере: открытые чек-листы пространства человека,
  виды проверки, языки (предвыбран прошлый выбор человека, D451) и состояние
  текущей проверки (нет / идёт / сдана);
- `suggest` — подсказки к полю названия по мере набора;
- `start` — начать проверку.

Правила не переписаны, а взяты у бота: пределы и каноничность названия
(`domain.unit_name.check_unit_name`), сверка со справочником и «Новая пиццерия?»
(`bot.unit_pick`), открытые чек-листы (`bot.start_options`), имя проверяющего
(`bot.auditor`) и тексты отказов бота. Мини-апп — второй вход в тот же мастер,
а не вторая реализация. Отличие одно: два языка выбираются раздельно — речь
аудитора и язык отчёта (D393), у бота отчёт и речь пока идут за одним выбором.

Что здесь решено:

* **Идущую проверку без явного «заменить» не трогаем.** Незавершённую проверку
  новая стирает (T052), поэтому запрос без `replace: true` получает отказ 409, а
  экран спрашивает человека. Сданную заменять можно без вопроса: её копия в
  чате — то, что бот убирает кнопкой «Убрать из чата», а отчёт и история точки
  остаются.
* **Всё под замком заметок** (`domain.holding_notes`) — тем же, под которым бот
  ставит признак сдачи и мини-апп пишет запись: решение «идёт или сдана»,
  снятие сданной копии, старт и сброс заметок не перемежаются с чужим действием.
* **Сообщений в чат нет.** Бот на старте пишет в чат «Проверка начата»; мини-апп
  этого не делает — человек и так видит обход (правило владельца: исходящее
  человеку — только с явного «да»).
* **Память бота** (`PendingStore`, `MaterialStore`) отсюда не очистить: она в
  другом процессе. Её сбрасывает сам бот по смене личности проверки
  (`Inspection.run_id`, `bot/run_guard.py`).
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, Response, jsonify, request

from src.bot import journal
from src.bot.auditor import auditor_name
from src.bot.config import BotSettings
from src.bot.keyboards import KIND_TITLES, LANG_LABELS, kind_title
from src.bot.start_options import open_checklists
from src.bot.texts import t
from src.bot.unit_pick import (
    UNIT_KNOWN,
    UNIT_PARTNER_REFUSED,
    match_unit,
    resolve_unit,
    suggest_index,
    suggest_units,
    where_suffix,
)
from src.db import checklist_langs
from src.db.directory import upsert_unit
from src.db.errors import DbError
from src.domain import (
    drop_inspection,
    get_state,
    handed_over,
    holding_notes,
    reset_notes,
    start_inspection,
)
from src.domain.errors import DomainError
from src.domain.tenants import HQ_TENANT
from src.domain.unit_name import UNIT_NAME_LIMIT, UnitName, check_unit_name

from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_access import space_of
from .walk_auth import (
    INIT_DATA_HEADER,
    START_ENDPOINT,
    START_PATH,
    WalkAccessError,
    WalkSettings,
    full_name_of,
)
from .walk_settings import chosen_lang
from .walk_write import Identify, Respond

logger = logging.getLogger(__name__)

#: Что сейчас с проверкой человека — экран по этому решает, спрашивать ли «заменить».
STATE_NONE = "none"
STATE_RUNNING = "running"
STATE_SEALED = "sealed"

#: Имя пиццерии длиннее предела не разбирается: подсказки к нему бессмысленны.
MAX_TYPED = UNIT_NAME_LIMIT * 2


class Refused(Exception):
    """Отказ словами экрана. `field` — к какому полю он относится, `need` — что спросить."""

    def __init__(self, message: str, status: int = 422, *, field: str = "", need: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field
        self.need = need
        self.extra: dict[str, Any] = {}


def _said(key: str, lang: str, ui_lang: str) -> str:
    entry = WALK_TEXTS[key]
    return entry.get(lang) or entry[ui_lang]


def _state_of(chat_id: int) -> str:
    """Нет проверки, идёт или сдана. Нечитаемое состояние — «идёт»: стирать его молча нельзя."""
    try:
        if get_state(chat_id) is None:
            return STATE_NONE
        return STATE_SEALED if handed_over(chat_id) else STATE_RUNNING
    except DomainError:
        logger.exception("Старт из мини-аппа: состояние чата %s не читается", chat_id)
        return STATE_RUNNING


def _remembered_lang(who: int) -> str | None:
    """Язык чек-листа с прошлого старта человека (D451). Нет выбора или база молчит — `None`."""
    try:
        lang = checklist_langs.chosen_checklist_lang(who)
    except DbError:
        logger.warning("Старт из мини-аппа: язык чек-листа %s не прочитался", who, exc_info=True)
        return None
    return lang if lang in LANG_LABELS else None


def _remember_lang(who: int, lang: str) -> None:
    """Запомнить выбор после удачного старта. Не записалось — проверка уже идёт, это не отказ."""
    try:
        checklist_langs.choose_checklist_lang(who, lang)
    except DbError:
        logger.warning("Старт из мини-аппа: язык чек-листа %s не записался", who, exc_info=True)


def _text(body: dict[str, Any], name: str) -> str:
    value = body.get(name, "")
    if not isinstance(value, str):
        raise Refused("", 400)
    return value.strip()


def _choice(body: dict[str, Any], name: str, allowed: Any) -> str:
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise Refused("", 400)
    return value


class _Wizard:
    """Один запрос мастера: кто, на каком языке, в каком пространстве."""

    def __init__(
        self,
        who: int,
        lang: str,
        ui_lang: str,
        space: str,
        conf: WalkSettings,
        bot: BotSettings | None,
    ) -> None:
        self.who = who
        self.lang = lang
        self.ui_lang = ui_lang
        self.space = space
        self.conf = conf
        self.bot = bot

    def say(self, key: str) -> str:
        return _said(key, self.lang, self.ui_lang)

    def checklists(self) -> list[Any]:
        """Открытые чек-листы. Не прочитались или нет ни одного — отказ словами бота."""
        открыты = open_checklists(self.space)
        if открыты is None:
            raise Refused(self.say("walk.start.err.failed"), 503)
        if not открыты:
            raise Refused(t("start.no_checklists", self.lang), 409)
        return открыты

    def options(self) -> dict[str, Any]:
        открыты = self.checklists()
        return {
            "state": _state_of(self.who),
            "checklists": [{"code": c.code, "name": c.name(self.lang)} for c in открыты],
            "kinds": [{"code": code, "title": kind_title(code, self.lang)} for code in KIND_TITLES],
            "langs": [{"code": code, "label": label} for code, label in LANG_LABELS.items()],
            "default_lang": self.default_lang(),
            "suggest": suggest_index(tenant=self.space),
        }

    def default_lang(self) -> str:
        """Язык чек-листа для предвыбора: прошлый выбор человека (D451), иначе язык интерфейса."""
        remembered = _remembered_lang(self.who)
        if remembered is not None:
            return remembered
        return self.lang if self.lang in LANG_LABELS else next(iter(LANG_LABELS))

    def suggest(self, body: dict[str, Any]) -> dict[str, Any]:
        typed = _text(body, "name")[:MAX_TYPED]
        return {"suggestions": suggest_units(typed, tenant=self.space)}

    def unit(self, body: dict[str, Any]) -> str:
        """Название пиццерии для старта — как у бота: проверка, справочник, «Новая пиццерия?»."""
        typed = _text(body, "unit")
        проверка = check_unit_name(typed)
        if проверка.name is None:
            raise Refused(
                t(f"start.{проверка.problem}", self.lang, limit=UNIT_NAME_LIMIT, typed=typed),
                field="unit",
            )
        имя = проверка.name
        сверка = match_unit(имя.name, tenant=self.space)
        решение = resolve_unit(имя, сверка, self.space)
        if решение.status == UNIT_KNOWN:
            return решение.name
        if решение.status == UNIT_PARTNER_REFUSED:
            raise Refused(t("start.unit_new_partner", self.lang, name=имя.name), field="unit")
        if body.get("add_unit") is not True:
            ask = Refused(
                t(
                    "start.unit_new_ask",
                    self.lang,
                    name=имя.name,
                    where=where_suffix(имя, self.lang),
                ),
                409,
                field="unit",
                need="unit_new",
            )
            ask.extra = {"name": имя.name}
            raise ask
        self._register(имя, typed)
        return имя.name

    def _register(self, имя: UnitName, typed: str) -> None:
        """Завести пиццерию в справочник страны — как «Да, новая» у бота."""
        синонимы = (typed,) if typed and typed != имя.name else ()
        try:
            upsert_unit(
                имя.name,
                aliases=синонимы,
                country=имя.country,
                city=имя.city,
                tenant=self.space,
            )
        except DbError as exc:
            # Точка заведётся по имени при сливе проверки; страну и город допишет
            # администратор. Держать аудитора незачем (так же у бота).
            logger.warning("новая пиццерия %s не записана в справочник: %s", имя.name, exc)

    def checklist(self, body: dict[str, Any]) -> str | None:
        """Код чек-листа: открыт один — берём его сами, как бот; несколько — выбранный."""
        открыты = self.checklists()
        if len(открыты) == 1:
            return str(открыты[0].code)
        code = body.get("checklist")
        if not isinstance(code, str) or code not in {c.code for c in открыты}:
            # Методист закрыл чек-лист, пока человек смотрел на экран.
            raise Refused(self.say("walk.start.err.checklist_gone"), field="checklist")
        return code

    def start(self, body: dict[str, Any], full_name: str) -> None:
        kind = _choice(body, "kind", KIND_TITLES)
        speech_lang = _choice(body, "speech_lang", LANG_LABELS)
        # Язык отчёта на старте не спрашивается (D415): до готовности проверки он
        # равен языку чек-листа, а задаёт его бот/мини-апп в конце. `report_lang`
        # от старого клиента принимается и игнорируется.
        replace = body.get("replace") is True
        checklist = self.checklist(body)
        if _state_of(self.who) == STATE_RUNNING and not replace:
            raise Refused(self.say("walk.start.err.running"), 409, need="replace")
        unit = self.unit(body)
        names = self.bot.auditor_names if self.bot is not None else {}
        auditor = auditor_name(self.who, full_name, names)
        try:
            with holding_notes(self.who):
                # Решающая проверка — под замком: ранняя выше могла пройти за
                # миг до того, как проверка началась в чате.
                state = _state_of(self.who)
                if state == STATE_RUNNING and not replace:
                    raise Refused(self.say("walk.start.err.running"), 409, need="replace")
                if state == STATE_SEALED:
                    # Только сданная копия, как «Убрать из чата» у бота (T201).
                    drop_inspection(self.who)
                start_inspection(
                    self.who,
                    unit=unit,
                    kind=kind,
                    report_lang=speech_lang,
                    ui_lang=self.lang,
                    speech_lang=speech_lang,
                    auditor=auditor,
                    tenant=self.space,
                    checklist_code=checklist,
                )
                reset_notes(self.who)
        except DomainError as exc:
            logger.exception("Старт из мини-аппа: проверка чата %s не началась", self.who)
            raise Refused(self.say("walk.start.err.failed"), 500) from exc
        # Журнал разбора — спутник проверки (#367): прежний закрывается, новый с чистого листа.
        journal.close(self.who)
        _remember_lang(self.who, speech_lang)
        logger.info("Старт из мини-аппа: чат %s начал проверку, чек-лист %s", self.who, checklist)


def install(
    app: Flask,
    *,
    conf: WalkSettings,
    ui_lang: str,
    identify: Identify,
    respond: Respond,
    bot: BotSettings | None,
) -> None:
    """Повесить `POST /tg/walk/start`. Опознание и доступ — те же, что у записи."""

    @app.post(START_PATH, endpoint=START_ENDPOINT)
    def walk_start() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _refused(_said("walk.err.bad_request", ui_lang, ui_lang), 400)
        lang = (chosen_lang(who) if bot is not None else None) or ui_lang
        if lang not in UI_LANGS:
            lang = ui_lang
        try:
            space = HQ_TENANT if conf.bot_token is None else space_of(who, conf)
            if space is None:
                return jsonify({"error": "unauthorized"}), 401
            wizard = _Wizard(who, lang, ui_lang, space, conf, bot)
            op = body.get("op")
            if op == "options":
                return jsonify(wizard.options()), 200
            if op == "suggest":
                return jsonify(wizard.suggest(body)), 200
            if op == "start":
                name = full_name_of(request.headers.get(INIT_DATA_HEADER, ""), conf)
                wizard.start(body, name)
                return respond(who, ui_lang)
            return _refused(_said("walk.err.bad_request", lang, ui_lang), 400)
        except Refused as exc:
            message = exc.message or _said("walk.err.bad_request", lang, ui_lang)
            return _refused(message, exc.status, field=exc.field, need=exc.need, extra=exc.extra)
        except WalkAccessError:
            return jsonify({"error": "unauthorized"}), 401
        except DbError:
            logger.exception("Старт из мини-аппа: чат %s — база не ответила", who)
            return _refused(_said("walk.app.err.unavailable", lang, ui_lang), 503)


def _refused(
    message: str,
    status: int = 422,
    *,
    field: str = "",
    need: str = "",
    extra: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    answer: dict[str, Any] = {"error": "refused", "message": message}
    if field:
        answer["field"] = field
    if need:
        answer["need"] = need
    answer.update(extra or {})
    return jsonify(answer), status
