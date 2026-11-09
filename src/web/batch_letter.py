"""Общее письмо по нескольким проверкам страны: окно на экране страны (D739, #1579).

Вход один — кнопка «Сформировать общее письмо» на экране страны. Состояние живёт в адресе
экрана страны: `batch=1` — панель справа с выбором принятых проверок, `ids=<id>,<id>` — окно
письма по выбранным. Окно устроено как у одиночного письма (`inspections/_letter_form.html`):
правка текста, язык, шаблон, «Вернуть заготовку», «Сохранить изменения», «Сохранить черновик
на почте».

Правило выбора и сборка — `src/report/batch_letter.py`; здесь только переводчик: отказ правила
становится словами на языке экрана, а запись и черновик идут теми же дверями, что у
одиночного письма (`inspections.remember_letter`-подобная фиксация, Google-поход
`letter_draft`). Отправки из системы нет (Q010).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import Flask, abort, current_app, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import batch_letters as store
from src.db import queries
from src.db.errors import ConfigError, DbError
from src.db.models import InspectionDetail, InspectionRow
from src.report import batch_letter as core
from src.report import letter_markup
from src.report.batch_letter import BatchLetterError
from src.report.letters import LetterError
from src.report.letters import sources as letter_sources

from . import auth, guard, view
from . import inspections as data
from .config import Settings
from .google_mail import GoogleMailError, MailAccountMismatchError, create_draft, draft_subject
from .letter_draft import (
    MAIL_CONSENT_KEY,
    MAIL_RETURNS_KEY,
    OUTCOME_WRONG_ACCOUNT,
    MailReturn,
    _inspection_to,
    _копия_ук,
)
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Вид похода за согласием Google для общего письма (см. `letter_draft.MAIL_RETURNS_KEY`).
MAIL_KIND = "batch_letter"
#: Сколько проверок страны показывает выбор: свежие сверху, остальное — сужением по дате.
PICK_LIMIT = 200
_ID = re.compile(r"[0-9a-fA-F-]{36}")
_ADDRESS_SPLIT = re.compile(r"[;,]\s*")


@dataclass(frozen=True)
class Candidate:
    """Строка выбора: принятая проверка страны."""

    row: InspectionRow
    checked: bool


def parse_ids(raw: str) -> tuple[str, ...]:
    """Идентификаторы из адреса: ввод снаружи, мусор отбрасывается, порядок и повторы остаются."""
    return tuple(x for x in (p.strip() for p in raw.split(",")) if _ID.fullmatch(x))


def _tenant() -> str:
    return auth.current_tenant()


def url_for_country(code: str, *, lang: str, **params: str) -> str:
    query: dict[str, Any] = {k: v for k, v in {"lang": lang, **params}.items() if v}
    return url_for("country", code=code, **query)


def refusal_text(error: BatchLetterError, lang: str) -> str:
    """Отказ правила или сборки словами языка экрана; код без текста — русская причина."""
    facts = {k: str(v) for k, v in error.facts.items()}
    if error.code == "spread" and "first" in facts:
        facts["first"] = date.fromisoformat(facts["first"]).strftime("%d.%m.%Y")
        facts["last"] = date.fromisoformat(facts["last"]).strftime("%d.%m.%Y")
    if error.code == "unit_failed":
        facts["date"] = date.fromisoformat(facts["date"]).strftime("%d.%m.%Y")
    key = f"batch.refuse.{error.code}"
    return t(key, lang, **facts)


def candidates(code: str, picked: tuple[str, ...]) -> tuple[Candidate, ...]:
    """Принятые проверки страны своего пространства, свежие сверху, без загруженных."""
    rows = queries.list_inspections(reach=auth.current_reach(), country=code, limit=PICK_LIMIT)
    tenant = _tenant()
    return tuple(
        Candidate(r, r.id in picked)
        for r in rows
        if r.tenant_code == tenant and not r.is_uploaded and not r.on_review
    )


def load_details(ids: tuple[str, ...]) -> tuple[list[InspectionDetail], str | None]:
    """Карточки выбранных проверок по охвату вошедшего; не нашлась — название причины."""
    details: list[InspectionDetail] = []
    for ident in ids:
        detail = data.load_card(ident, reach=auth.current_reach())
        if detail is None:
            return details, "missing"
        details.append(detail)
    return details, None


def panel(code: str, lang: str) -> dict[str, Any]:
    """Данные панели «общее письмо» экрана страны: выбор проверок и, если выбраны, окно письма."""
    ids = parse_ids(",".join(request.args.getlist("ids")))
    template = request.args.get("letter_template", "")
    template_n = (
        int(template) if template.isdigit() and int(template) in data.LETTER_TEMPLATES else None
    )
    ctx: dict[str, Any] = {
        "ids": ids,
        "refusal": "",
        "letter": None,
        "failure": "",
        "own": guard.may("inspection.letter", _tenant()),
        "letter_langs": data.LETTER_LANGS,
        "letter_templates": data.LETTER_TEMPLATES,
        "letter_template": template_n or data.LETTER_TEMPLATES[0],
        "letter_template_explicit": template_n is not None,
        "save_outcome": request.args.get("saved", ""),
        "gmail_outcome": request.args.get("gmail", ""),
        "max_days": core.MAX_SPREAD_DAYS,
        "show_draft": request.args.get("draft") == "1" or template_n is not None,
        "saved": None,
        "saved_known": True,
        "markup": "",
        "caveat_rows": (),
    }
    try:
        ctx["candidates"] = candidates(code, ids)
    except DbError:
        logger.warning("Проверки страны для общего письма не прочитались", exc_info=True)
        ctx["candidates"] = ()
        ctx["failure"] = t("batch.failed.read", lang)
        return ctx
    if not ids:
        return ctx
    letter_lang = request.args.get("letter_lang") or None
    try:
        details, problem = load_details(ids)
        if problem:
            ctx["refusal"] = t("batch.refuse.missing", lang)
            return ctx
        built = core.build(
            details,
            tenant=_tenant(),
            papers=letter_sources(),
            lang=letter_lang,
            template=template_n,
            country=code,
        )
    except BatchLetterError as error:
        ctx["refusal"] = refusal_text(error, lang)
        return ctx
    except LetterError as error:
        ctx["failure"] = str(error)
        return ctx
    except DbError:
        logger.warning("Общее письмо: карточки не прочитались", exc_info=True)
        ctx["failure"] = t("batch.failed.read", lang)
        return ctx
    letter_lang = str(built["lang"])
    try:
        saved = store.latest_for_set(ids, tenant=_tenant(), lang=letter_lang)
    except DbError:
        saved = None
        ctx["saved_known"] = False
    editing = saved is not None and not ctx["show_draft"]
    ctx.update(
        letter=built,
        letter_lang=letter_lang,
        saved=saved,
        editing=editing,
        markup=(
            letter_markup.sanitize(saved.body)
            if editing and saved is not None
            else letter_markup.from_generated(str(built["letter"]))
        ),
        caveat_rows=_caveat_rows(built, lang),
        partners_differ=len(built["partners"]) > 1,  # type: ignore[arg-type]
        ids_csv=",".join(ids),
    )
    return ctx


def _caveat_rows(built: dict[str, object], lang: str) -> tuple[tuple[str, list[str]], ...]:
    """Оговорки письма словами языка экрана, у каждой — пиццерии, которых она касается."""
    codes = tuple(str(c) for c in built["not_restored"])  # type: ignore[attr-defined]
    units: dict[str, list[str]] = built["caveat_units"]  # type: ignore[assignment]
    words = view.letter_caveats(codes, lang)
    return tuple((word, units.get(code, [])) for code, word in zip(codes, words, strict=True))


def card_lines(inspection_id: str, tenant: str, country: str, lang: str) -> list[dict[str, str]]:
    """Строки карточки проверки «вошла в общее письмо от <дата>» со ссылкой; сбой — пусто."""
    try:
        letters = store.letters_of_inspection(inspection_id, tenant=tenant)
    except DbError:
        logger.warning("Общие письма проверки не прочитались", exc_info=True)
        return []
    return [
        {
            "date": b.created_at.strftime("%d.%m.%Y"),
            "href": url_for_country(
                b.country, lang=lang, batch="1", ids=",".join(b.inspection_ids), letter_lang=b.lang
            ),
        }
        for b in letters
    ]


def _addresses(details: list[InspectionDetail]) -> str:
    """Объединённый «Кому»: по правилам одиночного письма у каждой проверки, без повторов."""
    seen: dict[str, str] = {}
    for detail in details:
        for address in _ADDRESS_SPLIT.split(_inspection_to(detail, reach=auth.current_reach())):
            clean = address.strip()
            if clean:
                seen.setdefault(clean.casefold(), clean)
    return ", ".join(seen.values())


def install(app: Flask, conf: Settings) -> None:
    """Повесить фиксацию и черновик общего письма и возврат из похода в Gmail."""
    base = section("country").path + "/<code>/batch-letter"

    def back(code: str, ids: tuple[str, ...], lang: str, **params: str) -> Response:
        return redirect(
            url_for_country(
                code, lang=lang, batch="1", ids=",".join(ids), letter_lang=lang, **params
            ),
            code=303,
        )

    def fix(code: str) -> tuple[str, tuple[str, ...], str, store.SavedBatchLetter | None, str]:
        """Общая часть «Сохранить» и «Черновик»: проверка прав и правила, фиксация текста.

        Возврат: страна, состав, язык письма, запись (или `None`), исход при неудаче.
        """
        refuse_foreign_origin()
        country = code.strip().upper()
        reach = auth.current_reach()
        if reach.countries is not None and country not in reach.countries:
            abort(404)
        ids = parse_ids(request.form.get("ids", ""))
        lang = request.form.get("letter_lang") or ""
        if guard.permit("inspection.letter", _tenant()) is not None:
            abort(403)
        try:
            details, problem = load_details(ids)
            if problem:
                return country, ids, lang, None, "refused"
            # Правило выбора — на сервере при каждой фиксации, а не только при показе окна.
            core.check_selection(details, tenant=_tenant(), country=country)
            body = letter_markup.for_saving(request.form.get("text") or "")
            вошедший = auth.current_account()
            saved = store.save_batch_letter(
                ids,
                tenant=_tenant(),
                country=country,
                body=body,
                lang=lang or details[-1].inspection.report_lang,
                saved_by="—" if вошедший is None else вошедший.login,
            )
        except BatchLetterError:
            return country, ids, lang, None, "refused"
        except (DbError, ValueError):
            return country, ids, lang, None, "failed"
        return country, ids, saved.lang, saved, ""

    @app.post(base + "/save", endpoint="batch_letter_save")
    @guard.action("inspection.letter", object_in_route=True)
    def save(code: str) -> Response:
        country, ids, lang, saved, outcome = fix(code)
        return back(country, ids, lang, saved="ok" if saved else outcome)

    @app.post(base + "/draft", endpoint="batch_letter_draft")
    @guard.action("inspection.letter", object_in_route=True)
    def draft(code: str) -> Response:
        country, ids, lang, saved, outcome = fix(code)
        if saved is None:
            return back(country, ids, lang, saved=outcome)
        начать: Callable[[str, str, str], Response | None] | None = current_app.extensions.get(
            MAIL_CONSENT_KEY
        )
        поход = None if начать is None else начать(MAIL_KIND, saved.id, saved.lang)
        if поход is None:
            return back(country, ids, saved.lang, gmail="unavailable")
        return поход

    def _back(ident: str, lang: str, outcome: str) -> Response:
        saved = store.get_batch_letter(ident, tenant=_tenant())
        if saved is None:
            return redirect(url_for("country_index"), code=303)
        return back(saved.country, saved.inspection_ids, lang, gmail=outcome)

    def _finish(ident: str, lang: str, token: Callable[[], str]) -> Response:
        """Возврат от Google: PDF всех проверок и объединённые адресаты — в черновик."""
        if not guard.may("inspection.letter", _tenant()):
            abort(404)
        try:
            saved = store.get_batch_letter(ident, tenant=_tenant())
            if saved is None:
                return _back(ident, lang, "failed")
            details, problem = load_details(saved.inspection_ids)
            if problem:
                return _back(ident, lang, "failed")
            # Состав заморожен, но правило выбора проверяется и здесь: возврат от Google — второй
            # вход в ту же запись.
            ordered = core.check_selection(details, tenant=_tenant(), country=saved.country)
            доступ = token()
            files = tuple(
                (
                    data.report_name(d.inspection),
                    data.report_bytes(data.ensure_report(d, reach=auth.current_reach())),
                    "application/pdf",
                )
                for d in ordered
            )
            if any(not f[1].startswith(b"%PDF-") for f in files):
                raise LetterError("отчёт пуст или не является PDF")
        except MailAccountMismatchError as сбой:
            logger.warning("общее письмо: %s", сбой)
            return _back(ident, lang, OUTCOME_WRONG_ACCOUNT)
        except GoogleMailError as сбой:
            logger.warning("общее письмо: доступ к Gmail не получен: %s", сбой)
            return _back(ident, lang, "failed")
        except BatchLetterError:
            return _back(ident, lang, "refused")
        except (DbError, LetterError):
            logger.warning("PDF для общего письма %s недоступен", ident)
            return _back(ident, lang, "pdf_failed")
        try:
            first, last = (
                ordered[0].inspection.inspection_date,
                ordered[-1].inspection.inspection_date,
            )
            subject, body = letter_markup.subject_and_body(
                saved.body,
                fallback=draft_subject(
                    city="", date=core.period_text(first, last), lang=saved.lang
                ),
            )
            create_draft(
                доступ,
                to=_addresses(list(ordered)),
                cc=_копия_ук(_tenant()),
                subject=subject,
                body=body,
                attachments=files,
            )
        except (DbError, ConfigError, ValueError):
            logger.warning("Адресаты или шаблон общего письма не подготовлены")
            return _back(ident, lang, "failed")
        except MailAccountMismatchError as сбой:
            logger.warning("общее письмо: %s", сбой)
            return _back(ident, lang, OUTCOME_WRONG_ACCOUNT)
        except GoogleMailError as сбой:
            logger.warning("черновик общего письма в Gmail не создан: %s", сбой)
            return _back(ident, lang, "failed")
        return _back(ident, lang, "ok")

    app.extensions.setdefault(MAIL_RETURNS_KEY, {})[MAIL_KIND] = MailReturn(
        back=_back, finish=_finish
    )
