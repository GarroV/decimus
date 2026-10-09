"""Порча защит мини-аппа обхода (D312): каждая сломанная защита обязана уронить свой тест.

Запуск: `.venv/bin/python tools/porcha_walk.py` из корня репозитория. Каждый
случай подменяет одну строку кода, гоняет ровно её тест и возвращает файл на
место. «НЕ ПРИМЕНИЛАСЬ» — код уехал, и порчу надо обновить: молча зелёный
прогон без подмены и есть та ложь, ради которой скрипт заведён.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`, см. цель `test-honest` в
`Makefile`): порча того же размера в ту же секунду подхватила бы кэш, и тест
«поймал» бы исправный код.
"""

import os
import pathlib
import subprocess
import sys

cases = [
    (
        "src/domain/uploads.py",
        "    _check_decodes(raw)\n",
        "",
        "tests/test_web_walk_write.py::test_не_jpeg_не_принимается",
    ),
    (
        "src/web/walk.py",
        "    if header_only and INIT_DATA_HEADER not in request.headers:",
        "    if False:",
        "tests/test_web_walk_write.py::test_запись_без_подписи_в_заголовке_не_читает_тело",
    ),
    (
        "src/web/walk_write.py",
        "    if _CONTROL.search(clean):",
        "    if False:",
        "tests/test_web_walk_write.py::test_управляющие_символы_не_доходят_до_движка",
    ),
    (
        "src/web/walk_write.py",
        "    if repeat is True and level not in REPEAT_LEVELS:",
        "    if False:",
        "tests/test_web_walk_write.py::test_повтор_у_замера_правкой_не_ставится",
    ),
    (
        "src/web/walk_auth.py",
        "        if not PREVIEW_CHATS[0] <= preview <= PREVIEW_CHATS[1]:",
        "        if False:",
        "tests/test_web_walk.py::test_просмотр_не_открывается_на_настоящий_чат",
    ),
    (
        "src/web/walk_write.py",
        "        if handed_over(chat_id):\n            return refused(",
        "        if False:\n            return refused(",
        "tests/test_web_walk_write.py::test_сданная_проверка_не_правится",
    ),
    (
        "src/web/walk_write.py",
        "            with while_open(who):\n",
        "            if True:\n",
        "tests/test_web_walk_write.py::test_сдача_между_ранней_проверкой_и_записью_не_пропускает_запись",
    ),
    (
        "src/domain/handover.py",
        "    with state_lock(_notes_path(chat_id)):",
        "    with state_lock(_notes_path(chat_id).with_suffix('.porcha')):",
        "tests/test_domain_handover_lock.py::test_пока_идёт_запись_бот_не_сдаёт",
    ),
    (
        "src/web/walk_write.py",
        "        if inspection is None or not _owns(inspection, ref):",
        "        if inspection is None:",
        "tests/test_web_walk_write.py::test_кадр_показывается_только_хозяину_записи",
    ),
    (
        "src/web/walk_write.py",
        "    if not isinstance(value, list) or not value:\n",
        "    if not isinstance(value, list):\n",
        "tests/test_web_walk_write.py::test_запись_без_настоящего_кадра_не_заводится",
    ),
    (
        "src/web/walk.py",
        "        if conf.bot_token is not None and walk_access.space_of(chat_id, conf) is None:",
        "        if False:",
        "tests/test_web_walk_write.py::test_снятый_доступ_не_пишет",
    ),
    (
        "src/domain/uploads.py",
        '_REF = re.compile(r"^walk:([0-9a-f]{32})$")',
        '_REF = re.compile(r"^walk:(.+)$")',
        "tests/test_domain_walk_uploads.py::test_чужая_ссылка_пути_не_даёт",
    ),
    (
        "src/bot/info.py",
        "        if field.code in answered:\n            continue\n",
        "",
        "tests/test_domain_walk_uploads.py::test_заполненное_в_обходе_бот_не_спрашивает",
    ),
    (
        "engine/audit.py",
        '        if not rest and not a.add and f["level"] != ADVICE:\n',
        "        if False:\n",
        "tests/test_web_walk_write.py::test_последний_кадр_не_снимается",
    ),
    (
        "src/web/walk_write.py",
        'repeat=body.get("repeat") is True and level in REPEAT_LEVELS,',
        'repeat=body.get("repeat") is True,',
        "tests/test_web_walk_write.py::test_повтор_только_по_нажатию_и_не_у_замера",
    ),
    (
        "src/web/walk.py",
        "    if not walk_open_to(conf.users, chat_id):",
        "    if False:",
        "tests/test_web_walk.py::test_вне_круга_тестеров_обход_закрыт_и_на_чтение_и_на_запись",
    ),
    (
        "src/bot/config.py",
        "        if self.walk_url is None or not walk_open_to(self.walk_users, user_id):",
        "        if self.walk_url is None:",
        "tests/test_bot_walk_button.py::test_круг_тестеров_кнопка_только_им",
    ),
    (
        "src/domain/walk_users.py",
        "    if not ids:\n",
        "    if False:\n",
        "tests/test_web_walk.py::test_кривой_круг_тестеров_отказ_на_старте",
    ),
    (
        "src/bot/propose.py",
        "    if words and not album_mode(words, len(frames)):",
        "    if words:",
        "tests/test_web_walk_suggest.py::test_пачка_с_комментарием_идёт_в_модель_целиком",
    ),
    (
        "src/web/walk_write.py",
        "    if words and learns:",
        "    if words:",
        "tests/test_web_walk_suggest.py::test_выученная_фраза_второй_раз_не_учится",
    ),
    # D372: посторонний с настоящей подписью — бот его не пускает, и мини-апп тоже.
    (
        "src/bot/access.py",
        "    if положение.ever_bound:\n        # Отвязан",
        "    if False:\n        # Отвязан",
        "tests/test_web_walk.py::test_снятый_доступ_не_открывает_даже_свою_проверку",
    ),
    # D373: команда с токеном ко всей истории — только кругу доступа к MCP.
    (
        "src/web/walk_settings.py",
        "            if bot is None or not in_circle(who, bot):",
        "            if bot is None:",
        "tests/test_web_walk_app.py::test_токен_только_кругу",
    ),
    (
        "src/web/walk_settings.py",
        "        if кому not in bot.allowed_ids:",
        "        if False:",
        "tests/test_web_walk_app.py::test_привести_можно_только_того_кого_пускает_бот",
    ),
    (
        "src/web/walk_settings.py",
        "        if у_кого == bot.mcp_owner_id:",
        "        if False:",
        "tests/test_web_walk_app.py::test_основателя_не_отозвать",
    ),
]
bad = 0
for path, old, new, test in cases:
    p = pathlib.Path(path)
    orig = p.read_text()
    if old not in orig:
        print("НЕ ПРИМЕНИЛАСЬ:", path, old[:50])
        bad += 1
        continue
    p.write_text(orig.replace(old, new, 1))
    try:
        r = subprocess.run(  # noqa: S603 — свой pytest и свои пути из списка выше
            [".venv/bin/pytest", "-q", "-x", "--no-cov", "-p", "no:cacheprovider", test],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    finally:
        p.write_text(orig)
    ok = r.returncode != 0
    line = [row for row in r.stdout.splitlines() if row.startswith("E ")][:1]
    print(
        ("ЛОВИТ " if ok else "НЕ ЛОВИТ ") + test.split("::")[1],
        "|",
        (line[0][:110] if line else ""),
    )
    bad += 0 if ok else 1
sys.exit(bad)
