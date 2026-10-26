"""Журналы входов и действий на стороне веба (D462): запись одной точкой и экраны.

Ядро: что попадает в журнал действий (чьи действия, какие методы, ничего секретного)
и кто видит какой экран. Слой базы подменён на границе (`web_harness`), записи
собираются в списки; сама база и права — в `tests/test_db_journals.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import journals
from src.db.errors import AccessError

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПАРОЛЬ_ИЗ_ФОРМЫ = "пароль-из-формы-не-для-журнала"


def _вошедший(
    monkeypatch: pytest.MonkeyPatch, *, role: str, **настройки: object
) -> tuple[object, dict[str, list[object]]]:
    зовы = подменить_двери(monkeypatch, tenant="HQ", role=role)
    client = собрать(tenant="HQ", **настройки).test_client()  # type: ignore[arg-type]
    assert войти(client).status_code == 302
    return client, зовы


def _запись(зовы: dict[str, list[object]]) -> dict[str, object]:
    (запись,) = зовы["action_journal"]
    return запись  # type: ignore[return-value]


# --- журнал действий: одна точка на весь веб -------------------------------


@pytest.mark.parametrize("роль", ["admin", "superadmin"])
def test_изменяющий_запрос_админа_попадает_в_журнал(
    monkeypatch: pytest.MonkeyPatch, роль: str
) -> None:
    client, зовы = _вошедший(monkeypatch, role=роль)

    client.post("/users/freeze", data={"login": "someone", "tenant": "HQ"}, headers=ЗАГОЛОВКИ)

    запись = _запись(зовы)
    assert запись["action"] == "freeze_user"
    assert запись["role"] == роль
    assert запись["door"] == "web"
    assert запись["credential"] == "session:33333333-3333-3333-3333-333333333333"
    assert "login=someone" in str(запись["target"])
    assert str(запись["outcome"]).isdigit()


def test_отказанное_действие_тоже_записано_с_кодом_отказа(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, зовы = _вошедший(monkeypatch, role="admin")

    ответ = client.post("/users/unfreeze", data={"login": "x", "tenant": "HQ"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code >= 400
    assert _запись(зовы)["outcome"] == str(ответ.status_code)


@pytest.mark.parametrize("роль", ["developer", "control", "guest", "auditor"])
def test_действия_прочих_ролей_в_журнал_действий_не_идут(
    monkeypatch: pytest.MonkeyPatch, роль: str
) -> None:
    client, зовы = _вошедший(monkeypatch, role=роль)

    client.post("/users/freeze", data={"login": "someone", "tenant": "HQ"}, headers=ЗАГОЛОВКИ)

    assert зовы["action_journal"] == []


def test_чтение_в_журнал_действий_не_идёт(monkeypatch: pytest.MonkeyPatch) -> None:
    client, зовы = _вошедший(monkeypatch, role="superadmin")

    client.get("/administration?tab=people")
    client.get("/settings")

    assert зовы["action_journal"] == []


def test_пароль_из_формы_в_журнал_не_попадает(monkeypatch: pytest.MonkeyPatch) -> None:
    client, зовы = _вошедший(monkeypatch, role="superadmin")

    client.post(
        "/users/add",
        data={
            "login": "newbie",
            "password": ПАРОЛЬ_ИЗ_ФОРМЫ,
            "new_password": ПАРОЛЬ_ИЗ_ФОРМЫ,
            "tenant": "HQ",
            "role": "developer",
        },
        headers=ЗАГОЛОВКИ,
    )

    запись = _запись(зовы)
    assert ПАРОЛЬ_ИЗ_ФОРМЫ not in repr(запись), "пароль из формы попал в журнал"
    assert "login=newbie" in str(запись["target"])
    assert "password=…" in str(запись["target"]), "имя поля пароля должно остаться без значения"


def test_секреты_из_адреса_и_json_тоже_не_попадают(monkeypatch: pytest.MonkeyPatch) -> None:
    client, зовы = _вошедший(monkeypatch, role="admin")

    client.post(
        "/users/freeze?access_token=СЕКРЕТ-В-АДРЕСЕ",
        json={"api_key": "СЕКРЕТ-В-JSON", "login": "x"},
        headers=ЗАГОЛОВКИ,
    )

    запись = repr(_запись(зовы))
    assert "СЕКРЕТ-В-АДРЕСЕ" not in запись
    assert "СЕКРЕТ-В-JSON" not in запись


def test_сбой_записи_журнала_не_ломает_действие_и_виден_в_журнале_процесса(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def не_отвечает(_зачем: str) -> None:
        raise AccessError("база не ответила")

    monkeypatch.setattr(journals, "_connected", не_отвечает)

    journals.record_action(
        user_id="u",
        role="admin",
        tenant="HQ",
        action="x",
        target="",
        outcome="200",
        ip=None,
        credential=None,
    )  # не бросает: действие уже выполнено

    assert "журнал действий: запись не прошла" in caplog.text, "сбой записи прошёл молча"


# --- адрес клиента: только по цепочке доверенных звеньев --------------------


def test_адрес_из_подделанного_заголовка_не_берётся(monkeypatch: pytest.MonkeyPatch) -> None:
    client, зовы = _вошедший(monkeypatch, role="admin")

    client.post(
        "/users/freeze",
        data={"login": "x"},
        headers={**ЗАГОЛОВКИ, "X-Forwarded-For": "203.0.113.66"},
    )

    assert _запись(зовы)["ip"] != "203.0.113.66", "в журнал пошёл адрес, названный клиентом"


def test_за_одним_звеном_берётся_адрес_с_конца_цепочки(monkeypatch: pytest.MonkeyPatch) -> None:
    client, зовы = _вошедший(monkeypatch, role="admin", trusted_proxies=1)

    client.post(
        "/users/freeze",
        data={"login": "x"},
        headers={**ЗАГОЛОВКИ, "X-Forwarded-For": "203.0.113.66, 198.51.100.7"},
    )

    assert _запись(зовы)["ip"] == "198.51.100.7"


# --- журнал входов: двери ----------------------------------------------------


def test_удачный_вход_записан_с_сессией_и_адресом(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    client = собрать(tenant="HQ").test_client()

    войти(client)

    (запись,) = зовы["login_journal"]
    assert запись["method"] == "password"
    assert запись["result"] == "ok"
    assert запись["session_id"] == "33333333-3333-3333-3333-333333333333"
    assert запись["ip"] == "127.0.0.1"
    assert зовы["open_origin"][0]["ip"] == "127.0.0.1"  # адрес лёг и на саму сессию


def test_неверный_пароль_записан_как_неудача_с_логином(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    client = собрать(tenant="HQ").test_client()

    войти(client, password="не-тот")

    (запись,) = зовы["login_journal"]
    assert запись["failed"] is True
    assert запись["method"] == "password"
    assert запись["login"] == "director"
    assert "не-тот" not in repr(запись), "введённый пароль попал в журнал"


def test_запертый_перебором_записан_как_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    client = собрать(tenant="HQ").test_client()

    for _ in range(40):
        войти(client, password="не-тот")

    assert any(
        запись.get("result") == "rate-limited"  # type: ignore[union-attr]
        for запись in зовы["login_journal"]
    ), "запрет за перебор не виден в журнале входов"


# --- журнал входов и ограничитель перебора (D462, разбор безопасности) ------


def _порядок(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Записывать порядок: ограничитель (`admit`) и журнал (`journal`)."""
    события: list[str] = []
    from src.web import auth

    настоящий = auth.admit_attempt

    def _admit(**kw: object) -> object:
        события.append("admit")
        return настоящий(**kw)  # type: ignore[arg-type]

    монтаж_журнала = journals.record_failed_login

    def _журнал(**kw: object) -> None:
        события.append("journal")
        монтаж_журнала(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(auth, "admit_attempt", _admit)
    monkeypatch.setattr(journals, "record_failed_login", _журнал)
    return события


def test_ограничитель_спрашивается_раньше_журнала(monkeypatch: pytest.MonkeyPatch) -> None:
    """Журнал не стоит ни перед ограничителем, ни вместо него: сначала `admit`."""
    зовы = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    события = _порядок(monkeypatch)
    client = собрать(tenant="HQ").test_client()

    for _ in range(12):
        войти(client, password="не-тот")

    assert зовы["login_journal"], "журнал не записан вовсе"
    assert события[0] == "admit"
    for i, событие in enumerate(события):
        if событие == "journal":
            assert события[i - 1] == "admit", "запись в журнал пошла без запроса к ограничителю"


def test_отказ_журнала_не_сбрасывает_и_не_обходит_ограничитель(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Журнал упал — перебор всё равно упирается в запрет, и ответ не 500."""
    настоящий_неудачный = journals.record_failed_login
    настоящий_вход = journals.record_login
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    # База журнала недоступна: настоящие функции журнала идут в сломанное соединение.
    from src.db import web_access
    from src.db.errors import DbError

    def _недоступна(_: str) -> object:
        raise DbError("журнал недоступен")

    monkeypatch.setattr(web_access, "_connected", _недоступна)
    monkeypatch.setattr(journals, "record_failed_login", настоящий_неудачный)
    monkeypatch.setattr(journals, "record_login", настоящий_вход)
    client = собрать(tenant="HQ").test_client()

    коды = [войти(client, password="не-тот").status_code for _ in range(40)]

    assert 500 not in коды, "отказ журнала сломал форму входа"
    assert коды[0] == 401
    assert коды[-1] != 401, "запрет за перебор не наступил: журнал вмешался в ограничитель"


def test_ключ_ограничителя_не_берётся_из_заголовка_клиента(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    from src.web import auth

    адреса: list[str] = []
    настоящий = auth.admit_attempt

    def _admit(**kw: object) -> object:
        адреса.append(str(kw["address"]))
        return настоящий(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(auth, "admit_attempt", _admit)
    client = собрать(tenant="HQ").test_client()

    client.post(
        auth.LOGIN_PATH,
        data={"login": "x", "password": "y"},
        headers={"Origin": СВОЙ, "X-Forwarded-For": "10.6.6.6", "X-Real-IP": "10.7.7.7"},
    )

    assert адреса == ["127.0.0.1"], "ключ ограничителя взят из заголовка, который назвал клиент"


# --- экраны: кто что видит ---------------------------------------------------


def _заглушки(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """Чтение журнала: записываем, ЧТО и с каким токеном спросила страница."""
    спросили: dict[str, list[object]] = {"logins": [], "actions": [], "people": []}
    момент = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

    def _logins(token: str, **kw: object) -> tuple[journals.LoginEntry, ...]:
        спросили["logins"].append((token, kw))
        return (
            journals.LoginEntry(
                1, момент, "u1", "anna", "198.51.100.7", "UA-ТЕСТ", "google", "ok", None
            ),
        )

    def _actions(token: str, **kw: object) -> tuple[journals.ActionEntry, ...]:
        спросили["actions"].append((token, kw))
        return (
            journals.ActionEntry(
                1,
                момент,
                "u1",
                "anna",
                "admin",
                "web",
                "session:1",
                "198.51.100.7",
                "freeze_user",
                "login=x",
                "302",
            ),
        )

    monkeypatch.setattr(journals, "read_logins", _logins)
    monkeypatch.setattr(journals, "read_actions", _actions)
    monkeypatch.setattr(journals, "journal_people", lambda token: (("u1", "anna", None),))
    return спросили


def test_главный_админ_видит_журнал_во_вкладке_пользователей(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _вошедший(monkeypatch, role="superadmin")
    спросили = _заглушки(monkeypatch)

    входы = client.get("/administration?tab=journal")
    действия = client.get(
        "/administration?tab=journal&view=actions&person=11111111-1111-1111-1111-111111111111"
    )

    assert входы.status_code == 200 and действия.status_code == 200
    страница = входы.get_data(as_text=True)
    assert "anna" in страница and "198.51.100.7" in страница and "UA-ТЕСТ" in страница
    assert "Заморожена учётка" in действия.get_data(as_text=True), "код действия без подписи"
    assert спросили["actions"][0][1]["person"] == "11111111-1111-1111-1111-111111111111"  # type: ignore[index]
    assert 'href="/administration?tab=journal"' in страница, "вкладки «Журнал» в экране нет"


def test_имя_человека_жирным_а_логин_мелко_под_ним(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _вошедший(monkeypatch, role="superadmin")
    _заглушки(monkeypatch)
    момент = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        journals,
        "read_logins",
        lambda token, **kw: (
            journals.LoginEntry(
                1, момент, "u1", "admin", "198.51.100.7", "UA", "google", "ok", None, "Иван Петров"
            ),
            journals.LoginEntry(
                2, момент, "u2", "bob", "198.51.100.8", "UA", "password", "ok", None
            ),
        ),
    )
    monkeypatch.setattr(
        journals,
        "read_actions",
        lambda token, **kw: (
            journals.ActionEntry(
                1,
                момент,
                "u1",
                "admin",
                "admin",
                "web",
                None,
                None,
                "freeze_user",
                "",
                "302",
                "Иван Петров",
            ),
            journals.ActionEntry(
                2, момент, "u2", "bob", "admin", "web", None, None, "freeze_user", "", "302"
            ),
        ),
    )
    monkeypatch.setattr(
        journals,
        "journal_people",
        lambda token: (("u1", "admin", "Иван Петров"), ("u2", "bob", None)),
    )

    входы = client.get("/administration?tab=journal").get_data(as_text=True)
    действия = client.get("/administration?tab=journal&view=actions").get_data(as_text=True)

    for страница in (входы, действия):
        assert "<b>Иван Петров</b><small>admin</small>" in страница, "имя не жирным над логином"
        assert "<b>bob</b>" in страница, "без имени должен остаться логин"
        assert ">Иван Петров · admin</option>" in страница, "в списке людей нет «Имя · логин»"
        assert ">bob</option>" in страница


@pytest.mark.parametrize("роль", ["admin", "developer", "control", "guest", "auditor"])
def test_вкладки_журнала_нет_ни_у_кого_кроме_главного_админа(
    monkeypatch: pytest.MonkeyPatch, роль: str
) -> None:
    client, _ = _вошедший(monkeypatch, role=роль)
    спросили = _заглушки(monkeypatch)

    ответ = client.get("/administration?tab=journal")
    начальная = client.get("/administration?tab=people")

    assert ответ.status_code == 404
    assert спросили == {"logins": [], "actions": [], "people": []}, "страница спросила журнал"
    assert "tab=journal" not in начальная.get_data(as_text=True), "вкладка видна не главному админу"


@pytest.mark.parametrize(
    "роль", ["superadmin", "admin", "developer", "control", "guest", "auditor"]
)
def test_мои_входы_открыты_каждой_роли_и_без_выбора_человека(
    monkeypatch: pytest.MonkeyPatch, роль: str
) -> None:
    client, _ = _вошедший(monkeypatch, role=роль)
    спросили = _заглушки(monkeypatch)

    ответ = client.get(
        "/settings/sign-ins?person=11111111-1111-1111-1111-111111111111&view=actions"
    )

    assert ответ.status_code == 200
    assert спросили["logins"][0][1]["person"] is None, "«Мои входы» приняли фильтр по человеку"  # type: ignore[index]
    assert спросили["actions"] == [], "«Мои входы» показали журнал действий"
    assert "journal-person" not in ответ.get_data(as_text=True)


def test_сбой_базы_журнал_показывает_ошибкой_а_не_пустотой(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _вошедший(monkeypatch, role="superadmin")

    def упала(*_: object, **__: object) -> tuple[()]:
        raise AccessError("не удалось")

    monkeypatch.setattr(journals, "read_logins", упала)
    monkeypatch.setattr(journals, "journal_people", lambda token: ())

    ответ = client.get("/administration?tab=journal")

    assert ответ.status_code == 503
    assert "Журнал не прочитан" in ответ.get_data(as_text=True)


def test_период_уходит_в_базу_границами_суток(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _вошедший(monkeypatch, role="superadmin")
    спросили = _заглушки(monkeypatch)

    client.get("/administration?tab=journal&from=2026-10-01&to=2026-10-03")

    параметры = спросили["logins"][0][1]  # type: ignore[index]
    assert параметры["start"] == datetime(2026, 10, 1, tzinfo=UTC)  # type: ignore[index]
    assert параметры["end"] == datetime(2026, 10, 4, tzinfo=UTC), "конец периода не включает день"  # type: ignore[index]
