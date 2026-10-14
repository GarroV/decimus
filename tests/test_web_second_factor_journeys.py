"""Вторая ступень входа (D463): пути человека через настоящий веб и настоящую базу.

Ядро доступа. Проверяется то, чего ошибка не показывает сама: полувход не открывает
ни одного маршрута; админ без способа не обходит подключение; код и ключ принимаются
ровно один раз; чужое происхождение, чужой домен, откат счётчика и повтор вызова — отказ.
Приложение — настоящее, база — настоящая под ролью приложения (`db_env`); только браузер
заменён: клиент Flask и виртуальный ключ доступа (`virtual_authenticator`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pyotp
import pytest
from conftest import requires_db
from db_harness import завести_пространства
from flask.testing import FlaskClient
from virtual_authenticator import VirtualAuthenticator
from web_harness import СВОЙ, войти, собрать

psycopg = pytest.importorskip("psycopg")

from src.db import second_factor as sf  # noqa: E402
from src.db.web_access import authenticate, create_account  # noqa: E402
from src.domain.second_factor import (  # noqa: E402
    MAX_PENDING_FAILURES,
    TOTP_INTERVAL_SECONDS,
    backup_code_hash,
    new_backup_codes,
    new_totp_secret,
    totp_step_now,
)
from src.web import auth, second_step  # noqa: E402

pytestmark = requires_db

ПАРОЛЬ = "пароль-учётки-теста-d463-вторая-ступень"
RP_ID = "admin.example"
ORIGIN = "https://admin.example"
HDR = {"Origin": СВОЙ}
STEP = second_step.STEP_PATH
SECURITY = "/settings/security"


class Стенд:
    def __init__(self, dsn: str, client: FlaskClient) -> None:
        self.dsn = dsn
        self.client = client
        self.ид: dict[str, str] = {}

    def завести(self, логин: str, роль: str) -> str:
        create_account(логин, tenant="HQ", password=ПАРОЛЬ, role=роль)
        учётка = authenticate(логин, ПАРОЛЬ)
        assert учётка is not None
        self.ид[логин] = учётка.id
        return учётка.id

    def sql(self, запрос: str, *параметры: object) -> list[tuple[object, ...]]:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            cur = conn.execute(запрос, параметры)  # type: ignore[arg-type]
            return cur.fetchall() if cur.description else []

    def с_приложением(self, логин: str) -> str:
        """Подключить приложение-аутентификатор человеку напрямую в базе; вернуть секрет."""
        секрет = new_totp_secret()
        uid = self.ид[логин]
        assert sf.begin_totp(uid, секрет)
        assert sf.confirm_totp(uid, step=0)
        return секрет

    def с_кодами(self, логин: str) -> tuple[str, ...]:
        коды = new_backup_codes()
        sf.replace_backup_codes(
            self.ид[логин], tuple(h for k in коды if (h := backup_code_hash(self.ид[логин], k)))
        )
        return коды

    def вход_паролем(self, логин: str) -> object:
        return войти(self.client, login=логин, password=ПАРОЛЬ)

    def новый_браузер(self) -> FlaskClient:
        return self.client.application.test_client()

    def журнал_входов(self, логин: str) -> list[tuple[object, ...]]:
        return self.sql(
            "select j.method, j.result from login_journal j join web_users u on u.id = j.user_id"
            " where u.login = %s order by j.id",
            логин,
        )

    def журнал_действий(self, логин: str) -> list[str]:
        return [
            str(r[0])
            for r in self.sql(
                "select a.action from action_journal a join web_users u on u.id = a.user_id"
                " where u.login = %s order by a.id",
                логин,
            )
        ]


@pytest.fixture
def стенд(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Стенд]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ")
    app = собрать(
        tenant="HQ",
        admin_public_url=ORIGIN,
        mcp_public_url="https://mcp.example/mcp",
        webauthn_rp_id=RP_ID,
        webauthn_origin=ORIGIN,
    )
    with app.test_client() as client:
        группа = Стенд(pg_dsn, client)
        группа.завести("sofia", "superadmin")
        группа.завести("anna", "admin")
        группа.завести("dev", "developer")
        группа.завести("boris", "admin")
        yield группа


def _сессия(client: FlaskClient) -> bool:
    return client.get_cookie(auth.COOKIE_NAME) is not None


def _код(секрет: str, шаг: int) -> str:
    return pyotp.TOTP(секрет).at(шаг * TOTP_INTERVAL_SECONDS)


def _ввести_код(client: FlaskClient, код: str) -> int:
    return client.post(f"{STEP}/code", data={"code": код}, headers=HDR).status_code


# --- полувход не открывает ничего --------------------------------------------


def test_полувход_не_открывает_ни_одного_маршрута(стенд: Стенд) -> None:
    стенд.с_приложением("dev")
    ответ = стенд.вход_паролем("dev")

    assert ответ.status_code == 302  # type: ignore[attr-defined]
    assert STEP in ответ.headers["Location"]  # type: ignore[attr-defined]
    assert not _сессия(стенд.client), "сессия выдана до второй ступени"
    assert стенд.client.get_cookie(second_step.PENDING_COOKIE) is not None
    проверено = 0
    for rule in стенд.client.application.url_map.iter_rules():
        if rule.endpoint in auth.OPEN_ENDPOINTS:
            continue
        путь = rule.rule.replace("<inspection_id>", "11111111-1111-1111-1111-111111111111")
        путь = путь.replace("<passkey_id>", "11111111-1111-1111-1111-111111111111")
        for метод in ("GET", "POST"):
            if метод not in (rule.methods or set()):
                continue
            ответ = стенд.client.open(путь, method=метод, headers=HDR)
            assert ответ.status_code == 302, f"полувход открыл {метод} {путь}"
            assert auth.LOGIN_PATH in (ответ.headers.get("Location") or "")
            проверено += 1
    assert проверено > 20, "перебор маршрутов ничего не проверил"
    assert не_вошёл(стенд.client)


def не_вошёл(client: FlaskClient) -> bool:
    return client.get("/", headers=HDR).status_code == 302 and not _сессия(client)


def test_верный_пароль_без_второго_способа_у_разработчика_даёт_сессию(стенд: Стенд) -> None:
    ответ = стенд.вход_паролем("dev")

    assert ответ.status_code == 302  # type: ignore[attr-defined]
    assert STEP not in ответ.headers["Location"]  # type: ignore[attr-defined]
    assert _сессия(стенд.client)


def test_согласие_claude_требует_второй_ступени(стенд: Стенд) -> None:
    стенд.с_приложением("dev")
    стенд.вход_паролем("dev")

    ответ = стенд.client.get("/oauth/authorize?client_id=x", headers=HDR)

    assert ответ.status_code == 302
    assert auth.LOGIN_PATH in ответ.headers["Location"]


# --- админ без способа: только подключение ----------------------------------------


def test_админ_без_способа_не_заперт(стенд: Стенд) -> None:
    # Блокировка снята 14.10.2026 (ENFORCE_ENROLL выключен): админ без второго способа
    # работает, подключение — рекомендация на экране «Вход и защита».
    ответ = стенд.вход_паролем("anna")
    assert ответ.status_code == 302  # type: ignore[attr-defined]
    assert _сессия(стенд.client)
    for путь in ("/", "/users", "/inspections"):
        r = стенд.client.get(путь, headers=HDR)
        if r.status_code == 302:
            assert SECURITY not in r.headers["Location"], f"{путь} снова запирает админа"
    assert стенд.client.get(SECURITY, headers=HDR).status_code == 200


def test_админ_после_подключения_приложения_работает_дальше(стенд: Стенд) -> None:
    стенд.вход_паролем("anna")
    r = стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)
    assert r.status_code == 200
    секрет = sf.totp_of(стенд.ид["anna"])
    assert секрет is not None
    r = стенд.client.post(
        f"{SECURITY}/totp/confirm",
        data={"code": _код(секрет.secret, totp_step_now())},
        headers=HDR,
    )
    assert r.status_code == 200
    assert стенд.client.get("/settings", headers=HDR).status_code == 200


# --- код приложения -----------------------------------------------------------


def test_верный_код_выдаёт_сессию_а_повтор_того_же_кода_отвергается(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    шаг = totp_step_now()
    стенд.вход_паролем("dev")
    assert _ввести_код(стенд.client, _код(секрет, шаг)) == 302
    assert _сессия(стенд.client)
    assert стенд.client.get(SECURITY, headers=HDR).status_code == 200

    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)
    assert _ввести_код(второй, _код(секрет, шаг)) == 401, "тот же код принят дважды"
    assert not _сессия(второй)
    # Код ШАГОМ ПОЗЖЕ внутри окна — настоящий новый код, он проходит: отказ был именно за повтор.
    assert _ввести_код(второй, _код(секрет, шаг + 1)) == 302
    assert _сессия(второй)


def test_код_старше_принятого_отвергается(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    шаг = totp_step_now()
    стенд.вход_паролем("dev")
    assert _ввести_код(стенд.client, _код(секрет, шаг + 1)) == 302

    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)
    assert _ввести_код(второй, _код(секрет, шаг - 1)) == 401


def test_неверный_код_пишется_в_журнал_и_мёртвый_вход_не_воскресает(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    стенд.вход_паролем("dev")
    for _ in range(MAX_PENDING_FAILURES):
        _ввести_код(стенд.client, "000000")

    # После предела верный код уже не помогает: полувход мёртв.
    r = стенд.client.post(f"{STEP}/code", data={"code": _код(секрет, totp_step_now())}, headers=HDR)
    assert r.status_code == 302
    assert "second_step=expired" in r.headers["Location"]
    assert not _сессия(стенд.client)
    исходы = [x[1] for x in стенд.журнал_входов("dev") if x[0] == "second-step"]
    assert "bad-code" in исходы
    assert "ok" not in исходы


def test_полувход_привязан_к_браузеру(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    стенд.вход_паролем("dev")
    чужой = стенд.новый_браузер()

    r = чужой.post(f"{STEP}/code", data={"code": _код(секрет, totp_step_now())}, headers=HDR)

    assert r.status_code == 302
    assert "expired" in r.headers["Location"]
    assert not _сессия(чужой)


def test_полувход_живёт_пять_минут(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    стенд.вход_паролем("dev")
    стенд.sql("update web_second_steps set expires_at = now() - interval '1 second'")

    r = стенд.client.post(f"{STEP}/code", data={"code": _код(секрет, totp_step_now())}, headers=HDR)

    assert r.status_code == 302
    assert "expired" in r.headers["Location"]
    assert not _сессия(стенд.client)


def test_чужое_происхождение_формы_отвергается(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    стенд.вход_паролем("dev")

    r = стенд.client.post(
        f"{STEP}/code",
        data={"code": _код(секрет, totp_step_now())},
        headers={"Origin": "https://evil.example"},
    )

    assert r.status_code >= 400
    assert not _сессия(стенд.client)


# --- резервные коды ----------------------------------------------------------------


def test_резервный_код_одноразовый(стенд: Стенд) -> None:
    стенд.с_приложением("dev")
    коды = стенд.с_кодами("dev")
    стенд.вход_паролем("dev")
    assert _ввести_код(стенд.client, коды[0]) == 302
    assert _сессия(стенд.client)

    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)
    assert _ввести_код(второй, коды[0]) == 401, "резервный код принят дважды"
    assert _ввести_код(второй, коды[1]) == 302, "другой код того же набора обязан работать"
    assert "backup-used" in [x[1] for x in стенд.журнал_входов("dev")]


def test_новый_набор_гасит_старый(стенд: Стенд) -> None:
    стенд.с_приложением("dev")
    старые = стенд.с_кодами("dev")
    стенд.с_кодами("dev")
    стенд.вход_паролем("dev")

    assert _ввести_код(стенд.client, старые[0]) == 401


# --- ключ доступа ------------------------------------------------------------------


def _подключить_ключ(стенд: Стенд, клиент: FlaskClient, ключ: VirtualAuthenticator) -> None:
    опции = клиент.post(f"{SECURITY}/passkey/options", headers=HDR)
    assert опции.status_code == 200, опции.get_data(as_text=True)
    ответ = клиент.post(
        f"{SECURITY}/passkey/register",
        json={
            "credential": json.loads(ключ.create(опции.get_data(as_text=True), origin=ORIGIN)),
            "name": "Mac",
        },
        headers=HDR,
    )
    assert ответ.status_code == 200, ответ.get_data(as_text=True)


def _вход_ключом(
    клиент: FlaskClient, ключ: VirtualAuthenticator, **порча: object
) -> tuple[int, str]:
    опции = клиент.post(f"{STEP}/passkey/options", headers=HDR)
    assert опции.status_code == 200, опции.get_data(as_text=True)
    параметры: dict[str, object] = {"origin": ORIGIN, **порча}
    тело = ключ.get(опции.get_data(as_text=True), **параметры)  # type: ignore[arg-type]
    ответ = клиент.post(
        f"{STEP}/passkey/verify", data=тело, content_type="application/json", headers=HDR
    )
    return ответ.status_code, тело


@pytest.fixture
def с_ключом(стенд: Стенд) -> VirtualAuthenticator:
    """Разработчик dev с одним подключённым ключом; вход выполнен и закрыт."""
    ключ = VirtualAuthenticator()
    стенд.вход_паролем("dev")
    _подключить_ключ(стенд, стенд.client, ключ)
    стенд.client.post("/logout", headers=HDR)
    стенд.client.delete_cookie(auth.COOKIE_NAME)
    return ключ


def test_вход_ключом_выдаёт_сессию(стенд: Стенд, с_ключом: VirtualAuthenticator) -> None:
    стенд.вход_паролем("dev")
    assert not _сессия(стенд.client)

    код, _ = _вход_ключом(стенд.client, с_ключом)

    assert код == 200
    assert _сессия(стенд.client)
    assert стенд.sql("select sign_count from web_passkeys")[0][0] == 1


def test_откат_счётчика_ключа_отвергается(стенд: Стенд, с_ключом: VirtualAuthenticator) -> None:
    стенд.вход_паролем("dev")
    assert _вход_ключом(стенд.client, с_ключом, counter=5)[0] == 200
    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)

    код, _ = _вход_ключом(второй, с_ключом, counter=3)

    assert код == 401, "клон ключа (счётчик назад) пущен"
    assert not _сессия(второй)
    assert "passkey-fail" in [x[1] for x in стенд.журнал_входов("dev")]


def test_чужое_происхождение_подписи_отвергается(
    стенд: Стенд, с_ключом: VirtualAuthenticator
) -> None:
    стенд.вход_паролем("dev")

    код, _ = _вход_ключом(стенд.client, с_ключом, origin="https://evil.example")

    assert код == 401
    assert not _сессия(стенд.client)


def test_чужой_домен_подписи_отвергается(стенд: Стенд, с_ключом: VirtualAuthenticator) -> None:
    стенд.вход_паролем("dev")

    код, _ = _вход_ключом(стенд.client, с_ключом, rp_id="evil.example")

    assert код == 401
    assert not _сессия(стенд.client)


def test_ключ_без_проверки_человека_отвергается(
    стенд: Стенд, с_ключом: VirtualAuthenticator
) -> None:
    стенд.вход_паролем("dev")

    код, _ = _вход_ключом(стенд.client, с_ключом, user_verified=False)

    assert код == 401


def test_повтор_вызова_ключа_отвергается(стенд: Стенд, с_ключом: VirtualAuthenticator) -> None:
    стенд.вход_паролем("dev")
    код, тело = _вход_ключом(стенд.client, с_ключом)
    assert код == 200
    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)
    # Перехваченный ответ подсовывается в другой полувход без нового вызова.
    assert второй.post(f"{STEP}/passkey/options", headers=HDR).status_code == 200
    повтор = второй.post(
        f"{STEP}/passkey/verify", data=тело, content_type="application/json", headers=HDR
    )
    assert повтор.status_code == 401

    # И внутри одного полувхода: вызов снят первым предъявлением.
    третий = стенд.новый_браузер()
    войти(третий, login="dev", password=ПАРОЛЬ)
    assert третий.post(f"{STEP}/passkey/options", headers=HDR).status_code == 200
    ключ = с_ключом
    опции = третий.post(f"{STEP}/passkey/options", headers=HDR)
    ответ = ключ.get(опции.get_data(as_text=True), origin=ORIGIN)
    assert (
        третий.post(
            f"{STEP}/passkey/verify", data=ответ, content_type="application/json", headers=HDR
        ).status_code
        == 200
    )
    assert not _вызов_жив(стенд)


def _вызов_жив(стенд: Стенд) -> bool:
    return bool(стенд.sql("select 1 from web_webauthn_challenges where purpose = 'authenticate'"))


def test_ключ_чужого_человека_не_закрывает_вторую_ступень(стенд: Стенд) -> None:
    ключ = VirtualAuthenticator()
    стенд.вход_паролем("boris")
    # boris подключает ключ; dev (с приложением, без ключей) чужим ключом не входит.
    _подключить_ключ(стенд, стенд.client, ключ)
    стенд.с_приложением("dev")
    чужой = стенд.новый_браузер()
    войти(чужой, login="dev", password=ПАРОЛЬ)

    ответ = чужой.post(f"{STEP}/passkey/options", headers=HDR)
    assert ответ.status_code == 400  # у dev нет ключей: вызов не выдан
    assert not _сессия(чужой)


# --- подключение: свежесть и последний способ --------------------------------------------


def test_подключение_требует_свежего_входа(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")
    стенд.sql("update web_sessions set issued_at = now() - interval '11 minutes'")

    r = стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)

    assert r.status_code in (302, 401, 403)
    assert not стенд.sql("select 1 from web_totp"), "приложение подключено по несвежему входу"


def test_подключение_по_свежему_входу_проходит(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")

    assert стенд.client.post(f"{SECURITY}/totp/start", headers=HDR).status_code == 200
    assert стенд.sql("select 1 from web_totp")


def test_последний_способ_админа_не_снять(стенд: Стенд) -> None:
    стенд.с_приложением("anna")
    стенд.вход_паролем("anna")
    секрет = sf.totp_of(стенд.ид["anna"])
    assert секрет is not None
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302

    r = стенд.client.post(f"{SECURITY}/totp/remove", headers=HDR)

    assert стенд.sql("select 1 from web_totp"), "последний способ админа снят"
    assert r.status_code == 200


def test_разработчик_свой_последний_способ_снимает(стенд: Стенд) -> None:
    стенд.с_приложением("dev")
    секрет = sf.totp_of(стенд.ид["dev"])
    assert секрет is not None
    стенд.вход_паролем("dev")
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302

    стенд.client.post(f"{SECURITY}/totp/remove", headers=HDR)

    assert not стенд.sql("select 1 from web_totp")


# --- аудит экрана «Вход и защита»: окно, снятие, чужие сессии ----------------------------


def _состарить_сессии(стенд: Стенд, минут: int) -> None:
    стенд.sql("update web_sessions set issued_at = now() - make_interval(mins => %s)", минут)


def test_админ_без_способа_подключает_только_в_первые_пять_минут(стенд: Стенд) -> None:
    стенд.вход_паролем("anna")
    _состарить_сессии(стенд, 6)

    r = стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)

    assert r.status_code in (302, 401, 403), (
        "окно подключения первого способа админа длиннее 5 минут"
    )
    assert not стенд.sql("select 1 from web_totp")
    _состарить_сессии(стенд, 4)
    assert стенд.client.post(f"{SECURITY}/totp/start", headers=HDR).status_code == 200


def test_разработчик_без_способа_подключает_и_на_седьмой_минуте(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")
    _состарить_сессии(стенд, 7)

    assert стенд.client.post(f"{SECURITY}/totp/start", headers=HDR).status_code == 200


def test_сессия_первой_ступени_снять_способ_не_может(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")
    стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)
    секрет = sf.totp_of(стенд.ид["dev"])
    assert секрет is not None
    r = стенд.client.post(
        f"{SECURITY}/totp/confirm",
        data={"code": _код(секрет.secret, totp_step_now())},
        headers=HDR,
    )
    assert r.status_code == 200

    стенд.client.post(f"{SECURITY}/totp/remove", headers=HDR)

    assert стенд.sql("select 1 from web_totp"), "сессия без второй ступени сняла способ"


def test_снятие_ключа_сессией_без_второй_ступени_отвергается(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")
    ключ = VirtualAuthenticator()
    _подключить_ключ(стенд, стенд.client, ключ)
    ид = str(стенд.sql("select id from web_passkeys")[0][0])

    стенд.client.post(f"{SECURITY}/passkey/{ид}/delete", headers=HDR)

    assert стенд.sql("select 1 from web_passkeys"), "сессия без второй ступени сняла ключ"


def test_снятие_несвежей_сессией_после_второй_ступени_отвергается(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    стенд.вход_паролем("dev")
    assert _ввести_код(стенд.client, _код(секрет, totp_step_now())) == 302
    _состарить_сессии(стенд, 11)

    стенд.client.post(f"{SECURITY}/totp/remove", headers=HDR)

    assert стенд.sql("select 1 from web_totp")


def test_чужой_номер_ключа_в_адресе_ничего_не_снимает(стенд: Стенд) -> None:
    чужой = VirtualAuthenticator()
    стенд.вход_паролем("boris")
    _подключить_ключ(стенд, стенд.client, чужой)
    ид = str(стенд.sql("select id from web_passkeys")[0][0])
    секрет = стенд.с_приложением("dev")
    второй = стенд.новый_браузер()
    войти(второй, login="dev", password=ПАРОЛЬ)
    assert _ввести_код(второй, _код(секрет, totp_step_now())) == 302

    второй.post(f"{SECURITY}/passkey/{ид}/delete", headers=HDR)

    assert стенд.sql("select 1 from web_passkeys"), "ключ другого человека снят по номеру"


def test_изменяющие_маршруты_экрана_не_открываются_get_и_чужим_происхождением(
    стенд: Стенд,
) -> None:
    стенд.вход_паролем("dev")
    for путь in ("totp/start", "totp/confirm", "totp/remove", "backup/generate", "passkey/options"):
        assert стенд.client.get(f"{SECURITY}/{путь}", headers=HDR).status_code == 405, путь
        r = стенд.client.post(f"{SECURITY}/{путь}", headers={"Origin": "https://evil.example"})
        assert r.status_code >= 400, путь
    assert not стенд.sql("select 1 from web_totp")


def test_первый_способ_закрывает_другие_сессии_человека(стенд: Стенд) -> None:
    # Сессия «угонщика»: открыта первой ступенью раньше, чем хозяин подключил способ.
    угонщик = стенд.новый_браузер()
    войти(угонщик, login="anna", password=ПАРОЛЬ)
    assert _сессия(угонщик)
    стенд.вход_паролем("anna")
    стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)
    секрет = sf.totp_of(стенд.ид["anna"])
    assert секрет is not None
    r = стенд.client.post(
        f"{SECURITY}/totp/confirm",
        data={"code": _код(секрет.secret, totp_step_now())},
        headers=HDR,
    )
    assert r.status_code == 200

    assert угонщик.get(SECURITY, headers=HDR).status_code == 302, (
        "чужая сессия пережила подключение"
    )
    assert стенд.client.get(SECURITY, headers=HDR).status_code == 200


def test_сброс_чужой_ступени_сессией_без_второй_ступени_отвергается(стенд: Стенд) -> None:
    стенд.с_приложением("anna")
    стенд.вход_паролем("sofia")
    стенд.client.post(f"{SECURITY}/totp/start", headers=HDR)
    секрет = sf.totp_of(стенд.ид["sofia"])
    assert секрет is not None
    стенд.client.post(
        f"{SECURITY}/totp/confirm",
        data={"code": _код(секрет.secret, totp_step_now())},
        headers=HDR,
    )

    r = стенд.client.post(
        "/users/reset-second-factor", data={"login": "anna", "tenant": "HQ"}, headers=HDR
    )

    assert r.status_code == 403
    assert стенд.sql("select 1 from web_totp where user_id = %s", стенд.ид["anna"])


# --- сброс главным админом и командой ---------------------------------------------------


def test_главный_админ_сбрасывает_чужую_ступень_и_это_в_журнале(стенд: Стенд) -> None:
    стенд.с_приложением("anna")
    стенд.с_кодами("anna")
    стенд.с_приложением("sofia")
    секрет = sf.totp_of(стенд.ид["sofia"])
    assert секрет is not None
    стенд.вход_паролем("sofia")
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302

    r = стенд.client.post(
        "/users/reset-second-factor", data={"login": "anna", "tenant": "HQ"}, headers=HDR
    )

    assert r.status_code == 200
    assert not стенд.sql("select 1 from web_totp where user_id = %s", стенд.ид["anna"])
    assert not стенд.sql("select 1 from web_backup_codes where user_id = %s", стенд.ид["anna"])
    assert "reset_second_factor" in стенд.журнал_действий("sofia")


def test_админ_чужую_ступень_не_сбрасывает(стенд: Стенд) -> None:
    стенд.с_приложением("boris")
    стенд.с_приложением("anna")
    секрет = sf.totp_of(стенд.ид["anna"])
    assert секрет is not None
    стенд.вход_паролем("anna")
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302

    r = стенд.client.post(
        "/users/reset-second-factor", data={"login": "boris", "tenant": "HQ"}, headers=HDR
    )

    assert r.status_code in (302, 403)
    assert стенд.sql("select 1 from web_totp where user_id = %s", стенд.ид["boris"])


def test_главный_админ_себя_через_экран_не_сбрасывает(стенд: Стенд) -> None:
    стенд.с_приложением("sofia")
    секрет = sf.totp_of(стенд.ид["sofia"])
    assert секрет is not None
    стенд.вход_паролем("sofia")
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302

    r = стенд.client.post(
        "/users/reset-second-factor", data={"login": "sofia", "tenant": "HQ"}, headers=HDR
    )

    assert r.status_code == 400
    assert стенд.sql("select 1 from web_totp where user_id = %s", стенд.ид["sofia"])


def test_сброс_закрывает_открытые_сессии_человека(стенд: Стенд) -> None:
    стенд.с_приложением("anna")
    секрет = sf.totp_of(стенд.ид["anna"])
    assert секрет is not None
    стенд.вход_паролем("anna")
    assert _ввести_код(стенд.client, _код(секрет.secret, totp_step_now())) == 302
    assert стенд.client.get("/settings", headers=HDR).status_code == 200

    out = sf.reset_by_login("anna", tenant="HQ")

    assert out is not None
    assert out.removed == 1
    assert стенд.client.get("/settings", headers=HDR).status_code == 302


def test_сброс_несуществующей_учётки_ничего_не_делает(стенд: Стенд) -> None:
    assert sf.reset_by_login("никто", tenant="HQ") is None


# --- ограничитель попыток ----------------------------------------------------------


def test_перебор_кодов_упирается_в_ограничитель_а_не_в_пароль(стенд: Стенд) -> None:
    секрет = стенд.с_приложением("dev")
    статусы: list[int] = []
    for _ in range(12):
        # Удачный пароль каждый раз: общий счётчик с паролем сбрасывался бы, отдельный — нет.
        браузер = стенд.новый_браузер()
        войти(браузер, login="dev", password=ПАРОЛЬ)
        статусы.append(_ввести_код(браузер, "000000"))
    assert 429 in статусы, "перебор кода не упёрся в ограничитель"
    браузер = стенд.новый_браузер()
    войти(браузер, login="dev", password=ПАРОЛЬ)
    assert _ввести_код(браузер, _код(секрет, totp_step_now())) == 429
    assert not _сессия(браузер)


def test_время_шага_не_уходит_в_будущее_случайно() -> None:
    assert totp_step_now(datetime.now(UTC)) > 0


def test_страница_подтверждения_сама_запускает_ключ_когда_он_есть(
    стенд: Стенд, с_ключом: VirtualAuthenticator
) -> None:
    стенд.вход_паролем("dev")

    страница = стенд.client.get(STEP).get_data(as_text=True)

    assert "data-passkey-autostart" in страница


def test_после_неверного_кода_ключ_сам_не_запускается(
    стенд: Стенд, с_ключом: VirtualAuthenticator
) -> None:
    """Осечка не должна вызывать окно ключа по кругу."""
    стенд.вход_паролем("dev")
    стенд.client.post(f"{STEP}/code", data={"code": "000000"}, headers=HDR)

    страница = стенд.client.post(f"{STEP}/code", data={"code": "000000"}, headers=HDR).get_data(
        as_text=True
    )

    assert "data-passkey-button" in страница
    assert "data-passkey-autostart" not in страница


def test_плашка_подключения_видна_админу_без_способа_но_не_на_экране_защиты(стенд: Стенд) -> None:
    стенд.завести("adm", "admin")
    войти(стенд.client, login="adm", password=ПАРОЛЬ)

    другая = стенд.client.get("/settings", follow_redirects=True).get_data(as_text=True)
    защита = стенд.client.get(SECURITY).get_data(as_text=True)

    assert "data-enroll-banner" in другая
    assert "data-enroll-banner" not in защита
