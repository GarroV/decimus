"""Блок `web` — веб-админка управляющей компании.

Контракт — `docs/furca/blocks/web.md`, поверхность описана в
`docs/12-web-admin.md`. Блок **читает** уже существующие двери и не заводит
своих: история проверок и карточка — `src/db/queries.py`, снятие —
`src/db/retract.py` (D086/D089), методика и виды проверок — `src/domain`.

Оценка здесь не считается ни в каком виде. Контракт `engine-not-imported` в
`lint-imports` делает это техническим фактом: импорт движка из `src.web` роняет
прогон.
"""

from __future__ import annotations

from .app import create_app
from .config import Settings, load_settings

__all__ = ["Settings", "create_app", "load_settings"]
