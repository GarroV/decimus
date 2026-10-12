"""Карта кода и инвентарь не отстают от кода (#731).

Четыре вещи, на которые молчаливо разъезжается документация, и каждая здесь —
отдельная проверка с сообщением «что запустить»:

* файл кода есть, а в `docs/00-map.md` его нет;
* карта называет файл, которого уже нет;
* таблицы между маркерами не совпадают со свежей генерацией (забыли `make map`);
* код читает переменную окружения, которой нет в `.env.example`.

Базы не нужно. Проверки способны упасть: тесты ниже подсовывают им сломанный
вход (убранная строка, призрачный файл, новая переменная) и требуют отказа.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAP_DOC = ROOT / "docs" / "00-map.md"

#: Путь в обратных кавычках, который карта обязана держать живым.
_PATH_IN_DOC = re.compile(
    r"`((?:src|tools|scripts|engine|docs|tests|front|deploy)/[A-Za-z0-9_./-]+\.[a-z0-9]+)`"
)


def _load_gen_map() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_map", ROOT / "tools" / "gen_map.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_map"] = module
    spec.loader.exec_module(module)
    return module


gen_map = _load_gen_map()


def files_missing_from_map(text: str) -> list[str]:
    """Файл назван, только если у него есть своя строка таблицы, а не упоминание в тексте."""
    return [
        rel for rel in (gen_map._rel(p) for p in gen_map.map_files()) if f"| `{rel}` |" not in text
    ]


def ghost_files_in(text: str) -> list[str]:
    return sorted({p for p in _PATH_IN_DOC.findall(text) if not (ROOT / p).exists()})


def first_difference(old: str, new: str) -> str:
    for number, (left, right) in enumerate(zip(old.split("\n"), new.split("\n"), strict=False), 1):
        if left != right:
            return f"строка {number}: в документе «{left[:90]}», по коду «{right[:90]}»"
    return "документ короче или длиннее свежей генерации"


def undocumented_env(reads: dict[str, list[str]], documented: set[str], allowed: dict[str, str]):
    return sorted(name for name in reads if name not in documented and name not in allowed)


# --- карта называет каждый файл -------------------------------------------------


def test_every_code_file_is_named_in_the_map() -> None:
    missing = files_missing_from_map(MAP_DOC.read_text(encoding="utf-8"))
    assert not missing, (
        "Файлов кода нет в docs/00-map.md: "
        + ", ".join(missing)
        + ". Впишите каждый в подходящий маркер `<!-- map:begin files … -->` "
        "(перечень или глоб) и запустите `make map`."
    )


def test_map_check_fails_when_a_row_is_removed() -> None:
    text = MAP_DOC.read_text(encoding="utf-8")
    victim = "src/web/auth.py"
    broken = "\n".join(line for line in text.split("\n") if f"`{victim}`" not in line)
    assert broken != text, "порча не применилась: строки файла в карте нет"
    assert victim in files_missing_from_map(broken)


# --- карта не называет призраков -------------------------------------------------


def test_map_names_no_file_that_does_not_exist() -> None:
    ghosts = ghost_files_in(MAP_DOC.read_text(encoding="utf-8"))
    assert not ghosts, (
        "docs/00-map.md называет файлы, которых нет: "
        + ", ".join(ghosts)
        + ". Файл переименовали или удалили — поправьте текст вокруг таблиц; "
        "строки в таблицах пересоберёт `make map`."
    )


def test_ghost_check_fails_on_a_removed_file() -> None:
    text = MAP_DOC.read_text(encoding="utf-8") + "\nСм. `src/web/no_such_module.py`.\n"
    assert ghost_files_in(text) == ["src/web/no_such_module.py"]


def test_generator_refuses_a_marker_that_points_at_a_missing_file() -> None:
    broken = "<!-- map:begin files src/web/no_such_module.py -->\n<!-- map:end -->\n"
    with pytest.raises(gen_map.MapError, match="no_such_module"):
        gen_map.render(broken)


# --- таблицы свежие --------------------------------------------------------------


@pytest.mark.parametrize("path", gen_map.TARGETS, ids=lambda p: p.name)
def test_generated_sections_match_the_code(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        fresh = gen_map.render(text)
    except gen_map.MapError as exc:
        pytest.fail(f"{path.name}: маркер не разбирается — {exc}")
    assert fresh == text, (
        f"{path.relative_to(ROOT)}: таблицы между маркерами отстали от кода "
        f"({first_difference(text, fresh)}). Запустите `make map` и закоммитьте результат."
    )


def test_stale_table_is_detected() -> None:
    text = (ROOT / "docs" / "inventory.md").read_text(encoding="utf-8")
    broken = text.replace("| `make map` |", "| `make nothing` |", 1)
    assert broken != text, "порча не применилась: строки `make map` в инвентаре нет"
    assert gen_map.render(broken) != broken


@pytest.mark.parametrize(
    ("path", "kinds"),
    [
        (MAP_DOC, ("files", "migrations", "tree")),
        (ROOT / "docs" / "inventory.md", ("routes", "mcp", "env", "tables", "make")),
        (ROOT / "docs" / "12-web-admin.md", ("toc",)),
        (ROOT / "docs" / "08-deploy.md", ("toc",)),
    ],
    ids=lambda v: v.name if isinstance(v, Path) else "kinds",
)
def test_documents_keep_their_markers(path: Path, kinds: tuple[str, ...]) -> None:
    """Убрать маркер — способ обойти свежесть таблицы, поэтому их наличие тоже проверяется."""
    text = path.read_text(encoding="utf-8")
    absent = [kind for kind in kinds if f"<!-- map:begin {kind}" not in text]
    assert not absent, f"{path.name}: нет маркеров {absent} — верните их, см. tools/gen_map.py"


# --- переменные окружения ---------------------------------------------------------


def test_every_env_var_read_in_code_is_in_env_example() -> None:
    missing = undocumented_env(
        gen_map.env_reads(), gen_map.env_example_names(), gen_map.ENV_ALLOWLIST
    )
    assert not missing, (
        "Код читает переменные, которых нет в .env.example: "
        + ", ".join(missing)
        + ". Впишите каждую в .env.example с комментарием (смысл, умолчание, без "
        "настоящих значений) и запустите `make map`. Если переменную задаёт сам код, "
        "а не оператор, — запись с причиной в ENV_ALLOWLIST (tools/gen_map.py)."
    )


def test_env_check_fails_on_a_new_variable() -> None:
    reads = {**gen_map.env_reads(), "BRAND_NEW_KNOB": ["src/x.py"]}
    assert undocumented_env(reads, gen_map.env_example_names(), gen_map.ENV_ALLOWLIST) == [
        "BRAND_NEW_KNOB"
    ]


def test_env_scan_sees_a_variable_read_through_a_name_constant() -> None:
    import ast

    tree = ast.parse(
        'POOL_VAR = "SOME_POOL_KNOB"\nvalue = src.get(POOL_VAR)\nraw = os.environ["OTHER_KNOB"]\n'
    )
    assert gen_map._env_names_in(tree) == {"SOME_POOL_KNOB", "OTHER_KNOB"}


def test_env_allowlist_is_honest() -> None:
    """Запись без причины или про переменную, которую код больше не читает, — мусор."""
    reads = gen_map.env_reads()
    for name, reason in gen_map.ENV_ALLOWLIST.items():
        assert len(reason) >= 20, f"ENV_ALLOWLIST[{name}]: причина не названа по-человечески"
        assert name in reads, (
            f"ENV_ALLOWLIST[{name}]: код эту переменную больше не читает — уберите"
        )
        assert name not in gen_map.env_example_names(), (
            f"ENV_ALLOWLIST[{name}]: переменная уже в .env.example — запись лишняя"
        )
