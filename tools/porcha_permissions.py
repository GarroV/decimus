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
        '    "inspection.read",\n    "ratings.read",\n    "view.overview",\n',
        '    "inspection.read",\n    "ratings.read",\n    "people.manage",\n    "view.overview",\n',
        T + "test_permissions_table.py::test_каждая_клетка_матрицы",
    ),
    # D599: ОСБ — не больше, чем предписания; админ ведёт ничего; девелопер без страницы ОСБ.
    (
        "src/domain/permissions.py",
        '| _codes("prescription.request", "prescription.manage", "view.osb", "contract.manage"),',
        '| _codes("prescription.request", "prescription.manage", "view.osb", "contract.manage", '
        '"people.manage"),',
        T
        + "test_permissions_osb.py::test_осб_не_пишет_в_проверки_и_вообще_ничего_кроме_предписаний",
    ),
    (
        "src/domain/permissions.py",
        '    (SIDE_HQ, "admin"): _HQ_ADMIN,\n',
        '    (SIDE_HQ, "admin"): _HQ_ADMIN | _codes("prescription.manage"),\n',
        T + "test_permissions_osb.py::test_вести_предписание_могут_только_осб_и_главный_админ",
    ),
    (
        "src/domain/permissions.py",
        '_ALL_VIEWS_HQ = frozenset(a.code for a in _VIEWS if a.code != "view.osb")',
        "_ALL_VIEWS_HQ = frozenset(a.code for a in _VIEWS)",
        T + "test_permissions_osb.py::test_страницу_осб_видят_осб_админ_и_главный_админ",
    ),
    # Закрытое в Claude.
    (
        "src/domain/permissions.py",
        "    if action in CLAUDE_CLOSED.get(side_of(tenant), frozenset()):\n",
        "    if False:\n",
        T + "test_permissions_can.py::test_claude_снятие_закрыто_всем_методика_партнёру",
    ),
    # D460: методика партнёра в Claude — как в вебе, не больше.
    (
        "src/domain/permissions.py",
        '    | _codes("checklist.master")\n',
        "    | _CHECKLIST_OWNER\n",
        T + "test_permissions_table.py::test_каждая_клетка_матрицы",
    ),
    (
        "src/domain/permissions.py",
        '    "checklist.read",\n    "ratings.read",\n    "trip.own",\n)\n',
        '    "checklist.read",\n    "checklist.edit",\n    "ratings.read",\n    "trip.own",\n)\n',
        T + "test_mcp_policy.py::test_сотруднику_партнёра_в_claude_методика_только_на_чтение",
    ),
    (
        "src/mcp/config.py",
        '            and claude_may(role, tenant, "checklist.read")\n        )\n\n    def tenant_for',  # noqa: E501
        "            and False\n        )\n\n    def tenant_for",
        T + "test_mcp_partner_methodology.py::test_админ_партнёра_читает_эталон_но_не_правит_его",
    ),
    (
        "src/mcp/config.py",
        '            and claude_may(role, tenant, "checklist.read")\n        )\n\n    def may_read_checklist',  # noqa: E501
        "            and False\n        )\n\n    def may_read_checklist",
        T + "test_mcp_partner_methodology.py::test_хранилище_партнёру_даёт_роль_а_не_список_env",
    ),
    (
        "src/mcp/rpc.py",
        "    свой = replace(база, space=space_of(tenant))\n",
        "    свой = replace(база, space=DEFAULT_SPACE)\n",
        T
        + "test_mcp_partner_methodology.py::test_админ_партнёра_правит_свой_чек_лист_в_своём_пространстве",  # noqa: E501
    ),
    (
        "src/web/templates/methodology/checklists.html",
        '{% if not item.in_production and may("checklist.apply") %}',
        "{% if not item.in_production %}",
        T
        + "test_web_methodology_spaces.py::test_партнёру_применение_к_проду_не_показано_и_не_выдано",  # noqa: E501
    ),
    # Ревью безопасности: токен партнёра не выходит за своё пространство.
    (
        "src/mcp/checklist_tools.py",
        "    if side_of(tenant) != SIDE_HQ:\n",
        "    if False:\n",
        T + "test_mcp_partner_methodology.py::test_накопитель_слов_аудиторов_партнёру_не_отдаётся",
    ),
    (
        "src/mcp/policy.py",
        '    "uncovered_phrases": "phrases.raw",\n',
        "",
        T
        + "test_mcp_policy.py::test_админу_партнёра_открыты_инструменты_методики_кроме_указателя_прода",  # noqa: E501
    ),
    (
        "src/mcp/rpc.py",
        "        if spec.writes:\n            raise ToolError(ETALON_READONLY_FOR_PARTNER",
        "        if False:\n            raise ToolError(ETALON_READONLY_FOR_PARTNER",
        T
        + "test_mcp_partner_methodology.py::test_ни_один_инструмент_методики_не_трогает_чужое_пространство",  # noqa: E501
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
    # Граница пространств: необъявленный маршрут открылся бы партнёру (F-004).
    (
        "src/web/guard.py",
        "    return any(open_to_space(код, tenant) for код in "
        "_declared_codes(app, endpoint, path))\n",
        "    коды = _declared_codes(app, endpoint, path)\n"
        "    return not коды or any(open_to_space(код, tenant) for код in коды)\n",
        T + "test_web_guard.py::test_необъявленный_маршрут_партнёру_закрыт_УК_открыт",
    ),
    (
        "src/web/guard.py",
        "        and not _declared_codes(app, rule.endpoint, rule.rule)\n",
        "        and False\n",
        T + "test_web_guard.py::test_полнота_ловит_необъявленный_маршрут",
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
    # D603: договор страны — ОСБ получила бы девелопера и партнёра страны; блок и
    # правка у лишней роли; почты партнёру.
    (
        "src/domain/permissions.py",
        '"prescription.request", "prescription.manage", "view.osb", "contract.manage"),',
        '"prescription.request", "prescription.manage", "view.osb", "contract.manage", '
        '"space.manage"),',
        T + "test_permissions_osb.py::test_осб_правит_договор_но_не_остальную_карточку_страны",
    ),
    (
        "src/domain/permissions.py",
        '    (SIDE_HQ, "developer"): _HQ_WORK | _CHECKLISTS | _ALL_VIEWS_HQ | _codes("inspection.import"),\n',  # noqa: E501
        '    (SIDE_HQ, "developer"): _HQ_WORK | _CHECKLISTS | _ALL_VIEWS_HQ'
        ' | _codes("inspection.import", "contract.manage"),\n',
        T + "test_permissions_osb.py::test_договор_страны_правят_осб_админ_и_главный_админ",
    ),
    (
        "src/domain/permissions.py",
        '    Action("contract.manage", "people", hq_only=True),\n',
        '    Action("contract.manage", "people"),\n',
        T + "test_permissions_osb.py::test_договор_страны_только_для_ук_и_пишущее",
    ),
    (
        "src/web/country_settings.py",
        '    if show_email:\n        сведения["show_contract"] = True\n',
        '    if True:\n        сведения["show_contract"] = True\n',
        T
        + "test_web_country_contract.py::test_партнёр_договор_и_почты_не_видит_и_база_не_читается",
    ),
    (
        "src/web/country_settings.py",
        '    @guard.action("contract.manage")\n    def save_contract',
        '    @guard.action("view.country")\n    def save_contract',
        T
        + "test_web_country_contract.py::test_правка_договора_остальным_ролям_закрыта_и_ничего_не_пишет",  # noqa: E501
    ),
    (
        "src/web/templates/country/_settings.html",
        "{% if s.can_contract and not s.contracts_failed %}",
        "{% if not s.contracts_failed %}",
        T + "test_web_country_contract.py::test_остальные_роли_ук_видят_договор_но_без_форм_правки",
    ),
    (
        "src/db/country_contracts.py",
        '    значения["dkk_emails"] = normalize_emails(fields.dkk_emails)\n',
        '    значения["dkk_emails"] = fields.dkk_emails\n',
        T
        + "test_web_country_contract.py::test_подмена_заголовка_через_перевод_строки_не_доходит_до_базы",  # noqa: E501
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
