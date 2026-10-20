"""F-003 (аудит 12.10): образ не работает от root, у сервисов отобраны привилегии.

Без docker: проверяется текст `Dockerfile` и разобранный `docker-compose.yml`.
Сборку и запуск образа проверяет CI/стенд, здесь — чтобы USER и `cap_drop`
не пропали молча при правке.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"

#: Сервисы на нашем образе (якорь `stand`).
OWN_IMAGE_SERVICES = ("bot", "mcp", "web", "walk", "demo", "demo-seed", "migrate", "state-backup")
VOLUME_DIRS = ("/app/state", "/app/frames", "/app/methodology")


def _instructions() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    text = re.sub(r"\\\n", " ", text)
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_dockerfile_drops_to_non_root_user_before_cmd() -> None:
    lines = _instructions()
    users = [i for i, ln in enumerate(lines) if ln.startswith("USER ")]
    assert users, "в Dockerfile нет USER: сервисы работают от root"
    last_user = lines[users[-1]].split()[1]
    assert last_user not in {"root", "0"}, f"последний USER — {last_user}: это root"
    cmd = next(i for i, ln in enumerate(lines) if ln.startswith("CMD "))
    assert users[-1] < cmd, "USER стоит после CMD"


def test_dockerfile_owns_volume_dirs_by_the_runtime_user() -> None:
    chown = " ".join(ln for ln in _instructions() if "chown" in ln)
    for d in VOLUME_DIRS:
        assert d in chown, f"{d} не отдан пользователю: новый том будет принадлежать root"


@pytest.fixture(scope="module")
def services() -> dict[str, dict]:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, _tag, node: loader.construct_scalar(node))
    return yaml.load(COMPOSE.read_text(encoding="utf-8"), Loader=Loader)["services"]  # noqa: S506


@pytest.mark.parametrize("name", OWN_IMAGE_SERVICES)
def test_service_drops_capabilities_and_new_privileges(
    services: dict[str, dict], name: str
) -> None:
    svc = services[name]
    assert svc.get("cap_drop") == ["ALL"], f"{name}: cap_drop: [ALL] не задан"
    assert "no-new-privileges:true" in (svc.get("security_opt") or []), (
        f"{name}: нет security_opt no-new-privileges"
    )
    assert "user" not in svc or str(svc["user"]) not in {"0", "root"}, f"{name}: user — root"


#: Все сервисы с потолком памяти и числа процессов (F-128): страховка от убегающего процесса.
LIMITED_SERVICES = (*OWN_IMAGE_SERVICES, "db", "storage", "link", "web-link", "tunnel")


@pytest.mark.parametrize("name", LIMITED_SERVICES)
def test_service_has_memory_and_pids_ceiling_but_no_cpu_throttle(
    services: dict[str, dict], name: str
) -> None:
    svc = services[name]
    assert svc.get("mem_limit"), f"{name}: нет mem_limit — убегающий процесс заберёт хост"
    assert svc.get("pids_limit"), f"{name}: нет pids_limit"
    assert "cpus" not in svc and "cpu_quota" not in svc, f"{name}: лимит по ЦП душит задержку"
