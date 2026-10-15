"""Фронт на Cloudflare Worker: маршрутизация статики в кэш (#698).

Логика Worker'а проверяется `node --test` без среды Workers; шаблон конфига —
что кэш включён только у точки входа статики, а у «default» выключен: страницы
под логином в кэш Worker'а попасть не должны.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

FRONT = Path(__file__).resolve().parent.parent / "front"


def test_маршрутизация_фронта_проходит_node_test() -> None:
    node = shutil.which("node")
    assert node, "нужен node: без него маршрутизация фронта не проверена"

    done = subprocess.run(  # noqa: S603 - свой скрипт, путь к node из PATH
        [node, "--test", "front/test/proxy.test.mjs"],
        cwd=FRONT.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]


def _template(name: str) -> dict:
    text = (FRONT / f"wrangler.{name}.template.jsonc").read_text(encoding="utf-8")
    return json.loads("\n".join(re.sub(r"^\s*//.*$", "", line) for line in text.splitlines()))


def test_кэш_включён_только_у_точки_входа_статики() -> None:
    admin = _template("admin")

    assert admin["vars"]["STATIC_CACHE"] == "1"
    assert admin["exports"]["StaticCache"]["cache"]["enabled"] is True
    assert admin["exports"]["default"]["cache"]["enabled"] is False


def test_у_mcp_и_стенда_статика_идёт_прежним_путём() -> None:
    for name in ("mcp", "stand"):
        config = _template(name)
        assert "STATIC_CACHE" not in config.get("vars", {})
        assert "cache" not in config
