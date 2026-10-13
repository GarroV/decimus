"""Порча матрицы прав (D408): каждая сломанная защита обязана уронить свой тест.

Запуск: `.venv/bin/python tools/porcha_permissions.py` из корня репозитория
(`make porcha-permissions`). Каждый случай подменяет одну строку кода, гоняет
ровно её тест и возвращает файл на место. «НЕ ПРИМЕНИЛАСЬ» — код уехал, и порчу
надо обновить: молча зелёный прогон без подмены и есть та ложь, ради которой
скрипт заведён. Базы тестам не нужно.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`): порча того же размера в ту же
секунду подхватила бы кэш, и тест «поймал» бы исправный код.
"""

import os
import pathlib
import subprocess
import sys

T = "tests/"
cases = [
    # Слой 1: граница пространств сильнее матрицы.
    (
        "src/domain/permissions.py",
        "    if действие.hq_only:\n        return RULE_HQ_ONLY\n",
        "",
        T + "test_permissions_table.py::test_граница_держит_даже_сломанную_матрицу",
    ),
    (
        "src/domain/permissions.py",
        "        if действие.own_space and not своё:\n",
        "        if False:\n",
        T + "test_permissions_can.py::test_проверки_и_письма_УК_только_в_своём_пространстве",
    ),
    # Слой 2: лишняя клетка у гостя.
    (
        "src/domain/permissions.py",
        '        "inspection.read",\n        "ratings.read",\n        "view.overview",\n',
        '        "inspection.read",\n        "ratings.read",\n        "people.manage",\n'
        '        "view.overview",\n',
        T + "test_permissions_table.py::test_каждая_клетка_матрицы",
    ),
    # Закрытое в Claude.
    (
        "src/domain/permissions.py",
        "    if action in CLAUDE_CLOSED.get(сторона, frozenset()):\n",
        "    if False:\n",
        T + "test_permissions_can.py::test_claude_снятие_закрыто_всем_методика_партнёру",
    ),
    # D460: методика админа партнёра в Claude — своё пространство, не больше.
    (
        "src/domain/permissions.py",
        '    SIDE_PARTNER: _codes("inspection.retract", "checklist.apply"),\n',
        '    SIDE_PARTNER: _codes("inspection.retract"),\n',
        T + "test_permissions_can.py::test_claude_снятие_закрыто_всем_методика_партнёру",
    ),
    (
        "src/domain/permissions.py",
        '    (SIDE_PARTNER, "auditor"): _CHECKLISTS,\n',
        "",
        T + "test_mcp_partner_methodology.py::test_сотруднику_партнёра_методика_не_видна",
    ),
    (
        "src/mcp/config.py",
        '            and claude_may(role, tenant, "checklist.edit")\n',
        "            and True\n",
        T + "test_mcp_partner_methodology.py::test_хранилище_партнёру_даёт_роль_а_не_список_env",
    ),
    (
        "src/mcp/rpc.py",
        "    свой = replace(база, space=space_of(tenant))\n",
        "    свой = replace(база, space=DEFAULT_SPACE)\n",
        T
        + "test_mcp_partner_methodology.py::test_админ_партнёра_правит_свой_чек_лист_в_своём_пространстве",  # noqa: E501
    ),
    # Веб: запрет по умолчанию, полнота, разделы, забытый `permit`.
    (
        "src/web/guard.py",
        "        if not коды:\n",
        "        if False:\n",
        T + "test_web_guard.py::test_маршрут_без_кода_закрыт_запретом_по_умолчанию",
    ),
    (
        "src/web/guard.py",
        "            непокрытые.append(",
        "            (lambda *_: None)(",
        T + "test_web_guard.py::test_полнота_ловит_маршрут_без_кода",
    ),
    (
        "src/web/users_screen.py",
        '    @guard.action("people.role")\n',
        "",
        T + "test_web_guard.py::test_каждый_пишущий_маршрут_объявил_действие",
    ),
    (
        "src/web/guard.py",
        "            if код is not None and not can(current_actor(), код).allowed:\n",
        "            if False:\n",
        T + "test_web_guard.py::test_разделы_по_матрице",
    ),
    (
        "src/web/guard.py",
        "        if response.status_code >= 400 or getattr(g, _PERMITTED, False):\n",
        "        if True:\n",
        T + "test_web_guard.py::test_маршрут_с_объектом_обязан_спросить_матрицу",
    ),
    # MCP: инструмент указателя прода у девелопера.
    (
        "src/mcp/policy.py",
        '    "apply_checklist": "checklist.apply",\n',
        "",
        T + "test_mcp_policy.py::test_девелоперу_указатель_прода_отказом_словами",
    ),
    # Бот: команда без действия и вход не по полю.
    (
        "src/bot/access.py",
        '    "stops": "refusals.read",\n',
        "",
        T + "test_bot_command_actions.py::test_каждая_команда_бота_сведена_к_действию",
    ),
    (
        "src/bot/access.py",
        'FIELD_ACTION = "inspection.conduct"\n',
        'FIELD_ACTION = "inspection.read"\n',
        T + "test_bot_command_actions.py::test_вход_в_бота_по_матрице",
    ),
]

bad = 0
for path, old, new, test in cases:
    p = pathlib.Path(path)
    orig = p.read_text(encoding="utf-8")
    if old not in orig:
        print("НЕ ПРИМЕНИЛАСЬ:", path, repr(old[:60]))
        bad += 1
        continue
    p.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run(  # noqa: S603 — свой pytest и свои пути из списка выше
            [".venv/bin/pytest", "-q", "-x", "-o", "addopts=", "-p", "no:cacheprovider", test],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
    finally:
        p.write_text(orig, encoding="utf-8")
    ok = r.returncode != 0
    line = [row for row in r.stdout.splitlines() if row.startswith("E ")][:1]
    print(
        ("ЛОВИТ " if ok else "НЕ ЛОВИТ ") + test.split("::")[1],
        "|",
        (line[0][:110] if line else ""),
    )
    bad += 0 if ok else 1
sys.exit(1 if bad else 0)
