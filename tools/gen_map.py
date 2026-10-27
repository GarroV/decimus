"""Карта кода: перегенерация таблиц в docs/ между маркерами (`make map`, #731).

Руками пишутся только роли пакетов и таблица «по задаче → куда идти»; всё, что
зеркалит код (файл и первая фраза его докстринга, маршруты, инструменты MCP,
переменные окружения, миграции, цели Makefile, оглавления), собирает этот
скрипт. Маркеры в документе:

    <!-- map:begin files src/web/auth*.py src/web/accounts.py -->
    ...генерируется, руками не править...
    <!-- map:end -->

Виды таблиц: `files <глоб>...`, `tree <каталог>`, `migrations`, `tables`,
`routes`, `mcp`, `env`, `make`, `toc`. Порядок везде детерминирован, поэтому
`tests/test_docs_map.py` сравнивает документ со свежей генерацией дословно.

    python tools/gen_map.py           # переписать документы
    python tools/gen_map.py --check   # только проверить, код возврата 1 при расхождении
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from unittest import mock


class MapError(Exception):
    """Маркер в документе не разобрать или он ведёт в несуществующее: чинится правкой документа."""


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Документы с маркерами. Новый документ с таблицами — вписать сюда.
TARGETS: tuple[Path, ...] = (
    DOCS / "00-map.md",
    DOCS / "inventory.md",
    DOCS / "08-deploy.md",
    DOCS / "12-web-admin.md",
)

#: Что карта обязана перечислить: каталоги и расширения файлов кода.
MAP_ROOTS = ("src", "tools", "scripts", "engine")
MAP_SUFFIXES = (".py", ".sh", ".ps1")

#: Переменные, которые код читает, но в `.env.example` им не место, — с причиной.
#: Новая запись без причины — не запись: тест требует понятной строки.
ENV_ALLOWLIST: dict[str, str] = {
    "CHECKLIST_DIR": "подставляется кодом в окружение подпроцесса движка (src/domain/engine.py)",
    "INSPECTION_FILE": "подставляется кодом в окружение подпроцесса движка (src/domain/engine.py)",
    "WALK_MOCKUP_ZONES": "ручной рычаг сборки макета (tools/walk_mockup/build.py), не настройка",
}

BEGIN_RE = re.compile(r"^<!-- map:begin (.+?) -->\s*$")
END_LINE = "<!-- map:end -->"

SENTENCE_LIMIT = 170
ENV_FILES_SHOWN = 3
GENERATED_NOTE = "<!-- сгенерировано `make map` (tools/gen_map.py), руками не править -->"

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_ENV_RECEIVERS = frozenset({"environ", "src", "env", "source", "environment", "mapping"})
_ENV_CONST_RE = re.compile(r"(_VAR|_VARS|_ENV|_ENVVAR|_ENV_VAR)$")
_ENV_EXAMPLE_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]{2,})=", re.MULTILINE)


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _cell(text: str) -> str:
    """Текст в ячейку таблицы: без переводов строки и без неэкранированной черты."""
    return " ".join(text.split()).replace("|", "\\|")


def first_sentence(text: str, limit: int = SENTENCE_LIMIT) -> str:
    """Первая фраза первого абзаца: до точки с пробелом или до предела по слову."""
    paragraph = " ".join(text.strip().split("\n\n", 1)[0].split())
    cut = re.search(r"\.(\s|$)", paragraph)
    sentence = paragraph[: cut.start()] if cut else paragraph
    if len(sentence) > limit:
        sentence = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return sentence


def _py_doc(path: Path) -> str:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    return first_sentence(doc) if doc else "(нет докстринга)"


def _script_doc(path: Path) -> str:
    """Первый абзац комментария в голове скрипта (shell, PowerShell)."""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("#!"):
            continue
        if not line.startswith("#"):
            if lines or line:
                break
            continue
        body = line.lstrip("#").strip()
        if not body:
            if lines:
                break
            continue
        lines.append(body)
    return first_sentence(" ".join(lines)) if lines else "(нет комментария)"


def describe_file(path: Path) -> str:
    return _py_doc(path) if path.suffix == ".py" else _script_doc(path)


def table(header: tuple[str, ...], rows: Iterable[tuple[str, ...]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return out


def _tracked(base: Path) -> list[Path]:
    """Файлы под `base`, которые знает git: карта описывает репозиторий, а не рабочее
    дерево. Иначе неотслеживаемые остатки (`front/wrangler.admin.temp` после выкладки)
    попадали в таблицу у того, кто запустил `make map`, и main краснел у всех."""
    out = subprocess.run(  # noqa: S603 — свой git и свой путь, ввода извне нет
        ["git", "ls-files", "-z", "--", base.relative_to(ROOT).as_posix()],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted(ROOT / name for name in out.split("\0") if name)


def map_files() -> list[Path]:
    """Все файлы, которые карта обязана назвать: код в src/, tools/, scripts/, engine/."""
    found: list[Path] = []
    for top in MAP_ROOTS:
        for path in _tracked(ROOT / top):
            if path.suffix not in MAP_SUFFIXES or path.name == "__init__.py":
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            found.append(path)
    return found


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------


def _expand_braces(pattern: str) -> list[str]:
    """`src/db/{a,b}.py` → `src/db/a.py`, `src/db/b.py` (pathlib скобки не знает)."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [r for part in match.group(1).split(",") for r in _expand_braces(head + part + tail)]


def gen_files(args: list[str]) -> list[str]:
    paths: set[Path] = set()
    for pattern in args:
        for single in _expand_braces(pattern):
            found = [p for p in ROOT.glob(single) if p.is_file() and p.name != "__init__.py"]
            if not found:
                raise MapError(f"map:files {single} — файла нет: поправьте маркер в документе")
            paths.update(found)
    if not paths:
        raise MapError(f"map:files {' '.join(args)} — ни одного файла: поправьте глоб в маркере")
    rows = [(f"`{_rel(p)}`", _cell(describe_file(p))) for p in sorted(paths)]
    return table(("Файл", "Что делает"), rows)


def gen_tree(args: list[str]) -> list[str]:
    base = ROOT / args[0]
    groups: dict[str, list[str]] = defaultdict(list)
    for path in _tracked(base):
        if path.is_file():
            groups[path.parent.relative_to(base).as_posix()].append(path.name)
    rows = []
    for folder in sorted(groups):
        names = groups[folder]
        shown = ", ".join(names[:8]) + (f", … (+{len(names) - 8})" if len(names) > 8 else "")
        label = f"{args[0]}/" if folder == "." else f"{args[0]}/{folder}/"
        rows.append((f"`{label}`", str(len(names)), _cell(shown)))
    return table(("Каталог", "Файлов", "Какие"), rows)


def _migration_files() -> list[Path]:
    return sorted((ROOT / "src/db/migrations").glob("*.sql"))


def _migration_summary(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[1:]:
        if not raw.startswith("--"):
            break
        body = raw[2:].strip()
        if not body:
            if lines:
                break
            continue
        lines.append(body)
    return first_sentence(" ".join(lines)) if lines else "(нет описания)"


def gen_migrations(_args: list[str]) -> list[str]:
    rows = [(f"`{p.name}`", _cell(_migration_summary(p))) for p in _migration_files()]
    return table(("Миграция", "Что заводит"), rows)


_CREATE_TABLE_RE = re.compile(
    r"^\s*create\s+(?:unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.\"]*)",
    re.IGNORECASE | re.MULTILINE,
)


def gen_tables(_args: list[str]) -> list[str]:
    rows = []
    for path in _migration_files():
        names = _CREATE_TABLE_RE.findall(path.read_text(encoding="utf-8"))
        shown = ", ".join(f"`{n.replace(chr(34), '')}`" for n in names) if names else "—"
        rows.append((f"`{path.name}`", shown))
    return table(("Миграция", "Новые таблицы"), rows)


def _unwrapped_file(view: Callable[..., Any]) -> str:
    try:
        source = inspect.getsourcefile(inspect.unwrap(view))
    except TypeError:
        source = None
    if source is None:
        return "—"
    path = Path(source).resolve()
    # Окружение внутри дерева (worktree с `.venv`) — тоже библиотека, а не код (#850).
    inside = path.is_relative_to(ROOT) and not {".venv", "site-packages"} & set(path.parts)
    return _rel(path) if inside else "(библиотека)"


def _routes_of(app: Any) -> list[tuple[str, ...]]:
    rows = []
    for rule in app.url_map.iter_rules():
        methods = ", ".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        view = app.view_functions[rule.endpoint]
        rows.append((rule.rule, methods, rule.endpoint, _unwrapped_file(view)))
    rows.sort()
    return [(f"`{r[0]}`", r[1], f"`{r[2]}`", f"`{r[3]}`" if r[3][0] != "(" else r[3]) for r in rows]


def gen_routes(_args: list[str]) -> list[str]:
    """Маршруты из `url_map` настоящих приложений, собранных на минимальном окружении."""
    from src.web import walk_app
    from src.web.app import create_app
    from src.web.config import Settings

    settings = Settings(
        host="127.0.0.1",
        port=8080,
        tenant="HQ",
        ui_lang="ru",
        secret_key="map-only",  # noqa: S106 — заглушка для сборки карты, не секрет
        walk_upstream="http://walk.invalid:8081",
        admin_public_url="https://admin.invalid",
        mcp_public_url="https://mcp.invalid",
    )
    # Чистое окружение: состав маршрутов не должен зависеть от того, на чьей машине идёт сборка.
    with mock.patch.dict(os.environ, {}, clear=True):
        admin = create_app(settings)
        walk = walk_app.create_walk_app(settings)
    out: list[str] = []
    for title, app in (
        ("Админка (`src/web/app.py: create_app`)", admin),
        ("Мини-апп обхода (`src/web/walk_app.py: create_walk_app`)", walk),
    ):
        rows = _routes_of(app)
        out += [f"**{title}** — {len(rows)} маршрутов", ""]
        out += table(("Путь", "Методы", "Endpoint", "Файл"), rows)
        out.append("")
    return out[:-1]


def gen_mcp(_args: list[str]) -> list[str]:
    from src.mcp.annotations import TOOL_CLASSES
    from src.mcp.catalogue import TOOLS

    specs = sorted(TOOLS, key=lambda t: (t.kind, t.name))
    by_kind: dict[str, int] = defaultdict(int)
    for spec in specs:
        by_kind[spec.kind] += 1
    summary = ", ".join(f"{kind} — {count}" for kind, count in sorted(by_kind.items()))
    rows = [
        (
            f"`{s.name}`",
            s.kind,
            TOOL_CLASSES[s.name].kind,
            _cell(first_sentence(s.description, 120)),
            f"`{_unwrapped_file(s.handler)}`",
        )
        for s in specs
    ]
    return [
        f"Всего **{len(specs)}** инструментов ({summary}).",
        "",
        *table(
            ("Инструмент", "Вид", "Класс", "Что делает (описание для агента)", "Обработчик"), rows
        ),
    ]


# --- переменные окружения -------------------------------------------------


def _is_env_receiver(node: ast.expr) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id in _ENV_RECEIVERS


def _name_constants(tree: ast.AST) -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if isinstance(node, ast.Assign) and isinstance(value, ast.Tuple | ast.List):
            # `URL_VARS = ("A", "B")`: перечень имён, из которых читается первое заданное.
            for target in node.targets:
                if isinstance(target, ast.Name) and _ENV_CONST_RE.search(target.id):
                    for i, item in enumerate(value.elts):
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            if _NAME_RE.match(item.value):
                                consts[f"{target.id}[{i}]"] = item.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        if not _NAME_RE.match(value.value):
            continue
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        else:
            continue
        for target in targets:
            consts[target.id] = value.value
    return consts


def _env_names_in(tree: ast.AST) -> set[str]:
    consts = _name_constants(tree)

    def resolve(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value if _NAME_RE.match(node.value) else None
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        return None

    names = {value for key, value in consts.items() if _ENV_CONST_RE.search(key.split("[")[0])}
    for node in ast.walk(tree):
        arg: ast.expr | None = None
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"get", "pop", "setdefault"}:
                if _is_env_receiver(func.value):
                    arg = node.args[0]
            elif isinstance(func, ast.Attribute) and func.attr == "getenv":
                arg = node.args[0]
            elif isinstance(func, ast.Name) and func.id == "getenv":
                arg = node.args[0]
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_env_receiver(node.value)
        ):
            arg = node.slice
        resolved = resolve(arg) if arg is not None else None
        if resolved:
            names.add(resolved)
    return names


def env_reads() -> dict[str, list[str]]:
    """Какие переменные окружения читает код и в каких файлах (по AST, не по регулярке)."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in map_files():
        if path.suffix != ".py":
            continue
        for name in _env_names_in(ast.parse(path.read_text(encoding="utf-8"))):
            found[name].add(_rel(path))
    return {name: sorted(files) for name, files in sorted(found.items())}


def env_example_names() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(_ENV_EXAMPLE_RE.findall(text))


def gen_env(_args: list[str]) -> list[str]:
    documented = env_example_names()
    rows = []
    for name, files in env_reads().items():
        shown = ", ".join(f"`{f}`" for f in files[:ENV_FILES_SHOWN])
        if len(files) > ENV_FILES_SHOWN:
            shown += f" и ещё {len(files) - ENV_FILES_SHOWN}"
        if name in documented:
            status = "да"
        elif name in ENV_ALLOWLIST:
            status = _cell(f"нет — {ENV_ALLOWLIST[name]}")
        else:
            status = "**нет**"
        rows.append((f"`{name}`", shown, status))
    return table(("Переменная", "Где читается", "В `.env.example`"), rows)


# --- Makefile ---------------------------------------------------------------

_TARGET_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*):(?!=)(?:\s+(.*))?$")


def make_targets() -> list[tuple[str, str]]:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    result: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        match = _TARGET_RE.match(line)
        if not match:
            continue
        rest = match.group(2) or ""
        if rest.startswith("export "):  # `цель: export VAR = ...` — не объявление цели
            continue
        inline = rest.split("##", 1)[1].strip() if "##" in rest else ""
        if inline:
            result.append((match.group(1), inline))
            continue
        block: list[str] = []
        back = index - 1
        while back >= 0 and lines[back].startswith("#"):
            block.insert(0, lines[back].lstrip("#").strip())
            back -= 1
        result.append(
            (match.group(1), first_sentence(" ".join(b for b in block if b)) if block else "—")
        )
    return sorted(result)


def gen_make(_args: list[str]) -> list[str]:
    return table(
        ("Цель", "Что делает (по комментарию в Makefile)"),
        [(f"`make {n}`", _cell(d)) for n, d in make_targets()],
    )


# --- оглавление -------------------------------------------------------------


def slug(heading: str, seen: dict[str, int]) -> str:
    """Якорь заголовка так, как его строит GitHub."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text).replace(" ", "-")
    count = seen.get(text, 0)
    seen[text] = count + 1
    return text if count == 0 else f"{text}-{count}"


def gen_toc(_args: list[str], *, text: str = "") -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence or not line.startswith("## "):
            continue
        title = line[3:].strip()
        out.append(f"- [{title}](#{slug(title, seen)})")
    return out


# ---------------------------------------------------------------------------
# Подстановка в документ
# ---------------------------------------------------------------------------

GENERATORS: dict[str, Callable[[list[str]], list[str]]] = {
    "files": gen_files,
    "tree": gen_tree,
    "migrations": gen_migrations,
    "tables": gen_tables,
    "routes": gen_routes,
    "mcp": gen_mcp,
    "env": gen_env,
    "make": gen_make,
}


def _generate(spec: str, document: str) -> list[str]:
    kind, *args = spec.split()
    if kind == "toc":
        return gen_toc(args, text=document)
    if kind not in GENERATORS:
        raise MapError(f"map:begin {spec} — неизвестный вид таблицы «{kind}»")
    return GENERATORS[kind](args)


def render(text: str) -> str:
    """Документ со свежими таблицами между маркерами; всё остальное — как было."""
    out: list[str] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        match = BEGIN_RE.match(line)
        index += 1
        if not match:
            continue
        end = index
        while end < len(lines) and lines[end] != END_LINE:
            end += 1
        if end == len(lines):
            raise MapError(f"маркер «{line}» без закрывающего «{END_LINE}»")
        out.extend(_generate(match.group(1), text))
        index = end
    return "\n".join(out)


def stale_documents() -> list[Path]:
    """Документы, чьи таблицы отстали от кода."""
    return [
        p for p in TARGETS if p.read_text(encoding="utf-8") != render(p.read_text(encoding="utf-8"))
    ]


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    check = "--check" in argv
    try:
        stale = stale_documents()
    except MapError as exc:
        print(f"карта не собирается: {exc}")
        return 2
    if check:
        for path in stale:
            print(f"отстал от кода: {_rel(path)} — запустите `make map`")
        return 1 if stale else 0
    for path in stale:
        path.write_text(render(path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"обновлён {_rel(path)}")
    if not stale:
        print("таблицы актуальны")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
