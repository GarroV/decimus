"""#418: мини-апп обхода — опознание по подписи Telegram, данные экрана, заголовки.

Самое дорогое здесь — опознание: адреса открыты без учётки админки, и всё,
что отделяет историю точки от постороннего, — подпись `initData`. Поэтому
каждый отказ проверяется отдельно: подделанная, устаревшая, пустая.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from flask import Flask
from web_harness import СЕКРЕТ

from src.db.bot_links import NEVER_BOUND, Standing
from src.db.errors import AccessError, DbError
from src.db.models import PreviousFinding, PreviousFindings
from src.domain import add_finding, get_state, list_zones, start_inspection
from src.web import walk, walk_write
from src.web.app import create_app
from src.web.config import Settings
from src.web.walk_auth import (
    INIT_DATA_HEADER,
    MAX_AGE_SECONDS,
    WalkAccessError,
    WalkSettings,
    chat_of,
    load_walk_settings,
)

ТОКЕН = "123456:TEST-token"
АУДИТОР = 4242


def подписать(user_id: int, *, token: str = ТОКЕН, auth_date: int | None = None) -> str:
    """initData так, как её подписывает Telegram (core.telegram.org/bots/webapps)."""
    поля = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Аудитор"}, ensure_ascii=False),
    }
    строка = "\n".join(f"{k}={v}" for k, v in sorted(поля.items()))
    ключ = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    поля["hash"] = hmac.new(ключ, строка.encode(), hashlib.sha256).hexdigest()
    return urlencode(поля)


БОТ = WalkSettings(bot_token=ТОКЕН, preview_chat=None)

# ── опознание ───────────────────────────────────────────────────────────


def test_подпись_telegram_даёт_чат_аудитора() -> None:
    assert chat_of(подписать(АУДИТОР), БОТ) == АУДИТОР


@pytest.mark.parametrize(
    "строка",
    [
        pytest.param(подписать(АУДИТОР, token="999:other"), id="чужой-токен"),
        pytest.param(подписать(АУДИТОР).replace("4242", "4243"), id="подменён-пользователь"),
        pytest.param("", id="пусто"),
        pytest.param("user=%7B%22id%22%3A1%7D", id="без-подписи"),
    ],
)
def test_неверная_подпись_отказ(строка: str) -> None:
    with pytest.raises(WalkAccessError):
        chat_of(строка, БОТ)


def test_устаревшая_подпись_отказ() -> None:
    давно = int(time.time()) - MAX_AGE_SECONDS - 60
    with pytest.raises(WalkAccessError, match="устарела"):
        chat_of(подписать(АУДИТОР, auth_date=давно), БОТ)


def test_просмотр_без_подписи_только_на_заданный_чат() -> None:
    стенд = WalkSettings(bot_token=None, preview_chat=7)
    assert chat_of("", стенд) == 7
    with pytest.raises(WalkAccessError):
        chat_of(подписать(АУДИТОР), стенд)  # подпись есть, а проверить её нечем


def test_просмотр_вместе_с_токеном_бота_не_стартует() -> None:
    with pytest.raises(ValueError, match="просмотр без подписи"):
        load_walk_settings({"TELEGRAM_BOT_TOKEN": ТОКЕН, "WEB_WALK_PREVIEW_CHAT": "7"})


def test_просмотр_не_открывается_на_настоящий_чат() -> None:
    """С D312 просмотр пишет: забытая переменная не должна открыть живую проверку."""
    with pytest.raises(ValueError, match="вымышленного диапазона"):
        load_walk_settings({"WEB_WALK_PREVIEW_CHAT": str(АУДИТОР)})
    assert load_walk_settings({"WEB_WALK_PREVIEW_CHAT": "999000000501"}).preview_chat


def test_без_настроек_обход_выключен() -> None:
    assert not load_walk_settings({}).enabled


# ── данные экрана ───────────────────────────────────────────────────────


def _прошлое(*находки: tuple[str, str, str, str | None]) -> walk.PreviousOutcome:
    return walk.PreviousOutcome(
        PreviousFindings(
            date=date(2026, 9, 15),
            findings=tuple(
                PreviousFinding(code=c, level=lv, zone=z, text=tx) for c, lv, z, tx in находки
            ),
        )
    )


def _зона(данные: dict, код: str) -> dict:
    return next(z for z in данные["zones"] if z["code"] == код)


def test_экран_раскладывает_записи_и_прошлое_по_зонам(domain_env: Path) -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    add_finding(1, code="CLN06", level="D1", zone="dining", text="пятно снова")
    проверка = get_state(1)
    assert проверка is not None

    данные = walk.build_walk(
        проверка,
        list_zones(chat_id=1),
        _прошлое(
            ("CLN06", "D1", "dining", "пятно на столе"),
            ("CLN06", "D1", "facade", None),
            ("ZZZ01", "D2", "old_zone", "зона из старой методики"),
        ),
        lang="ru",
        question=lambda code: {"CLN06": "(D1, D2) Столы чистые"}.get(code),
    )

    коды = [z["code"] for z in данные["zones"]]
    assert коды[:3] == [z.code for z in list_zones(chat_id=1)][:3], "порядок — методики"
    assert коды[-1] == "old_zone", "прошлая запись из исчезнувшей зоны не теряется"
    зал = _зона(данные, "dining")
    assert [r["text"] for r in зал["recorded"]] == ["пятно снова"]
    assert зал["previous"][0]["again"] is True, "тот же пункт в той же зоне — записан снова"
    фасад = _зона(данные, "facade")
    assert фасад["previous"][0]["again"] is False, "тот же пункт в ДРУГОЙ зоне — не повтор"
    assert фасад["previous"][0]["text"] == "Столы чистые", "без слов — вопрос методики без классов"
    assert данные["previous"] == {"date": "2026-09-15", "count": 3}


def test_ключ_пометок_свой_у_каждой_проверки(domain_env: Path) -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", date="2026-09-01")
    первая = get_state(1)
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", date="2026-10-01")
    вторая = get_state(1)
    assert первая is not None and вторая is not None

    ключ = walk.mark_key(первая)
    assert ключ != walk.mark_key(вторая), "новая проверка начиналась бы с прошлых галочек"
    assert len(ключ) <= 128 and ключ.replace("_", "").isalnum()


# ── маршруты и заголовки ────────────────────────────────────────────────


def _приложение(monkeypatch: pytest.MonkeyPatch, **env: str) -> Flask:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WEB_WALK_PREVIEW_CHAT", raising=False)
    for имя, значение in env.items():
        monkeypatch.setenv(имя, значение)
    app = create_app(
        Settings(host="127.0.0.1", port=8266, tenant="default", ui_lang="ru", secret_key=СЕКРЕТ)
    )
    app.config.update(TESTING=True)
    return app


def test_данные_по_подписи_и_без_истории(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")

    def база_молчит(**_: str) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(walk.queries, "previous_findings", база_молчит)
    monkeypatch.setattr(walk.bot_links, "standing", lambda _: NEVER_BOUND)
    client = _приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client()

    ответ = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")

    assert ответ.status_code == 200
    тело = ответ.get_json()
    assert тело["unit"] == "Белград-1" and тело["previous_unavailable"] is True
    assert тело["texts"]["walk.next.mark"] == "Осмотрено →"
    assert client.post(walk.DATA_PATH, data="hash=0", content_type="text/plain").status_code == 401


def test_без_проверки_экран_говорит_что_её_нет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _приложение(monkeypatch, WEB_WALK_PREVIEW_CHAT="999000000005").test_client()

    тело = client.post(walk.DATA_PATH, data="", content_type="text/plain").get_json()

    assert тело["state"] == "none" and "zones" not in тело


def test_выключенный_обход_не_отвечает(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _приложение(monkeypatch).test_client()
    assert client.get(walk.PAGE_PATH).status_code == 404
    assert client.post(walk.DATA_PATH, data="").status_code == 404


def test_страница_пускает_в_рамку_только_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client()

    ответ = client.get(walk.PAGE_PATH)

    assert ответ.status_code == 200
    политика = ответ.headers["Content-Security-Policy"]
    assert "frame-ancestors https://web.telegram.org https://*.telegram.org" in политика
    assert "script-src 'self' https://telegram.org" in политика
    assert "X-Frame-Options" not in ответ.headers
    вход = client.get("/login")
    assert вход.headers["X-Frame-Options"] == "DENY", "ослабление ушло дальше обхода"
    assert "frame-ancestors 'none'" in вход.headers["Content-Security-Policy"]


def _подписанный_клиент(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, положение: object
) -> Any:
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)

    def standing(_: int) -> object:
        if isinstance(положение, Exception):
            raise положение
        return положение

    monkeypatch.setattr(walk.bot_links, "standing", standing)
    return _приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client()


def test_снятый_доступ_не_открывает_даже_свою_проверку(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _подписанный_клиент(domain_env, monkeypatch, Standing(binding=None, ever_bound=True))
    ответ = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    assert ответ.status_code == 401, "отключённый человек видел бы обход и историю точки"


def test_без_привязки_пускает_тот_кого_пустил_бот(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _подписанный_клиент(domain_env, monkeypatch, NEVER_BOUND)
    ответ = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    assert ответ.status_code == 200


def test_база_молчит_отказ_а_не_пропуск_вслепую(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _подписанный_клиент(domain_env, monkeypatch, AccessError("нет базы"))
    ответ = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    assert ответ.status_code == 503


# ── пробный запуск на боевом боте: круг тестеров (WALK_USERS) ───────────


def test_вне_круга_тестеров_обход_закрыт_и_на_чтение_и_на_запись(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WALK_USERS", str(АУДИТОР + 1))
    client = _подписанный_клиент(domain_env, monkeypatch, NEVER_BOUND)

    чтение = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    запись = client.post(
        walk_write.FINDING_PATH,
        json={"op": "drop", "n": 1},
        headers={INIT_DATA_HEADER: подписать(АУДИТОР)},
    )

    assert чтение.status_code == 403 and чтение.get_json()["error"] == "closed"
    assert "walk.closed" in чтение.get_json()["texts"]
    assert запись.status_code == 403, "пересланная ссылка открыла бы запись не тестеру"


def test_тестер_из_круга_обход_видит(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALK_USERS", f"{АУДИТОР + 1}, {АУДИТОР}")
    client = _подписанный_клиент(domain_env, monkeypatch, NEVER_BOUND)
    ответ = client.post(walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain")
    assert ответ.status_code == 200


@pytest.mark.parametrize("значение", ["abc", " , "])
def test_кривой_круг_тестеров_отказ_на_старте(значение: str) -> None:
    with pytest.raises(ValueError, match="WALK_USERS"):
        load_walk_settings({"TELEGRAM_BOT_TOKEN": ТОКЕН, "WALK_USERS": значение})
