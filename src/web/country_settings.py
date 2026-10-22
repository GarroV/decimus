"""«Карточка страны» на экране «Страны» (D539, прежде «Настройки страны», D536).

Широкая панель справа на том же экране (D527): всё, что известно про страну, —
партнёр и девелопер, юридические партнёры из свода, пиццерии с адресами, датами
открытия и другими написаниями названия (D538). Видит каждый, кому видна страна;
почта партнёра — только УК (D375), правка — только администратору (ниже).

Строки пиццерий — те же `UnitRow`, что уже прочитал экран (`country_units`): второго
чтения базы ради панели нет. Правка — дверь веба в то, что уже есть:

- девелопер — справочник рейтингов (`ratings.countries.developer`), тот же
  `ratings_read.set_developer`, что у экрана «Рейтинги → Загрузки» (`ratings.py`);
- партнёр — пространство, за которым закреплена страна (`space_countries`), тот же
  `partner_spaces.add_countries`, что у «Пользователи → Пространства». Страна — один
  партнёр: занятую другим пространством страну отсюда не перенести, как и там;
  привязка добавляется, снять её можно только руками (`docs/18-access-map.md`).

Кто вправе — по матрице: оба маршрута объявлены действием `space.manage` (главный
админ и админ УК, D364). Кнопка на экране показывается по тому же коду, остальным
адреса отвечают отказом заслона.

Блок «Договор» (D603) — юрлицо партнёра, договор одной строкой, контакты по ДКК: список
строк на страну (`db/country_contracts.py`). Видит только УК (почты — персональные
данные, как `partner_email`, D375), правят ОСБ, админ и главный админ — отдельное
действие `contract.manage`, чтобы ОСБ не получила девелопера и партнёра страны
(`space.manage`). Два маршрута: сохранить строку (новую или правку) и снять её.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, abort, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import agg_store, ratings_read
from src.db import country_contracts as contracts_db
from src.db.errors import CountryContractError, DbError
from src.db.models import InspectionRow
from src.domain import report_langs
from src.domain.errors import ConfigError
from src.domain.tenants import HQ_TENANT

from . import auth, guard, partner_spaces
from . import country as country_data
from .country_units import UnitRow, UnitsData
from .origin import refuse_foreign_origin
from .sections import section

log = logging.getLogger(__name__)

#: Исходы сохранения — коды в адресе возврата (`?saved=`); текст подбирает экран.
SAVED = "ok"
FAILED = "failed"
#: Договор: ввод не прошёл проверку (почта, пустая строка) — не база, а поля.
INVALID = "invalid"
_OUTCOMES = frozenset({SAVED, FAILED, INVALID})

#: Длина имени девелопера — как у поля справочника (`country_page.DEVELOPER_MAX`).
DEVELOPER_MAX = 120


@dataclass(frozen=True)
class SpaceOption:
    """Пространство партнёра для выбора: код и название."""

    code: str
    name: str


#: Порядок стадий в сводке и таблице карточки; закрытые — в конце.
STAGES = ("open", "paused", "pipeline", "closed")


@dataclass(frozen=True)
class LegalPartner:
    """Юридический партнёр из свода: имя, сколько у него пиццерий страны, почта (только УК)."""

    name: str
    units: int
    email: str = ""


@dataclass(frozen=True)
class AggScore:
    """Оценка пиццерии на площадке доставки: код площадки, оценка, шкала."""

    aggregator: str
    score: float
    scale: int


@dataclass(frozen=True)
class Auditor:
    """Кто проверял страну за период экрана и сколько раз."""

    name: str
    inspections: int


@dataclass(frozen=True)
class Panel:
    """Что показывает панель: девелопер, чья страна, кому её можно отдать, исход."""

    code: str
    developer: str
    #: Пространство, за которым закреплена страна; пусто — ни за кем.
    owner: str = ""
    owner_name: str = ""
    #: Пространства партнёров, которым страну можно закрепить (пока она ничья).
    spaces: tuple[SpaceOption, ...] = ()
    #: Пространства не прочитались — форма партнёра не рисуется.
    failed: bool = False
    #: Исход прошлого сохранения (`ok` / `failed`) или пусто.
    saved: str = ""
    #: Формы правки — только у `space.manage`; остальным те же сведения текстом.
    can_edit: bool = False
    #: Пиццерии страны в порядке таблицы и сводка «стадия → сколько».
    rows: tuple[UnitRow, ...] = ()
    stages: tuple[tuple[str, int], ...] = ()
    partners: tuple[LegalPartner, ...] = ()
    #: Свод пиццерий не прочитался — адресов и дат нет, и панель об этом говорит.
    profiles_failed: bool = False
    #: Площадки доставки: код Dodo → оценки (D543); не прочитались — отметка.
    aggregators: Mapping[str, tuple[AggScore, ...]] = field(default_factory=dict)
    aggregators_failed: bool = False
    #: Аудиторы страны за период экрана, по числу проверок.
    auditors: tuple[Auditor, ...] = ()
    #: Языки отчёта страны из методики (`report_langs.json`, D415) — их предлагает бот.
    report_langs: tuple[str, ...] = ()
    #: Блок «Договор» (D603): виден только УК; формы правки — у `contract.manage`.
    show_contract: bool = False
    can_contract: bool = False
    contracts: tuple[contracts_db.Contract, ...] = ()
    #: Договор не прочитался — блок об этом говорит, а не рисует «договора нет».
    contracts_failed: bool = False


def _ordered(rows: Sequence[UnitRow]) -> tuple[UnitRow, ...]:
    """Открытые сверху, закрытые в конце; внутри стадии — по названию."""
    порядок = {stage: i for i, stage in enumerate(STAGES)}
    return tuple(sorted(rows, key=lambda r: (порядок.get(r.stage, 0), r.name.casefold())))


def _stages(rows: Sequence[UnitRow]) -> tuple[tuple[str, int], ...]:
    счёт = Counter(r.stage for r in rows)
    return tuple((stage, счёт[stage]) for stage in STAGES if счёт[stage])


def _partners(rows: Sequence[UnitRow], *, show_email: bool) -> tuple[LegalPartner, ...]:
    """Партнёры из свода по числу пиццерий; почта — только если её вправе видеть (D375)."""
    счёт = Counter(r.partner for r in rows if r.partner)
    почта = {r.partner: r.partner_email for r in rows if r.partner and r.partner_email}
    return tuple(
        LegalPartner(name, n, почта.get(name, "") if show_email else "")
        for name, n in sorted(счёт.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
    )


def _aggregators(code: str) -> tuple[dict[str, tuple[AggScore, ...]], bool]:
    """Последние оценки площадок доставки по пиццериям страны — только когда карточка открыта."""
    try:
        rows = agg_store.latest((code,))
    except DbError:  # RatingsError — тоже DbError
        log.warning("Оценки агрегаторов для карточки страны не прочитались", exc_info=True)
        return {}, True
    out: dict[str, list[AggScore]] = {}
    for r in sorted(rows, key=lambda r: r.aggregator):
        out.setdefault(r.dodo_id, []).append(AggScore(r.aggregator, r.score, r.scale))
    return {k: tuple(v) for k, v in out.items()}, False


def _auditors(inspections: Sequence[InspectionRow]) -> tuple[Auditor, ...]:
    счёт = Counter(i.auditor for i in inspections if i.auditor)
    return tuple(
        Auditor(name, n) for name, n in sorted(счёт.items(), key=lambda kv: (-kv[1], kv[0]))
    )


def _report_langs(code: str) -> tuple[str, ...]:
    try:
        return tuple(report_langs.report_langs_for(code))
    except ConfigError:
        log.warning("Языки отчёта страны не прочитались: методика не настроена", exc_info=True)
        return ()


def _contracts(code: str) -> tuple[tuple[contracts_db.Contract, ...], bool]:
    """Строки договора страны; не прочиталось — пусто и отметка, а не «договора нет»."""
    try:
        return contracts_db.read(code), False
    except (DbError, ConfigError):
        log.warning("Договор страны %s не прочитался", code, exc_info=True)
        return (), True


def load(
    code: str,
    developer: str,
    saved: str,
    *,
    units: UnitsData,
    can_edit: bool,
    show_email: bool,
    can_contract: bool = False,
    inspections: Sequence[InspectionRow] = (),
) -> Panel:
    """Карточка страны `code`: партнёр и девелопер, партнёры свода, пиццерии, договор.

    Договор читается и показывается только там, где видны почты (`show_email`, УК, D375).
    """
    сведения: dict[str, Any] = {
        "code": code,
        "developer": developer,
        "saved": saved if saved in _OUTCOMES else "",
        "can_edit": can_edit,
        "rows": _ordered(units.rows),
        "stages": _stages(units.rows),
        "partners": _partners(units.rows, show_email=show_email),
        "profiles_failed": units.profiles_failed,
        "auditors": _auditors(inspections),
        "report_langs": _report_langs(code),
    }
    сведения["aggregators"], сведения["aggregators_failed"] = _aggregators(code)
    if show_email:
        сведения["show_contract"] = True
        сведения["can_contract"] = can_contract
        сведения["contracts"], сведения["contracts_failed"] = _contracts(code)
    try:
        spaces = partner_spaces.overview()
    except DbError:
        log.warning("Пространства партнёров для карточки страны не прочитались", exc_info=True)
        return Panel(**сведения, failed=True)
    owner = next((s for s in spaces if code in s.countries), None)
    free = tuple(SpaceOption(s.code, s.name or s.code) for s in spaces if s.code != HQ_TENANT)
    return Panel(
        **сведения,
        owner=owner.code if owner else "",
        owner_name=(owner.name or owner.code) if owner else "",
        spaces=() if owner or not can_edit else free,
    )


def _back(code: str, outcome: str, lang_in_url: str) -> Response:
    params: dict[str, Any] = {"code": code, "settings": 1, "saved": outcome}
    if lang_in_url:
        params["lang"] = lang_in_url
    return redirect(url_for("country", **params))


def install(app: Flask) -> None:
    """Маршруты настроек страны: девелопер и партнёр. Оба — действие `space.manage`."""
    base = section("country").path + "/<code>/settings"

    def _checked(raw: str) -> str:
        """Код страны из адреса в охвате вошедшего — иначе 404, как у несуществующей."""
        code = country_data.normalize_code(raw)
        reach = auth.current_reach().countries
        if not code or (reach is not None and code not in reach):
            abort(404)
        return code

    @app.post(base + "/developer", endpoint="country_set_developer")
    @guard.action("space.manage")
    def set_developer(code: str) -> Response:
        страна = _checked(code)
        refuse_foreign_origin()
        вошедший = auth.current_account()
        имя = (request.form.get("developer") or "").strip()[:DEVELOPER_MAX]
        try:
            changed = ratings_read.set_developer(
                страна, имя, actor=вошедший.login if вошедший else ""
            )
        except (DbError, ratings_read.RatingsEditError):
            log.warning("Девелопер страны %s не сохранён", страна, exc_info=True)
            changed = False
        return _back(страна, SAVED if changed else FAILED, request.args.get("lang", ""))

    @app.post(base + "/space", endpoint="country_set_space")
    @guard.action("space.manage")
    def set_space(code: str) -> Response:
        страна = _checked(code)
        refuse_foreign_origin()
        пространство = (request.form.get("space") or "").strip()
        try:
            partner_spaces.add_countries(пространство, (страна,))
            outcome = SAVED
        except DbError:
            log.warning("Страна %s не закреплена за %s", страна, пространство, exc_info=True)
            outcome = FAILED
        return _back(страна, outcome, request.args.get("lang", ""))

    contract_base = base + "/contract"

    def _contract_back(code: str, outcome: str) -> Response:
        return _back(code, outcome, request.args.get("lang", ""))

    @app.post(contract_base, endpoint="country_save_contract")
    @guard.action("contract.manage")
    def save_contract(code: str) -> Response:
        """Новая строка договора страны или правка существующей (`contract_id`)."""
        страна = _checked(code)
        refuse_foreign_origin()
        вошедший = auth.current_account()
        поля = contracts_db.ContractFields(
            **{
                name: request.form.get(name) or ""
                for name in (*contracts_db.TEXT_FIELDS, "dkk_emails")
            }
        )
        try:
            contracts_db.clean(поля)
        except CountryContractError:
            return _contract_back(страна, INVALID)
        try:
            contracts_db.save(
                страна,
                поля,
                actor=вошедший.login if вошедший else "",
                contract_id=(request.form.get("contract_id") or "").strip() or None,
            )
        except (DbError, ConfigError):
            log.warning("Договор страны %s не сохранён", страна, exc_info=True)
            return _contract_back(страна, FAILED)
        return _contract_back(страна, SAVED)

    @app.post(contract_base + "/<contract_id>/delete", endpoint="country_delete_contract")
    @guard.action("contract.manage")
    def delete_contract(code: str, contract_id: str) -> Response:
        страна = _checked(code)
        refuse_foreign_origin()
        try:
            contracts_db.remove(страна, contract_id)
        except (DbError, ConfigError):
            log.warning("Строка договора страны %s не снята", страна, exc_info=True)
            return _contract_back(страна, FAILED)
        return _contract_back(страна, SAVED)
