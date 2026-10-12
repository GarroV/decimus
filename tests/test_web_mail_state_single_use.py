"""F-019 аудита 12.10: метка похода за согласием Gmail обязана быть одноразовой на ЛЮБОМ исходе.

До правки письмо по проверке снимало куку похода только на успехе
(`src/web/letter_draft.py`, `google_mail_callback`): отказ в окне согласия или
несовпадение метки оставляли подписанную куку жить до `MAIL_STATE_TTL_SECONDS`,
и второй возврат с той же меткой и чужим кодом клал черновик.

Оба теста описывают требуемое поведение и падали на коде до правки (6be533c7).
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_letter_draft import включить_почту, клиент, увести  # noqa: F401 — фикстура

from src.web.letter_draft import MAIL_STATE_COOKIE


def _метка(уход: Any) -> str:
    поля = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))
    return поля["state"]


def _кука_снята(ответ: Any) -> bool:
    return any(
        MAIL_STATE_COOKIE in к and ("Max-Age=0" in к or "expires=Thu, 01 Jan 1970" in к)
        for к in ответ.headers.getlist("Set-Cookie")
    )


def test_отказ_в_окне_согласия_снимает_метку(
    клиент: tuple[FlaskClient, dict[str, list[Any]]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    включить_почту(monkeypatch)
    client, _ = клиент
    метка = _метка(увести(client))
    ответ = client.get(f"/auth/google/mail?state={метка}&error=access_denied")
    assert "gmail=denied" in ответ.headers["Location"]
    assert _кука_снята(ответ), "после отказа кука похода осталась в браузере"


def test_метка_после_отказа_не_принимает_второй_возврат(
    клиент: tuple[FlaskClient, dict[str, list[Any]]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    метка = _метка(увести(client))
    client.get(f"/auth/google/mail?state={метка}&error=access_denied")
    повтор = client.get(f"/auth/google/mail?state={метка}&code=другой-код")
    assert not следы["draft"], f"та же метка приняла второй возврат: {повтор.headers['Location']}"
