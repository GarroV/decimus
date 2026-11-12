"""Заслон: в вебе партнёр не меняет методику УК и чек-листы другого партнёра (D285, D761 п.4).

Каждый правящий маршрут «Методики» проверяется трижды одним и тем же запросом:

1. **Контроль** — тот, кому правка открыта (админ УК на эталоне, админ AM на своём
   чек-листе), шлёт запрос, и хранилище МЕНЯЕТСЯ. Без этого отказ ниже мог бы
   означать неполную форму, а не границу пространства.
2. **Партнёр на эталоне** — админ и сотрудник AM шлют тот же запрос на эталон
   (по коду, с `?space=hq` и без кода — умолчание ведёт в применённый к проду):
   всё вне пространства AM байт в байт прежнее.
3. **Чужой партнёр** — админ GE шлёт тот же запрос на чек-лист AM: всё вне
   пространства GE прежнее.

Список маршрутов сверяется с картой приложения: новый POST под `/admin` без строки
здесь роняет `test_каждый_маршрут_записи_проверен`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from partner_readonly_harness import ДРУГОЙ, ПАРТНЁР, УК, свежее_хранилище, снимок, собрать_образец
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.mcp.checklist import Store, tip_version
from src.web.texts import t

ЗАГОЛОВКИ = {"Origin": СВОЙ}


@pytest.fixture(scope="module")
def образец(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return собрать_образец(tmp_path_factory.mktemp("образец"))


@pytest.fixture
def склад(образец: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    store = свежее_хранилище(образец, tmp_path / "копия")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    # Движок читает методику через указатель прода — как на площадке; иначе публикация
    # отказала бы на обычном каталоге и контроль публикации не доказал бы ничего.
    monkeypatch.setenv("AUDIT_DATA_DIR", str(store.root / "current"))
    return store


#: Маршрут → (путь с `{код}` — код чек-листа или пусто, форма). Коды пунктов и зон
#: есть и в эталоне, и в чек-листе AM (`partner_readonly_harness`).
ПРАВКИ: dict[str, tuple[str, dict[str, Any]]] = {
    "/admin/items": (
        "/admin/items",
        {
            "process": "Чистота",
            "question_ru": "Новый вопрос",
            "levels": "D1",
            "zones": "fridge",
            "days": "10",
            "criteria": "D1: проба",
            "kind": "violation",
        },
    ),
    "/admin/items/<code>": ("/admin/items/CLN01", {"question_ru": "Изменено"}),
    "/admin/items/<code>/disable": ("/admin/items/CLN01/disable", {"note": "проба"}),
    "/admin/items/<code>/restore": ("/admin/items/CLN02/restore", {"note": "проба"}),
    "/admin/zones": (
        "/admin/zones",
        {"code": "newz", "name_ru": "Новая", "name_en": "New", "equal_shares": "1"},
    ),
    "/admin/zones/shares": ("/admin/zones/shares", {"share_fridge": "60", "share_dough": "40"}),
    "/admin/zones/<code>/rename": ("/admin/zones/fridge/rename", {"name_ru": "Переименована"}),
    "/admin/zones/<code>/remove": ("/admin/zones/dough/remove", {"equal_shares": "1"}),
    "/admin/route": (
        "/admin/route",
        {"zone": ["fridge", "dough"], "order_fridge": "2", "order_dough": "1"},
    ),
    "/admin/scoring": ("/admin/scoring", {"d1": "0.7"}),
    "/admin/publish": ("/admin/publish", {"version": "{tip}"}),
    "/admin/checklists/<code>/state": ("/admin/checklists/{код}/state", {"state": "retired"}),
    "/admin/checklists/<code>/master": ("/admin/checklists/{код}/master", {"on": "1"}),
    "/admin/bot/<code>": ("/admin/bot/{код}", {"on": "{bot}"}),
}

#: Маршруты, у которых нет контроля «правка открыта и проходит» в этой раскладке:
#: заведение (партнёру закрыто вовсе, D283) и указатель прода (только УК, D460) —
#: для них проверяется лишь неизменность. `/admin/checklists` (POST) — заведение.
БЕЗ_КОНТРОЛЯ = {"/admin/checklists": {"code": "zz", "name_ru": "Новый", "name_en": "New"}}
ПРИМЕНЕНИЕ = "/admin/checklists/<code>/apply"


def _маршруты_записи(app: Flask) -> set[str]:
    return {
        p.rule
        for p in app.url_map.iter_rules()
        if "POST" in (p.methods or set()) and p.rule.startswith("/admin/")
    }


def test_каждый_маршрут_записи_проверен() -> None:
    """Новый правящий маршрут «Методики» обязан встать в этот заслон."""
    известные = set(ПРАВКИ) | set(БЕЗ_КОНТРОЛЯ) | {ПРИМЕНЕНИЕ}
    assert _маршруты_записи(собрать(tenant=УК)) == известные


@pytest.fixture
def клиент(склад: Store, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Фабрика: войти от имени (пространство, роль) — и получить клиента."""
    открытые: list[Any] = []

    def войти_как(tenant: str, role: str) -> Any:
        подменить_двери(monkeypatch, tenant=tenant, role=role)
        контекст = собрать(tenant=УК).test_client()
        клиент = контекст.__enter__()
        открытые.append(контекст)
        assert войти(клиент).status_code == 302
        return клиент

    yield войти_как
    for контекст in открытые:
        контекст.__exit__(None, None, None)


def _запрос(маршрут: str, склад: Store, *, space: str, code: str) -> tuple[str, dict[str, Any]]:
    путь, форма = ПРАВКИ[маршрут]
    цель = Store(root=склад.root, live=склад.live, space=space, code=code)
    бот = "0" if code == "bizdev" else "1"
    подстановки = {"{tip}": tip_version(цель), "{bot}": бот}
    готовая = {
        ключ: (подстановки.get(значение, значение) if isinstance(значение, str) else значение)
        for ключ, значение in форма.items()
    }
    return путь.replace("{код}", code), готовая


def _цель_маршрута(маршрут: str, space: str) -> str:
    """Код чек-листа, на котором маршрут меняет что-то наверняка.

    Состояние и метку «главный» у применённого к проду эталона дверь меняет не
    всякие, поэтому в пространстве УК они проверяются на втором чек-листе, `spare`.
    """
    if space == "hq" and маршрут.startswith("/admin/checklists/"):
        return "spare"
    return "bizdev" if space == "hq" else "rnd"


# --- 1. контроль: запрос годен и меняет хранилище у того, кому открыт -------------


@pytest.mark.parametrize("маршрут", sorted(ПРАВКИ))
@pytest.mark.parametrize(("кто", "space"), [(УК, "hq"), (ПАРТНЁР, "am")])
def test_контроль_тот_кому_открыто_меняет(
    склад: Store, клиент: Any, маршрут: str, кто: str, space: str
) -> None:
    код = _цель_маршрута(маршрут, space)
    путь, форма = _запрос(маршрут, склад, space=space, code=код)
    до = снимок(склад.root)

    ответ = клиент(кто, "admin").post(f"{путь}?checklist={код}", data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code in (200, 302), ответ.status_code
    assert снимок(склад.root) != до, (
        f"{маршрут}: запрос контроля ничего не изменил — отказ постороннему ниже "
        f"ничего бы не доказал. Ответ: {ответ.get_data(as_text=True)[-600:]}"
    )


# --- 2. партнёр на эталоне УК ----------------------------------------------------

#: Как партнёр может назвать эталон: кодом, кодом с пространством, никак (умолчание).
АДРЕСА_ЭТАЛОНА = ["?checklist={код}", "?space=hq&checklist={код}", ""]


@pytest.mark.parametrize("адрес", АДРЕСА_ЭТАЛОНА, ids=["код", "space=hq", "без-кода"])
@pytest.mark.parametrize("роль", ["admin", "auditor"])
@pytest.mark.parametrize("маршрут", sorted(ПРАВКИ))
def test_партнёр_не_меняет_эталон(
    склад: Store, клиент: Any, маршрут: str, роль: str, адрес: str
) -> None:
    код = _цель_маршрута(маршрут, "hq")
    путь, форма = _запрос(маршрут, склад, space="hq", code=код)
    до = снимок(склад.root, кроме="am")

    ответ = клиент(ПАРТНЁР, роль).post(
        путь + адрес.replace("{код}", код), data=форма, headers=ЗАГОЛОВКИ
    )

    assert снимок(склад.root, кроме="am") == до, f"{маршрут} {адрес}: партнёр изменил эталон УК"
    if роль == "auditor":
        assert ответ.status_code == 403
    elif адрес and not маршрут.startswith("/admin/checklists/") and маршрут != "/admin/bot/<code>":
        # Отказ назван словами, а не молчаливой пустой страницей.
        assert t("methodology.etalon_readonly", "ru") in ответ.get_data(as_text=True)


# --- 3. партнёр на чек-листе другого партнёра -----------------------------------


@pytest.mark.parametrize("адрес", ["?checklist=rnd", "?space=am&checklist=rnd"])
@pytest.mark.parametrize("маршрут", sorted(ПРАВКИ))
def test_партнёр_не_меняет_чек_лист_другого_партнёра(
    склад: Store, клиент: Any, маршрут: str, адрес: str
) -> None:
    путь, форма = _запрос(маршрут, склад, space="am", code="rnd")
    до = снимок(склад.root, кроме="ge")

    клиент(ДРУГОЙ, "admin").post(путь + адрес, data=форма, headers=ЗАГОЛОВКИ)

    assert снимок(склад.root, кроме="ge") == до, f"{маршрут} {адрес}: GE изменил чек-лист AM"


# --- заведение и указатель прода ---------------------------------------------------


@pytest.mark.parametrize("роль", ["admin", "auditor"])
def test_партнёр_не_заводит_чек_лист(склад: Store, клиент: Any, роль: str) -> None:
    """D283: заводит УК. Ни в эталоне, ни у себя — хранилище целиком прежнее."""
    до = снимок(склад.root)

    клиент(ПАРТНЁР, роль).post(
        "/admin/checklists", data=БЕЗ_КОНТРОЛЯ["/admin/checklists"], headers=ЗАГОЛОВКИ
    )

    assert снимок(склад.root) == до


@pytest.mark.parametrize("адрес", ["", "?space=hq", "?space=am"])
@pytest.mark.parametrize("код", ["rnd", "bizdev", "spare"])
def test_партнёр_не_двигает_указатель_прода(
    склад: Store, клиент: Any, код: str, адрес: str
) -> None:
    """Указатель один на всю сеть (D460): админ партнёра не применяет даже СВОЙ чек-лист."""
    до = снимок(склад.root)

    ответ = клиент(ПАРТНЁР, "admin").post(
        f"/admin/checklists/{код}/apply{адрес}", headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code in (403, 404)
    assert снимок(склад.root) == до


# --- экран: на чужом чек-листе нет кнопок, которые откажут --------------------------

#: Формы правки, которых на чужом чек-листе быть не должно (адрес действия формы).
#: Карточка пункта — форма с запертым `fieldset` и без кнопки записи: так экран
#: показывает пункт на чтение, её здесь нет.
ФОРМЫ_ПРАВКИ = (
    'action="/admin/items?',
    "/disable?",
    "/restore?",
    "data-mx-record",
    'action="/admin/zones',
    'action="/admin/route',
    'action="/admin/scoring',
    'action="/admin/publish',
    'action="/admin/checklists/bizdev/master',
    'action="/admin/checklists/rnd/master',
    'action="/admin/checklists"',
)

ЭКРАНЫ = [
    "",
    "&item=CLN01",
    "&new=1",
    "&panel=scoring",
    "&panel=versions",
    "&panel=new",
    "&diff=1",
]


@pytest.mark.parametrize("экран", ЭКРАНЫ)
@pytest.mark.parametrize(
    ("кто", "адрес"),
    [(ПАРТНЁР, "?checklist=bizdev"), (УК, "?space=am&checklist=rnd")],
    ids=["партнёр-на-эталоне", "ук-на-чек-листе-партнёра"],
)
def test_на_чужом_чек_листе_нет_форм_правки(
    склад: Store, клиент: Any, кто: str, адрес: str, экран: str
) -> None:
    страница = клиент(кто, "admin").get(f"/admin{адрес}{экран}").get_data(as_text=True)

    лишние = [форма for форма in ФОРМЫ_ПРАВКИ if форма in страница]
    assert not лишние, f"на чужом чек-листе показаны формы правки: {лишние}"
    if not экран:
        причина = "etalon" if кто == ПАРТНЁР else "foreign"
        assert t(f"methodology.{причина}.readonly.title", "ru") in страница


def test_на_своём_чек_листе_формы_правки_есть(склад: Store, клиент: Any) -> None:
    """Обратная сторона: скрытие не задело своё — иначе тест выше прошёл бы на пустом экране."""
    страница = клиент(ПАРТНЁР, "admin").get("/admin?checklist=rnd&item=CLN01")

    assert 'action="/admin/items/CLN01?' in страница.get_data(as_text=True)
    assert 'action="/admin/checklists/rnd/master' in страница.get_data(as_text=True)


def test_перечень_партнёру_без_форм_для_эталона_и_заведения(склад: Store, клиент: Any) -> None:
    страница = клиент(ПАРТНЁР, "admin").get("/admin/checklists").get_data(as_text=True)

    assert 'action="/admin/checklists/rnd/state"' in страница
    assert 'action="/admin/checklists/bizdev/state"' not in страница
    assert 'action="/admin/checklists/spare/state"' not in страница
    assert 'action="/admin/checklists"' not in страница


def test_перечень_сотруднику_партнёра_без_форм(склад: Store, клиент: Any) -> None:
    страница = клиент(ПАРТНЁР, "auditor").get("/admin/checklists").get_data(as_text=True)

    assert "/state" not in страница
    assert 'action="/admin/checklists"' not in страница


def test_панель_бота_сотруднику_партнёра_без_переключателей(склад: Store, клиент: Any) -> None:
    страница = клиент(ПАРТНЁР, "auditor").get("/admin?checklist=rnd&panel=bot")

    assert 'action="/admin/bot/' not in страница.get_data(as_text=True)
