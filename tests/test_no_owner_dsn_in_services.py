"""F-002 (аудит 12.10): сервисы не держат владельца схемы.

`env_file` отдаёт контейнеру весь `.env`, а в нём `DATABASE_ADMIN_URL` — на проде
суперпользователь Postgres с обходом построчных политик. Сервис, смотрящий в
интернет, с такой переменной отдаёт всю базу при любой уязвимости исполнения
кода. Здесь два заслона, оба без базы и без docker:

* в `docker-compose.yml` у каждого сервиса, кроме одноразового `migrate`,
  `DATABASE_ADMIN_URL` переопределена пустой строкой (она перекрывает `env_file`);
* код пространств и учёток не берёт владельца сам: `spaces.py` ходит узкой
  ролью (`_managing`), а `_owned` не существует.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"
PROD_OVERLAY = ROOT / "docker-compose.prod.yml"
SRC = ROOT / "src"

OWNER_VAR = "DATABASE_ADMIN_URL"
#: Всё, что собирается якорем `stand` и тем самым получает `.env` целиком.
SERVICES_WITH_ENV_FILE = ("bot", "mcp", "web", "walk", "demo", "demo-seed", "state-backup")
#: Root-ключи хранилища кадров (D635): в `.env` ради `storage-live`, приложению не нужны.
FRAMES_ROOT_VARS = ("FRAMES_ROOT_USER", "FRAMES_ROOT_PASSWORD")
#: Единственный, кому владелец нужен: накат схемы.
MIGRATE = "migrate"

#: Модули `src/`, которым владелец законно нужен: накат, и сверка баз/запасное
#: подключение инструментов. Всё прочее в `src/` его не берёт.
MAY_READ_OWNER_DSN = {"db/migrate.py", "db/database_target.py", "db/recipe_audit.py"}


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader, терпящий теги Compose (`!override`, `!reset`) — значение берётся как есть."""


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, _tag, node: (
        loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_scalar(node)
    ),
)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)  # noqa: S506


@pytest.fixture(scope="module")
def services() -> dict[str, dict]:
    return _load(COMPOSE)["services"]


@pytest.mark.parametrize("name", SERVICES_WITH_ENV_FILE)
def test_service_does_not_receive_schema_owner(services: dict[str, dict], name: str) -> None:
    env = services[name].get("environment")
    assert isinstance(env, dict), f"{name}: environment должен быть словарём"
    assert OWNER_VAR in env and env[OWNER_VAR] == "", (
        f"{name}: {OWNER_VAR} должна быть переопределена пустой строкой, иначе её отдаст "
        f"env_file (вливайте `<<: *no-owner`)"
    )
    assert env.get("POSTGRES_PASSWORD") == "", f"{name}: пароль владельца базы не должен доезжать"


@pytest.mark.parametrize("name", (*SERVICES_WITH_ENV_FILE, MIGRATE))
def test_service_does_not_receive_frames_root_keys(services: dict[str, dict], name: str) -> None:
    env = services[name].get("environment")
    assert isinstance(env, dict), f"{name}: environment должен быть словарём"
    for var in FRAMES_ROOT_VARS:
        assert env.get(var) == "", (
            f"{name}: {var} должна быть переопределена пустой строкой, иначе её отдаст "
            f"env_file и у приложения окажется root хранилища кадров"
        )


def test_only_migrate_keeps_schema_owner(services: dict[str, dict]) -> None:
    migrate = services[MIGRATE]
    assert migrate["profiles"] == ["migrate"], "накат — отдельный профиль, `up -d` его не трогает"
    assert migrate["env_file"], "накат берёт .env целиком, и владелец приезжает оттуда"
    assert OWNER_VAR not in (migrate.get("environment") or {}), "migrate не обнуляет владельца"
    assert migrate["command"] == ["python", "-m", "src.db.migrate"]


def test_prod_overlay_does_not_reintroduce_owner() -> None:
    overlay = _load(PROD_OVERLAY)["services"]
    for name, svc in overlay.items():
        env = svc.get("environment") or {}
        assert OWNER_VAR not in env or env[OWNER_VAR] == "", f"{name}: надстройка вернула владельца"


def test_spaces_use_narrow_role_not_owner() -> None:
    text = (SRC / "db" / "spaces.py").read_text(encoding="utf-8")
    assert "_owned" not in text, "spaces.py ходит ролью администратора истории (_managing)"
    assert "admin_dsn" not in text and "DATABASE_ADMIN_URL_VAR" not in text
    assert len(re.findall(r"with _managing\(", text)) >= 5, (
        "каждая запись и чтение — через _managing"
    )
    assert not hasattr(__import__("src.db.web_access", fromlist=["x"]), "_owned"), (
        "_owned удалён: подключения владельца у веб-слоя быть не должно"
    )


def test_runtime_code_does_not_read_owner_dsn() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in MAY_READ_OWNER_DSN:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\badmin_dsn\b|DATABASE_ADMIN_URL_VAR", text):
            offenders.append(rel)
    assert not offenders, f"владельца схемы читают: {offenders}"
