"""#475: отказы раздела «Методика» — на языке интерфейса, и ни один не потерян.

Хранилище методики (`src/mcp`) отказывает по-русски — это язык MCP, его читает
агент партнёра. Веб берёт фразу по коду отказа (`refusal.<код>`) на языке
интерфейса. Свойства, чья ошибка молчит:

* отказ, которому завели код, но не завели текст, роняет экран пятисоткой
  (`t()` отказывает на незнакомом ключе) — ловится здесь, а не на показе;
* отказ без кода не падает, а тихо приходит английскому интерфейсу
  по-русски — поэтому каждый отказ хранилища обязан нести код;
* параметр, который фраза ждёт, а отказ не кладёт, — та же пятисотка.

Перечень кодов берётся из исходников (AST), а не из списка в тесте: список
в тесте разошёлся бы с кодом ровно так же, как разошёлся бы каталог.
"""

from __future__ import annotations

import ast
import re
import string
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.mcp.checklist import check_code
from src.mcp.checklist_layout import check_slug
from src.mcp.errors import ChecklistError
from src.web import methodology as method
from src.web.errors import MethodologyRefused
from src.web.texts import TEXTS, UI_LANGS

ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = ROOT / "src" / "mcp"
DOMAIN_STORE = ROOT / "src" / "domain" / "checklist_store.py"
WEB_DIR = ROOT / "src" / "web"

#: Модули, чьи отказы доходят до панели «Методики» и обязаны нести код (#475, #504).
#: Модули двери, до которых веб не доходит (фото-эталоны, подсказки, непокрытые
#: фразы, чтение проверок), здесь не названы: их отказы читает только агент.
CODED_MODULES = (
    MCP_DIR / "checklist.py",
    MCP_DIR / "checklists.py",
    MCP_DIR / "checklist_tools.py",
    MCP_DIR / "route.py",
    MCP_DIR / "checklist_layout.py",
    DOMAIN_STORE,
)
REFUSAL_TYPES = {"ChecklistError", "EngineNoVerdictError", "ChecklistStoreError"}

ТЕНАНТ = "default"


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _calls(path: Path) -> Iterator[ast.Call]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            yield node


def _param_names(call: ast.Call, where: str) -> frozenset[str]:
    params = _keyword(call, "params")
    if params is None:
        return frozenset()
    assert isinstance(params, ast.Dict), f"{where}: params отказа — не литерал словаря"
    names = set()
    for key in params.keys:
        assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
            f"{where}: ключ params — не строка"
        )
        names.add(key.value)
    return frozenset(names)


def _raised() -> dict[str, set[frozenset[str]]]:
    """Ключ текста → наборы параметров, с которыми его кладут в отказ."""
    found: dict[str, set[frozenset[str]]] = {}
    for path in [*sorted(MCP_DIR.glob("*.py")), DOMAIN_STORE]:
        for call in _calls(path):
            code = _keyword(call, "refusal")
            if isinstance(code, ast.Constant) and isinstance(code.value, str):
                where = f"{path.name}:{call.lineno}"
                found.setdefault(method.REFUSAL_PREFIX + code.value, set()).add(
                    _param_names(call, where)
                )
    for path in sorted(WEB_DIR.glob("*.py")):
        for call in _calls(path):
            if getattr(call.func, "id", None) != "MethodologyRefused":
                continue
            key = _keyword(call, "key")
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                where = f"{path.name}:{call.lineno}"
                found.setdefault(key.value, set()).add(_param_names(call, where))
    return found


def _placeholders(text: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(text) if name)


def test_codes_are_found_in_the_source() -> None:
    """Сторож самого сборщика: пустой перечень сделал бы проверки ниже зелёными."""
    raised = _raised()
    assert len([k for k in raised if not k.startswith("refusal.web.")]) >= 30, sorted(raised)
    assert "refusal.checklist_missing" in raised


def test_every_refusal_code_has_a_text_in_every_language() -> None:
    missing = [
        f"{key} [{lang}]"
        for key in sorted(_raised())
        for lang in UI_LANGS
        if not TEXTS.get(key, {}).get(lang, "").strip()
    ]
    assert not missing, f"коду отказа не заведён текст: {', '.join(missing)}"


def test_every_refusal_text_takes_exactly_the_parameters_of_the_refusal() -> None:
    wrong = []
    for key, sets in sorted(_raised().items()):
        for params in sets:
            for lang in UI_LANGS:
                wanted = _placeholders(TEXTS.get(key, {}).get(lang, ""))
                if wanted != params:
                    wrong.append(
                        f"{key} [{lang}]: текст ждёт {sorted(wanted)}, отказ кладёт "
                        f"{sorted(params)}"
                    )
    assert not wrong, "\n".join(wrong)


def test_rate_field_refusals_have_texts() -> None:
    """Ключ ставки собирается из имени поля — f-строкой, мимо сборщика выше."""
    source = (WEB_DIR / "methodology.py").read_text(encoding="utf-8")
    fields = re.findall(r'поле="([a-z_0-9]+)"', source)
    assert len(fields) == 4, fields
    for field in fields:
        for lang in UI_LANGS:
            assert TEXTS[f"refusal.web.rate_not_number.{field}"][lang].strip()


def test_every_store_refusal_carries_a_code() -> None:
    """Отказ без кода приходит английскому интерфейсу по-русски — тихо."""
    uncoded = [
        f"{path.name}:{call.lineno}"
        for path in CODED_MODULES
        for call in _calls(path)
        if getattr(call.func, "id", None) in REFUSAL_TYPES and _keyword(call, "refusal") is None
    ]
    assert not uncoded, f"отказ без кода: {', '.join(uncoded)}"


# --- поведение: MCP по-прежнему по-русски, веб — на языке интерфейса ---------------


def test_mcp_text_stays_russian_and_web_translates_by_code() -> None:
    with pytest.raises(ChecklistError) as caught:
        check_code("не код")
    отказ = caught.value

    assert "не похоже на код" in str(отказ), "текст MCP изменился — агенты читают его"
    assert отказ.refusal == "bad_code"
    веб = method._refusal(отказ)
    assert "does not look like a code" in method.refusal_text(веб, "en")
    assert "не похоже на код" in method.refusal_text(веб, "ru")
    assert "“не код”" in method.refusal_text(веб, "en"), "параметр отказа потерян"


def test_refusal_without_code_is_shown_as_is() -> None:
    assert method.refusal_text(MethodologyRefused("как есть"), "en") == "как есть"


# --- экран ---------------------------------------------------------------------------


@pytest.fixture
def клиент(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")  # D344
    методика = tmp_path / "живая-методика"
    build_edition(методика, name="imf", day="2026-09-01")
    monkeypatch.setenv(method.STORE_VAR, str(tmp_path / "хранилище"))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        войти(client)
        yield client


def _post(клиент: FlaskClient, path: str, data: dict[str, Any]) -> str:
    ответ = клиент.post(path, data=data, headers={"Origin": СВОЙ})
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def test_engine_refusal_comes_in_english_on_english_screen(клиент: FlaskClient) -> None:
    страница = _post(клиент, "/admin/items/CLN01?lang=en", {"levels": "D9"})

    assert "The engine said:" in страница, "отказ движка не переведён на английский экран"
    assert "Правка отклонена" not in страница
    assert "D9" in страница, "слова движка потеряны"


def test_engine_refusal_stays_russian_on_russian_screen(клиент: FlaskClient) -> None:
    страница = _post(клиент, "/admin/items/CLN01?lang=ru", {"levels": "D9"})

    assert "Правка отклонена, новой версии не появилось. Движок сказал:" in страница


def test_form_refusal_comes_in_english_on_english_screen(клиент: FlaskClient) -> None:
    страница = _post(клиент, "/admin/scoring?lang=en", {"d1": "abc"})

    assert "Rate D1 is “abc”, which is not a number." in страница
    assert "а это не число" not in страница


def test_domain_refusal_keeps_its_code_through_mcp() -> None:
    """Отказ яруса `domain` переводится в отказ MCP — код и параметры не теряются (#504)."""
    with pytest.raises(ChecklistError) as caught:
        check_slug("BAD!", что="Код чек-листа")
    отказ = caught.value

    assert "не годится" in str(отказ), "текст MCP изменился — агенты читают его"
    assert отказ.refusal == "bad_slug"
    assert "“BAD!” is not valid" in method.refusal_text(method._refusal(отказ), "en")
