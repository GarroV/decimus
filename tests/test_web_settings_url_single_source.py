"""`settings_url` — адрес «Настроек» из общего контекста (`src/web/app.py`), один на все страницы.

Его читают меню учётки и боковая панель (`base.html`, `_account_menu*.html`). Страница,
передавшая в шаблон своё `settings_url`, молча перекрывает общее: на «Странах» «Все
настройки» вели в карточку страны, в журнале ссылки подключений выходили `/settings&tile=`.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "src" / "web"
#: Единственный источник и отдельное приложение обхода со своим контекстом.
ALLOWED = {"app.py", "walk_settings.py"}
ASSIGN = re.compile(r"""(["']settings_url["']\s*:|\bsettings_url\s*=)""")


def test_страница_не_перекрывает_адрес_настроек() -> None:
    нарушители = [
        f"{path.name}:{n}"
        for path in sorted(WEB.glob("*.py"))
        if path.name not in ALLOWED
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ASSIGN.search(line)
    ]
    assert not нарушители, (
        "settings_url задаётся только в src/web/app.py; страница перекрывает его: "
        + ", ".join(нарушители)
    )
