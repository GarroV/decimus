"""Раздел «Методика»: правка состава чек-листа той же дверью, что MCP и CLI.

**Своих правил версионирования здесь нет ни одного.** Снимок версии, правка
копии, сверка движком, отпечаток, запрет пустой правки, журнал и публикация
отдельным шагом живут в хранилище методики (`src/mcp/checklist.py`) и вызываются
отсюда как есть (D049, D050). Вторая копия этого хода разошлась бы с первой на
первой же правке — и разошлась бы молча: экран показывал бы версию, которой
движок не видел.

**Почему дверь лежит в пакете `src.mcp`.** Хранилище версий появилось вместе с
первым потребителем — разговором с агентом — и осталось там же, хотя склад
версий методики не принадлежит ни одной поверхности. Этот модуль — ЕДИНСТВЕННОЕ
место блока `web`, которому разрешено знать про `src.mcp`; всё остальное ходит
сюда, и держит это `tests/test_web_bounds.py`, а не договорённость. Честная
починка — переселить хранилище ярусом ниже обоих потребителей; она не в объёме
этой задачи и названа в отчёте блока.

**Хранилище одно на продукт.** Каталог версий и боевой каталог методики берутся
из тех же переменных, что у MCP (`MCP_CHECKLIST_STORE`, `AUDIT_DATA_DIR`).
Своя переменная веба завела бы второе хранилище, и правка из админки уехала бы
мимо той методики, по которой считает движок.

**Кто правит — записывается в журнал.** Журнал хранилища ведёт поле `note`, и
админка кладёт туда поверхность и логин вошедшего: через год по журналу должно
быть видно, пришла правка из разговора с агентом или человеком с экрана.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.mcp import checklist_tools as door
from src.mcp import checklists as lists_door
from src.mcp.checklist import Store, current_version, tip_version
from src.mcp.checklist_layout import ACTIVE, DRAFT, RETIRED, for_code
from src.mcp.config import DATA_DIR_VAR, MCP_CHECKLIST_STORE_VAR
from src.mcp.errors import McpError

from .errors import MethodologyRefused

#: Имена переменных окружения — для текста на странице. Пересказывать их
#: строкой в шаблоне нельзя: переименуют в `mcp`, а здесь останется старое имя,
#: и человек пойдёт заводить несуществующую переменную.
STORE_VAR = MCP_CHECKLIST_STORE_VAR
DATA_VAR = DATA_DIR_VAR

#: Виды пунктов, которые можно завести. Список берётся у двери, а не заводится
#: здесь: свой разошёлся бы с тем, что примет движок.
ITEM_KINDS = door.ITEM_KINDS

#: Предел пояснения к правке — тоже у двери: журнал один, и правило длины у
#: него одно.
MAX_NOTE = door.MAX_NOTE


@dataclass(frozen=True)
class StoreState:
    """Хранилище версий методики — или внятная причина, почему его нет."""

    store: Store | None
    #: Имена незаданных переменных. Пусто и `store is None` не бывает вместе:
    #: либо хранилище есть, либо сказано, чего не хватает.
    missing: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.store is not None


@dataclass(frozen=True)
class Composition:
    """Состав одной версии методики — как он лежит в файлах, без арифметики."""

    version: str
    #: Версия, по которой движок считает проверки сегодня.
    current: str
    #: Самая свежая записанная версия. Правка отсчитывается от неё.
    latest: str
    items: tuple[Mapping[str, str], ...]
    zones: tuple[Mapping[str, str], ...]
    versions: tuple[Mapping[str, Any], ...]

    @property
    def is_latest(self) -> bool:
        return self.version == self.latest

    @property
    def unpublished(self) -> bool:
        """Есть ли записанная, но не опубликованная версия."""
        return self.latest != self.current


@dataclass(frozen=True)
class Edit:
    """Чем кончилась принятая правка. Отклонённая приходит отказом, а не полем."""

    base_version: str
    version: str
    status: str


def _abs(raw: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(raw)))


def load_store(env: Mapping[str, str] | None = None) -> StoreState:
    """Хранилище версий методики из окружения. Не настроено — сказать, чего нет.

    Отказа на сборке приложения здесь нет намеренно: админка поднимается и
    показывает историю проверок и без правки методики. А вот молча показать
    пустой состав нельзя — это выглядело бы как «чек-лист пуст», поэтому
    незаданная настройка называется на экране поимённо.
    """
    src = os.environ if env is None else env
    root = (src.get(STORE_VAR) or "").strip()
    live = (src.get(DATA_VAR) or "").strip()
    missing = tuple(name for name, value in ((STORE_VAR, root), (DATA_VAR, live)) if not value)
    if missing:
        return StoreState(store=None, missing=missing)
    return StoreState(store=Store(root=_abs(root), live=_abs(live)))


def _refusal(exc: McpError) -> MethodologyRefused:
    """Отказ двери — отказом блока, слово в слово.

    Пересказ потерял бы то единственное, ради чего отказ и печатается: движок
    называет, ЧТО именно он не принял, и человеку с экрана нужно это, а не
    «правка отклонена».
    """
    return MethodologyRefused(str(exc))


def load_composition(store: Store, *, tenant: str, version: str | None = None) -> Composition:
    """Состав версии: пункты, зоны и список версий. Ни одной своей цифры.

    **Без явной версии показывается самая свежая записанная, а не действующая.**
    Экран правки обязан показывать то, от чего отсчитывается следующая правка:
    дверь стакает правки на последнюю записанную версию, и человек, правящий
    опубликованную, получал бы не тот состав, который увидит после сохранения.
    Чем действующая отличается от последней — говорит шапка страницы.
    """
    try:
        versions = door.checklist_versions(tenant=tenant, store=store)
        listing = door.checklist_items(
            tenant=tenant, store=store, version=version or str(versions["latest"])
        )
    except McpError as отказ:
        raise _refusal(отказ) from None
    return Composition(
        version=str(listing["version"]),
        current=str(versions["current"]),
        latest=str(versions["latest"]),
        items=tuple(listing["items"]),
        zones=tuple(listing["zones"]),
        versions=tuple(versions["versions"]),
    )


def full_items(store: Store, *, tenant: str, version: str) -> tuple[dict[str, str], ...]:
    """Пункты версии ВМЕСТЕ с критериями — для разницы перед публикацией.

    Состав (`load_composition`) критериев не несёт: они лежат отдельным файлом.
    Разница без них назвала бы правку критериев «изменений нет» — поэтому
    здесь каждый пункт читается целиком. Дорого на каждом открытии экрана,
    поэтому зовётся только по запросу разницы.
    """
    try:
        listing = door.checklist_items(tenant=tenant, store=store, version=version)
        return tuple(
            dict(
                door.checklist_item(
                    tenant=tenant, store=store, code=str(item.get("id", "")), version=version
                )["item"]
            )
            for item in listing["items"]
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def zones_of_version(store: Store, *, tenant: str, version: str) -> tuple[Mapping[str, str], ...]:
    """Зоны и доли версии — как лежат в файле."""
    try:
        return tuple(door.checklist_items(tenant=tenant, store=store, version=version)["zones"])
    except McpError as отказ:
        raise _refusal(отказ) from None


def needs_set_name(composition: Composition) -> bool:
    """Нужно ли спросить у человека имя набора перед правкой.

    Идентификатор версии составной: имя набора, дата издания и отпечаток данных
    (D050). У методики, которую никто не издавал, имени нет — она живёт под
    одним отпечатком, — и хранилище отказывает первой же правке: дата без имени
    не идентификатор. Имя спрашивается ровно один раз, дальше оно подхватывается
    из предыдущей версии.

    Найдено живым смоуком: без этого поля конструктор отказывал на первой же
    правке боевой методики, а человеку с экрана предлагалось назвать аргумент
    инструмента MCP, которого у него нет.
    """
    for версия in composition.versions:
        if версия.get("version") == composition.latest:
            return not версия.get("name")
    return False


def latest_version(store: Store) -> str:
    """Самая свежая ЗАПИСАННАЯ версия — та, от которой отсчитывается правка."""
    try:
        return tip_version(store)
    except McpError as отказ:
        raise _refusal(отказ) from None


def published_version(store: Store) -> str:
    """Версия, по которой движок считает проверки сегодня."""
    try:
        return current_version(store)
    except McpError as отказ:
        raise _refusal(отказ) from None


def load_item(
    store: Store, *, tenant: str, code: str, version: str | None = None
) -> dict[str, Any]:
    """Пункт вместе с критериями. Неизвестный код — отказ двери, слово в слово.

    Пустой выдачи и 404 здесь нет намеренно: дверь различает «такого пункта
    нет» и «код написан не по правилам», и человеку с экрана нужна именно эта
    разница, а не одинаковая пустая страница.

    Версия по умолчанию — свежая записанная, а не действующая, по той же
    причине, что и у состава: правка стакается на свежую.
    """
    try:
        return door.checklist_item(
            tenant=tenant, store=store, code=code, version=version or tip_version(store)
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def _maybe(value: str | None) -> str | None:
    """Пустое поле формы — «не трогать», а не «стереть».

    Форма присылает все поля, включая нетронутые, пустой строкой. Отданная
    двери как есть, она означала бы «поставить пусто» — то есть правка одной
    формулировки стирала бы остальные.
    """
    if value is None:
        return None
    text = value.strip()
    return text or None


def _days(value: str | None) -> int | None:
    """Срок устранения числом. Не число — отказ, а не тихий ноль.

    Нулевой срок печатается партнёру как «устранить немедленно»
    (`docs/10-checklist-configuration.md`), поэтому подставить его вместо
    непонятного ввода значило бы решить за управляющую компанию, каким будет
    предписание.
    """
    text = _maybe(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        raise MethodologyRefused(
            f"Срок устранения «{text}» не число. Пустой срок и срок 0 — разные вещи: "
            f"нулевой печатается партнёру как «устранить немедленно»"
        ) from None


def _signed(author: str, note: str | None) -> str:
    """Пояснение к правке с подписью поверхности и вошедшего.

    Журнал один на все двери, и через год по нему обязано быть видно, пришла
    правка из разговора с агентом или с экрана админки — и от кого именно.
    """
    сказанное = _maybe(note)
    подпись = f"web:{author}"
    return f"{подпись} — {сказанное}" if сказанное else подпись


def _edit(outcome: Mapping[str, Any]) -> Edit:
    return Edit(
        base_version=str(outcome["base_version"]),
        version=str(outcome["version"]),
        status=str(outcome["status"]),
    )


def add_item(
    store: Store,
    *,
    tenant: str,
    author: str,
    process: str,
    question_ru: str,
    levels: str,
    code: str | None = None,
    process_en: str | None = None,
    question_en: str | None = None,
    zones: str | None = None,
    days: str | None = None,
    criteria: str | None = None,
    kind: str | None = None,
    note: str | None = None,
    version_name: str | None = None,
) -> Edit:
    """Завести пункт — новой версией методики, а не правкой действующей."""
    try:
        return _edit(
            door.add_checklist_item(
                tenant=tenant,
                store=store,
                process=process,
                question_ru=question_ru,
                levels=levels,
                code=_maybe(code),
                process_en=_maybe(process_en),
                question_en=_maybe(question_en),
                zones=_maybe(zones),
                days=_days(days),
                criteria=_maybe(criteria),
                kind=_maybe(kind),
                note=_signed(author, note),
                version_name=_maybe(version_name),
            )
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def edit_item(
    store: Store,
    *,
    tenant: str,
    author: str,
    code: str,
    process: str | None = None,
    process_en: str | None = None,
    question_ru: str | None = None,
    question_en: str | None = None,
    levels: str | None = None,
    zones: str | None = None,
    days: str | None = None,
    criteria: str | None = None,
    note: str | None = None,
    version_name: str | None = None,
) -> Edit:
    """Поправить пункт — новой версией. Меняются только заполненные поля."""
    try:
        return _edit(
            door.edit_checklist_item(
                tenant=tenant,
                store=store,
                code=code,
                process=_maybe(process),
                process_en=_maybe(process_en),
                question_ru=_maybe(question_ru),
                question_en=_maybe(question_en),
                levels=_maybe(levels),
                zones=_maybe(zones),
                days=_days(days),
                criteria=_maybe(criteria),
                note=_signed(author, note),
                version_name=_maybe(version_name),
            )
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def disable_item(
    store: Store,
    *,
    tenant: str,
    author: str,
    code: str,
    note: str | None = None,
    version_name: str | None = None,
) -> Edit:
    """Выключить пункт. Строка остаётся в методике — так видно, что его убрали.

    Удаления строки совсем (`hard`) на экране нет намеренно: следа правки при
    нём не остаётся, а обратимость — единственное, чем правка состава дешевле
    правки движка.
    """
    try:
        return _edit(
            door.remove_checklist_item(
                tenant=tenant,
                store=store,
                code=code,
                note=_signed(author, note),
                version_name=_maybe(version_name),
            )
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def restore_item(
    store: Store,
    *,
    tenant: str,
    author: str,
    code: str,
    note: str | None = None,
    version_name: str | None = None,
) -> Edit:
    """Включить выключенный пункт обратно — тоже новой версией."""
    try:
        return _edit(
            door.restore_checklist_item(
                tenant=tenant,
                store=store,
                code=code,
                note=_signed(author, note),
                version_name=_maybe(version_name),
            )
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def publish_version(store: Store, *, tenant: str, version: str) -> str:
    """Сделать версию действующей — отдельным шагом, а не вместе с правкой (D049).

    Уже посчитанные проверки не пересчитываются и остаются на своей версии:
    отчёт, отправленный партнёру, задним числом не меняется.
    """
    try:
        итог = door.publish_checklist_version(tenant=tenant, store=store, version=version)
    except McpError as отказ:
        raise _refusal(отказ) from None
    return str(итог["published"])


# --- чек-листы как сущности (T347) --------------------------------------------
#
# Здесь же, а не своим модулем: дверь веба в хранилище методики ровно одна, и
# это проверяется сборкой (`tests/test_web_bounds.py`). Вторая дверь означала бы
# два разных представления об одном хранилище — ровно то, чего вся конструкция
# избегает.

#: Состояния чек-листа, в порядке жизни: черновик → в работе → снят.
CHECKLIST_STATES = (DRAFT, ACTIVE, RETIRED)


@dataclass(frozen=True)
class Difference:
    """«Сейчас в проде вот этот, будет вот этот» — то, что человек видит до кнопки."""

    current: lists_door.Summary | None
    candidate: lists_door.Summary | None


def store_for(store: Store, code: str | None) -> Store:
    """Хранилище, наведённое на чек-лист с экрана — или на применённый к проду.

    Тот же ход, что у точки входа MCP (`rpc`), и та же функция: экран, знающий
    про чек-листы своё, однажды показал бы не то, что правит агент.
    """
    try:
        return for_code(store, code)
    except McpError as отказ:
        raise _refusal(отказ) from None


def checklists_overview(store: Store) -> list[lists_door.Overview]:
    """Все чек-листы хранилища. Пусто — пустой список, а не отказ.

    Нетронутое хранилище дверь заводит сама (`checklists.overview`): иначе
    первый заход на экран показал бы «чек-листов нет» на площадке, где
    методика есть и по ней считают, — пустой перечень читался бы как факт о
    продукте.
    """
    try:
        return lists_door.overview(store)
    except McpError as отказ:
        raise _refusal(отказ) from None


def checklist_difference(store: Store) -> Difference:
    """Что стоит в проде сейчас и что встанет, если применить этот чек-лист."""
    try:
        сейчас, кандидат = lists_door.difference(store)
    except McpError as отказ:
        raise _refusal(отказ) from None
    return Difference(current=сейчас, candidate=кандидат)


def create_checklist(
    store: Store, *, tenant: str, author: str, code: str, name_ru: str, name_en: str
) -> Any:
    """Завести чек-лист с нуля. Рождается черновиком и к проду не идёт."""
    целевое = store_for(store, code)
    try:
        return lists_door.create(
            целевое, tenant=tenant, name_ru=name_ru, name_en=name_en, by=author
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def rename_checklist(
    store: Store, *, tenant: str, author: str, code: str, name_ru: str, name_en: str
) -> Any:
    """Поменять названия. Код не меняется ничем и никогда."""
    try:
        return lists_door.rename(
            store_for(store, code), tenant=tenant, name_ru=name_ru, name_en=name_en, by=author
        )
    except McpError as отказ:
        raise _refusal(отказ) from None


def set_checklist_state(store: Store, *, tenant: str, author: str, code: str, state: str) -> Any:
    """Черновик / в работе / снят."""
    try:
        return lists_door.set_state(store_for(store, code), tenant=tenant, state=state, by=author)
    except McpError as отказ:
        raise _refusal(отказ) from None


def apply_checklist(store: Store, *, tenant: str, author: str, code: str) -> dict[str, object]:
    """Применить чек-лист к проду: по нему пойдут проверки.

    Заслоны — в двери: пустой, снятый и без опубликованного издания к проду не
    идут. Экран их не повторяет, он их показывает.
    """
    try:
        return lists_door.apply_to_production(store_for(store, code), tenant=tenant, by=author)
    except McpError as отказ:
        raise _refusal(отказ) from None
