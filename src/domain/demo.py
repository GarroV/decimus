"""Открытое демо: учётки ролей и переключатели — контракт между посевом и входом.

Демо — отдельный стенд со своей базой и своим хранилищем кадров (D524). Посев
(`tools/seed_web_demo.py`) заводит в нём по учётке на каждую роль ниже, вход
`/demo` (`src/web/demo_entry.py`) открывает сессию выбранной учётки без пароля.
Обе стороны берут логины отсюда, чтобы не разойтись молча: посев завёл
`demo-admin`, а вход ищет `demo_admin` — и демо отвечает «нет такой учётки».

Вход без пароля включается ТОЛЬКО переменной `WEB_DEMO=1`. На проде её нет,
и `/demo` там отвечает 404 — проверяется тестом.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.tenants import HQ_TENANT

#: `WEB_DEMO=1` — стенд демо: открыт вход `/demo` без пароля и плашка «демо».
DEMO_VAR = "WEB_DEMO"
#: Адрес демо-стенда для кнопки лендинга прода (`WEB_DEMO_URL`). Не задан —
#: кнопки «Демо» на лендинге нет.
DEMO_URL_VAR = "WEB_DEMO_URL"
#: Пространство партнёра демо-сети.
DEMO_PARTNER_TENANT = "demo"


@dataclass(frozen=True)
class DemoRole:
    """Роль, которой посетитель входит в демо."""

    key: str
    login: str
    tenant: str
    role: str
    name: str


#: В порядке показа на экране выбора роли.
DEMO_ROLES: tuple[DemoRole, ...] = (
    DemoRole("admin", "demo-admin", HQ_TENANT, "admin", "Olivia Hart"),
    DemoRole("developer", "demo-developer", HQ_TENANT, "developer", "Marco Bianchi"),
    DemoRole("partner", "demo-partner", DEMO_PARTNER_TENANT, "admin", "Lena Novak"),
    DemoRole("viewer", "demo-viewer", HQ_TENANT, "guest", "Sam Taylor"),
)


def demo_role(key: str) -> DemoRole | None:
    """Роль по ключу из адреса `/demo/<key>`; чужой ключ — `None`."""
    return next((r for r in DEMO_ROLES if r.key == key), None)
