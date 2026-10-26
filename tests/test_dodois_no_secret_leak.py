"""Ключи Dodo IS нигде не печатаются и не логируются (D640): поиск по коду и прогон инструмента.

Статически: в модулях входов Dodo IS ни один вызов журнала процесса, `print` или `raise` не
берёт переменную с ключом, а сеть до `api.dodois.com` не знает слова POST. Живьём:
`tools/dodois_import.py` на входе с ключами и на сломанном входе не печатает ни одного.
"""

from __future__ import annotations

import ast
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.db import dodois_logins as store
from src.db.errors import AccessError
from src.db.job_lock import DODOIS_LOADER_LOCK_KEY
from src.dodois import client, service

КОРЕНЬ = Path(__file__).resolve().parents[1]
МОДУЛИ = (
    "src/dodois/client.py",
    "src/dodois/service.py",
    "src/dodois/flow.py",
    "src/db/dodois_logins.py",
    "src/web/dodois_screen.py",
    "src/web/dodois_connect.py",
    "src/bot/dodois_loader.py",
    "tools/dodois_import.py",
)
#: Имена, под которыми в этих модулях живут значения ключей и токена ссылки.
ОПАСНЫЕ = frozenset(
    {
        "access",
        "refresh",
        "access_token",
        "refresh_token",
        "device_code",
        "_device_code",
        "client_secret",
        "secret",
        "token",
        "tokens",
        "pair",
        "creds",
        "credentials",
        "raw_json",
        "data",
        "body",
    }
)
ЖУРНАЛЫ = frozenset({"debug", "info", "warning", "error", "exception", "critical", "print"})


def _имена(узел: ast.AST) -> set[str]:
    найдено: set[str] = set()
    for под in ast.walk(узел):
        if isinstance(под, ast.Name):
            найдено.add(под.id)
        elif isinstance(под, ast.Attribute):
            найдено.add(под.attr)
    return найдено


def _нарушения(путь: str) -> list[str]:
    дерево = ast.parse((КОРЕНЬ / путь).read_text(encoding="utf-8"))
    плохие: list[str] = []
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Call):
            функция = узел.func
            имя = функция.attr if isinstance(функция, ast.Attribute) else getattr(функция, "id", "")
            if имя in ЖУРНАЛЫ:
                for аргумент in [*узел.args, *(k.value for k in узел.keywords)]:
                    пересечение = _имена(аргумент) & ОПАСНЫЕ
                    if пересечение:
                        плохие.append(
                            f"{путь}:{узел.lineno} {имя}({', '.join(sorted(пересечение))})"
                        )
        if isinstance(узел, ast.Raise) and узел.exc is not None:
            пересечение = _имена(узел.exc) & ОПАСНЫЕ
            if пересечение:
                плохие.append(f"{путь}:{узел.lineno} raise({', '.join(sorted(пересечение))})")
    return плохие


@pytest.mark.parametrize("путь", МОДУЛИ)
def test_ни_журнал_ни_print_ни_исключение_не_берут_ключ(путь: str) -> None:
    # Сломанная копия: `logger.warning("... %s", pair)` в service.py — тест называет строку.
    assert _нарушения(путь) == []


def test_проверка_ловит_испорченный_вызов() -> None:
    """Сама проверка не слепа: на испорченном примере она находит нарушение."""
    пример = 'import logging\nlog = logging.getLogger("x")\nlog.warning("ключ %s", refresh_token)\n'
    путь = КОРЕНЬ / "reports" / "_dodois_leak_probe.py"
    путь.parent.mkdir(exist_ok=True)
    путь.write_text(пример, encoding="utf-8")
    try:
        assert _нарушения("reports/_dodois_leak_probe.py"), "проверка пропустила печать ключа"
    finally:
        путь.unlink()


def test_к_api_dodois_в_коде_нет_post() -> None:
    код = (КОРЕНЬ / "src/dodois/client.py").read_text(encoding="utf-8")
    assert "_post_form(_hosts(contour).api" not in код
    assert ".api +" in код and "_get(url, access_token)" in код


# --- инструмент переноса --------------------------------------------------------------------

ДОСТУП = "ACCESS-ТОКЕН-1111-секрет"
ПРОДЛЕНИЕ = "REFRESH-ТОКЕН-2222-секрет"


def _токены(**лишнее: Any) -> str:
    return json.dumps(
        {
            "access_token": ДОСТУП,
            "refresh_token": ПРОДЛЕНИЕ,
            "expires_in": 86400,
            "scope": "openid sales",
            "obtained_at": datetime.now(UTC).isoformat(),
            **лишнее,
        }
    )


def _вход_страны(поля: dict[str, Any]) -> Any:
    from src.domain.dodois import OK, Login

    return Login(
        поля["country"], "intl", поля["source"], поля["issued_by"], None, None, поля["now"],
        поля["scope"], None, None, поля["now"], поля["access_expires_at"], None, OK, None,
    )  # fmt: skip


def _перенос(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    тело: str,
    страна: str = "SI",
) -> tuple[int, str]:
    sys.path.insert(0, str(КОРЕНЬ))
    from tools import dodois_import

    записано: list[dict[str, Any]] = []

    def сохранить(**поля: Any) -> Any:
        записано.append(поля)
        return _вход_страны(поля)

    monkeypatch.setattr(store, "save_login", сохранить)
    monkeypatch.setattr(
        store, "get_login", lambda _c: _с_счётом(_вход_страны(записано[-1])) if записано else None
    )
    monkeypatch.setattr(service, "check", lambda c, now=None: _с_счётом(_вход_страны(записано[-1])))
    monkeypatch.setattr(client, "userinfo", lambda *_a: pytest.fail("userinfo у переноса не зовём"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(тело))
    код = dodois_import.main(["--country", страна, "--by", "owner"])
    вывод = capsys.readouterr()
    return код, вывод.out + вывод.err


def _с_счётом(вход: Any) -> Any:
    from dataclasses import replace

    return replace(вход, units_total=12, units_open=11, state="partial")


def test_перенос_печатает_только_состояние_и_счёт(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    код, вывод = _перенос(monkeypatch, capsys, _токены())
    assert код == 0
    assert вывод.strip() == "SI: состояние partial, открыто 11 из 12"
    assert ДОСТУП not in вывод and ПРОДЛЕНИЕ not in вывод


def test_перенос_пишет_как_обычный_вход_владельца(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools import dodois_import  # noqa: F401

    записано: list[dict[str, Any]] = []
    monkeypatch.setattr(store, "save_login", lambda **п: записано.append(п) or _вход_страны(п))
    monkeypatch.setattr(store, "get_login", lambda _c: _вход_страны(записано[-1]))
    monkeypatch.setattr(service, "check", lambda c, now=None: _вход_страны(записано[-1]))
    monkeypatch.setattr(sys, "stdin", io.StringIO(_токены()))
    from tools import dodois_import as инструмент

    инструмент.main(["--country", "BG", "--by", "owner"])
    (запись,) = записано
    assert (запись["country"], запись["source"], запись["issued_by"]) == ("BG", "import", "owner")
    assert запись["invite_id"] is None
    assert (запись["account_name"], запись["account_email"]) == (None, None)
    assert запись["tokens"].access == ДОСТУП and запись["tokens"].refresh == ПРОДЛЕНИЕ


@pytest.mark.parametrize(
    "тело",
    [
        "не json " + ДОСТУП,
        json.dumps([ДОСТУП]),
        json.dumps({"access_token": ДОСТУП}),
        _токены(expires_in="много"),
        _токены(obtained_at="вчера " + ДОСТУП),
    ],
    # Имена — постоянные: в теле текущее время, и под xdist каждый процесс собирал бы
    # свой набор тестов («Different tests were collected»), роняя весь прогон.
    ids=["не-json", "список", "без-продления", "срок-словом", "время-словом"],
)
def test_сломанный_вход_не_печатает_значений(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], тело: str
) -> None:
    код, вывод = _перенос(monkeypatch, capsys, тело)
    assert код == 2 and вывод.strip()
    assert ДОСТУП not in вывод and ПРОДЛЕНИЕ not in вывод


def test_отказ_базы_в_переносе_называет_тип_а_не_текст(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sys.path.insert(0, str(КОРЕНЬ))
    from tools import dodois_import

    def падает(**_п: Any) -> Any:
        raise AccessError(f"база отказала: {ДОСТУП}")  # даже если бы текст нёс значение

    monkeypatch.setattr(store, "save_login", падает)
    monkeypatch.setattr(sys, "stdin", io.StringIO(_токены()))
    код = dodois_import.main(["--country", "SI", "--by", "owner"])
    вывод = capsys.readouterr()
    assert код == 1 and "AccessError" in вывод.err
    assert ДОСТУП not in вывод.out + вывод.err


@pytest.mark.parametrize("страна", ["si", "SLO", "S1", ""])
def test_страна_в_переносе_только_из_двух_заглавных(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], страна: str
) -> None:
    код, вывод = _перенос(monkeypatch, capsys, _токены(), страна)
    assert код == 2 and ДОСТУП not in вывод


def test_продление_при_переносе_идёт_под_замком_бота(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Сломанная копия: звать `service.refresh` без `job_lock` — перенос продлит вдвоём с ботом.
    from contextlib import contextmanager
    from datetime import timedelta

    sys.path.insert(0, str(КОРЕНЬ))
    from tools import dodois_import

    записано: list[dict[str, Any]] = []
    замки: list[int] = []

    @contextmanager
    def занят(key: int, *, what: str):  # type: ignore[no-untyped-def]
        замки.append(key)
        yield False

    def прикрепить(**поля: Any) -> Any:
        ожидаемые = {"scope": "openid", "now": datetime.now(UTC), "access_expires_at": None}
        записано.append({**ожидаемые, **поля})
        return _вход_страны(записано[-1])

    monkeypatch.setattr(dodois_import, "job_lock", занят)
    monkeypatch.setattr(service, "attach", прикрепить)
    monkeypatch.setattr(service, "credentials", lambda: client.Credentials("id", "key"))
    monkeypatch.setattr(store, "get_login", lambda _c: _вход_страны(записано[-1]))
    monkeypatch.setattr(
        service, "refresh", lambda *_a, **_k: pytest.fail("продление мимо замка бота")
    )
    давно = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    monkeypatch.setattr(sys, "stdin", io.StringIO(_токены(obtained_at=давно)))
    код = dodois_import.main(["--country", "SI", "--by", "owner"])
    вывод = capsys.readouterr()
    assert код == 1 and "замок" in вывод.err
    assert замки == [DODOIS_LOADER_LOCK_KEY]
    assert ДОСТУП not in вывод.out + вывод.err
