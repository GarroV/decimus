"""Переключатель пространств главного админа (D726): дверь, подмена вида, «только просмотр».

Ядро прав: кто вправе переключаться, что видно и что запрещено, пока включено. Слой базы
подменён на границе (`web_harness`): опознание отдаёт НАСТОЯЩИЙ `Account`, а запись состояния
в сессию — словарь. Сама функция базы и её отказы — `tests/test_db_session_peek.py`.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, войти, подменить_двери, собрать

from src.db.web_access import Account
from src.web import auth, peek, second_step

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВЛАДЕЛЕЦ = "22222222-2222-2222-2222-222222222222"
СЕССИЯ = "33333333-3333-3333-3333-333333333333"
ПЛАШКА = "peek-bar"


def _учётка(*, tenant: str, role: str, **поля: Any) -> Account:
    return Account(
        id=ВЛАДЕЛЕЦ,
        login="director",
        tenant=tenant,
        role=role,
        session_id=СЕССИЯ,
        has_second_factor=поля.pop("has_second_factor", False),
        passed_second_step=поля.pop("passed_second_step", True),
        acting_name="Тестовый партнёр",
        **поля,
    )


class Стенд:
    """Вошедший клиент и то, что видно снаружи: журнал, записанные переключения."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        tenant: str = "HQ",
        role: str = "superadmin",
        **поля: Any,
    ) -> None:
        self.зовы = подменить_двери(monkeypatch, tenant=tenant, role=role)
        self.учётка = _учётка(tenant=tenant, role=role, **поля)
        #: Что записано на сессию (`web_session_peeks`).
        self.acting: str | None = None
        self.переключения: list[tuple[str, str | None]] = []
        self.база_разрешает = True

        def _resolve(token: str) -> Account | None:
            if token != ТОКЕН:
                return None
            return replace(self.учётка, acting_tenant=self.acting)

        def _set(token: str, target: str | None) -> bool:
            self.переключения.append((token, target))
            if not self.база_разрешает:
                return False
            self.acting = target
            return True

        monkeypatch.setattr(auth, "resolve_session", _resolve)
        monkeypatch.setattr(peek, "set_acting_tenant", _set)
        app = собрать(tenant=tenant)
        #: Как страница видела вошедшего в последнем запросе.
        self.снимок: dict[str, Any] = {}

        def _запомнить(ответ: Any) -> Any:
            вошедший = auth.current_account()
            if вошедший is not None:
                self.снимок = {
                    "tenant": auth.current_tenant(),
                    "role": вошедший.role,
                    "id": вошедший.id,
                    "real_role": вошедший.actual.role,
                    "охват": auth.current_reach().countries,
                }
            return ответ

        app.after_request(_запомнить)
        self.client: FlaskClient = app.test_client()
        assert войти(self.client).status_code == 302

    def переключить(self, target: str) -> Any:
        return self.client.post("/space/peek", data={"target": target}, headers=ЗАГОЛОВКИ)

    def страница(self) -> str:
        ответ = self.client.get("/settings?lang=ru")
        assert ответ.status_code == 200
        return ответ.get_data(as_text=True)


def _меню(html: str) -> list[str]:
    """Ссылки левой панели — то, что вошедший видит как «своё меню»."""
    панель = html.split('<nav class="sidenav', 1)[1].split("</nav>", 1)[0]
    return sorted(set(re.findall(r'href="([^"]+)"', панель)))


def _свой_вид(вид: Account, учётка: Account) -> bool:
    return вид is учётка and not вид.is_peeking


# --- кто вправе -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("пространство", "роль"),
    [
        ("HQ", "admin"),
        ("HQ", "developer"),
        ("HQ", "guest"),
        ("HQ", "control"),
        ("TEST", "admin"),
        ("TEST", "auditor"),
    ],
)
def test_прочим_ролям_дверь_закрыта_и_кнопки_нет(
    monkeypatch: pytest.MonkeyPatch, пространство: str, роль: str
) -> None:
    стенд = Стенд(monkeypatch, tenant=пространство, role=роль)

    ответ = стенд.переключить("TEST")

    assert ответ.status_code == 403
    assert стенд.переключения == [], "до базы отказанный не дошёл"
    assert "peek-switch" not in стенд.страница()


def test_главному_админу_кнопка_видна_и_переключение_ведёт_на_главную(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = Стенд(monkeypatch)
    assert 'class="peek-switch"' in стенд.страница()

    ответ = стенд.переключить("TEST")

    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith("/")
    assert стенд.переключения == [(ТОКЕН, "TEST")]


def test_без_второй_ступени_главный_админ_не_переключается(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = Стенд(monkeypatch, has_second_factor=True, passed_second_step=False)

    assert стенд.переключить("TEST").status_code == 403
    assert стенд.переключения == []
    assert "peek-switch" not in стенд.страница()


@pytest.mark.parametrize("цель", ["OTHER", "test", "default", "", "TEST;drop", "SI"])
def test_цель_вне_перечня_отказ_и_база_не_зовётся(
    monkeypatch: pytest.MonkeyPatch, цель: str
) -> None:
    стенд = Стенд(monkeypatch)

    assert стенд.переключить(цель).status_code == 400
    assert стенд.переключения == []


def test_отказ_базы_не_включает_просмотр(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.база_разрешает = False

    assert стенд.переключить("TEST").status_code == 403
    assert ПЛАШКА not in стенд.страница()


def test_чужая_страница_не_переключает(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)

    ответ = стенд.client.post(
        "/space/peek", data={"target": "TEST"}, headers={"Origin": "http://evil.example"}
    )

    assert ответ.status_code == 403
    assert стенд.переключения == []


# --- вид партнёра -----------------------------------------------------------------


def test_включённый_просмотр_показывает_меню_админа_партнёра(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    партнёр = Стенд(monkeypatch, tenant="TEST", role="admin")
    меню_партнёра = _меню(партнёр.страница())

    стенд = Стенд(monkeypatch)
    меню_владельца = _меню(стенд.страница())
    assert меню_владельца != меню_партнёра, "иначе проверка ничего не различает"
    стенд.переключить("TEST")
    html = стенд.страница()

    assert _меню(html) == меню_партнёра
    assert ПЛАШКА in html
    assert "Тестовый партнёр" in html
    assert "только просмотр" in html


def test_вид_партнёра_живёт_в_пространстве_партнёра(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    стенд.client.get("/settings?lang=ru")

    assert стенд.снимок["tenant"] == "TEST"
    assert стенд.снимок["role"] == "admin"
    assert стенд.снимок["id"] == ВЛАДЕЛЕЦ, "id — настоящий"
    assert стенд.снимок["real_role"] == "superadmin"
    assert стенд.снимок["охват"] == ("TEST",), "охват — партнёрский, не вся сеть"


def test_возврат_в_ук_выключает_просмотр(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    assert ПЛАШКА in стенд.страница()

    ответ = стенд.переключить("HQ")

    assert ответ.status_code == 302
    assert стенд.переключения[-1] == (ТОКЕН, None)
    assert ПЛАШКА not in стенд.страница()


# --- остаться на той же странице ---------------------------------------------------


def _переключить_с(стенд: Стенд, target: str, back: str) -> Any:
    return стенд.client.post(
        "/space/peek", data={"target": target, "back": back}, headers=ЗАГОЛОВКИ
    )


def test_после_переключения_остаётся_на_той_же_странице(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)

    туда = _переключить_с(стенд, "TEST", "/settings?lang=ru")
    assert туда.status_code == 302
    assert туда.headers["Location"].endswith("/settings?lang=ru")
    assert стенд.client.get("/settings?lang=ru").status_code == 200

    обратно = _переключить_с(стенд, "HQ", "/settings?lang=ru")
    assert обратно.headers["Location"].endswith("/settings?lang=ru")


@pytest.mark.parametrize(
    "back", ["https://evil.example/x", "//evil.example/x", "/\\evil.example", "", "/space/peek"]
)
def test_чужой_или_битый_адрес_возврата_ведёт_на_главную(
    monkeypatch: pytest.MonkeyPatch, back: str
) -> None:
    стенд = Стенд(monkeypatch)

    ответ = _переключить_с(стенд, "TEST", back)

    assert ответ.status_code == 302
    assert ответ.headers["Location"].rstrip("/").endswith(("localhost", ""))
    assert "evil" not in ответ.headers["Location"]
    assert not ответ.headers["Location"].endswith("/space/peek")


def test_страница_не_видная_партнёру_уводит_на_главную(monkeypatch: pytest.MonkeyPatch) -> None:
    партнёр = Стенд(monkeypatch, tenant="TEST", role="admin")
    меню_партнёра = set(_меню(партнёр.страница()))
    стенд = Стенд(monkeypatch)
    только_ук = sorted(set(_меню(стенд.страница())) - меню_партнёра)
    assert только_ук, "нужна страница, которой нет у партнёра"
    путь = только_ук[0].replace("&amp;", "&")

    туда = _переключить_с(стенд, "TEST", путь)
    assert туда.headers["Location"].endswith(путь)
    ответ = стенд.client.get(путь)

    assert ответ.status_code == 302, f"{путь} → {ответ.status_code}"
    assert ответ.headers["Location"].endswith("/")
    # Отметка живёт один запрос: дальше закрытая страница — обычный отказ.
    assert стенд.client.get(путь).status_code in (403, 404)


# --- только просмотр --------------------------------------------------------------


@pytest.mark.parametrize("метод", ["post", "put", "patch", "delete"])
def test_запись_при_просмотре_отказ(monkeypatch: pytest.MonkeyPatch, метод: str) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")

    ответ = getattr(стенд.client, метод)(
        "/users/freeze", data={"login": "x", "tenant": "TEST"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 403
    assert "Только просмотр" in ответ.get_data(as_text=True)


def test_запись_до_включения_просмотра_идёт_обычным_путём(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = Стенд(monkeypatch)

    ответ = стенд.client.post(
        "/users/freeze", data={"login": "x", "tenant": "HQ"}, headers=ЗАГОЛОВКИ
    )

    assert "Только просмотр" not in ответ.get_data(as_text=True)


def test_выход_при_просмотре_работает(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")

    ответ = стенд.client.post(auth.LOGOUT_PATH, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 302
    assert стенд.зовы["close"] == [ТОКЕН]


def test_пишущий_get_при_просмотре_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    from src.web import guard

    (адрес,) = [
        правило.rule
        for правило in стенд.client.application.url_map.iter_rules()
        if правило.endpoint in guard.WRITING_GETS
    ]

    ответ = стенд.client.get(адрес)

    assert ответ.status_code == 403
    assert "Только просмотр" in ответ.get_data(as_text=True)


# --- журнал -----------------------------------------------------------------------


def test_переключение_пишется_настоящей_учёткой(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)

    стенд.переключить("TEST")
    стенд.переключить("HQ")

    включение, выключение = стенд.зовы["action_journal"]
    for запись in (включение, выключение):
        assert запись["user_id"] == ВЛАДЕЛЕЦ
        assert запись["role"] == "superadmin"
        assert запись["tenant"] == "HQ"
        assert запись["action"] == "space_peek"
    assert "target=TEST" in str(включение["target"])
    assert "target=HQ" in str(выключение["target"])


def test_отказанная_запись_при_просмотре_пишется_настоящей_учёткой(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    стенд.зовы["action_journal"].clear()

    стенд.client.post("/users/freeze", data={"login": "x", "tenant": "TEST"}, headers=ЗАГОЛОВКИ)

    (запись,) = стенд.зовы["action_journal"]
    assert запись["user_id"] == ВЛАДЕЛЕЦ
    assert запись["role"] == "superadmin"
    assert запись["tenant"] == "HQ"
    assert запись["outcome"] == "403"
    assert str(запись["target"]).startswith("as=TEST;")


def test_чтение_страницы_при_просмотре_пишется_настоящей_учёткой(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    стенд.зовы["action_journal"].clear()

    ответ = стенд.client.get("/settings?lang=ru&q=Иван+Иванов")
    assert ответ.status_code == 200

    (запись,) = стенд.зовы["action_journal"]
    assert запись["user_id"] == ВЛАДЕЛЕЦ
    assert запись["role"] == "superadmin"
    assert запись["tenant"] == "HQ"
    assert запись["action"] == "peek_view"
    assert запись["target"] == "as=TEST; /settings"
    assert "Иван" not in str(запись["target"]), "строка запроса в журнал не идёт"


def test_чтение_без_просмотра_в_журнал_не_пишется(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.зовы["action_journal"].clear()

    assert стенд.client.get("/settings?lang=ru").status_code == 200

    assert стенд.зовы["action_journal"] == []


def test_отдача_файлов_при_просмотре_не_журналируется(monkeypatch: pytest.MonkeyPatch) -> None:
    стенд = Стенд(monkeypatch)
    стенд.переключить("TEST")
    стенд.зовы["action_journal"].clear()

    ответ = стенд.client.get("/static/decimus-web.css")

    assert ответ.status_code == 200
    assert стенд.зовы["action_journal"] == []


# --- вторая ступень и закрытие при сомнении -----------------------------------------


def test_вторая_ступень_настоящей_учётки_держит_и_при_просмотре(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(second_step, "ENFORCE_ENROLL", True)
    стенд = Стенд(monkeypatch)
    стенд.acting = "TEST"

    ответ = стенд.client.get("/settings?lang=ru")

    assert ответ.status_code == 302
    assert "security" in ответ.headers["Location"]


@pytest.mark.parametrize("цель", ["OTHER", "test"])
def test_запись_в_сессии_вне_перечня_не_действует(цель: str) -> None:
    учётка = _учётка(tenant="HQ", role="superadmin", acting_tenant=цель)

    assert _свой_вид(auth.peeked_view(учётка), учётка)


@pytest.mark.parametrize(
    ("роль", "пространство"), [("admin", "HQ"), ("admin", "TEST"), ("developer", "HQ")]
)
def test_запись_в_сессии_не_действует_для_не_главного_админа(роль: str, пространство: str) -> None:
    учётка = _учётка(tenant=пространство, role=роль, acting_tenant="TEST")

    assert _свой_вид(auth.peeked_view(учётка), учётка)


def test_запись_в_сессии_не_действует_без_второй_ступени() -> None:
    учётка = _учётка(
        tenant="HQ",
        role="superadmin",
        acting_tenant="TEST",
        has_second_factor=True,
        passed_second_step=False,
    )

    assert _свой_вид(auth.peeked_view(учётка), учётка)
