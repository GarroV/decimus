"""Вторая ступень входа (D463, миграция `0068`) — уровень базы.

Ядро доступа: ошибка здесь молчалива (чужой код принят дважды, полувход открыл дверь,
последний способ админа снят). Каждое «ровно один раз» проверяется на живой базе под
ролью приложения (`db_env`), как на площадке.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db import second_factor as sf  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    create_account,
    freeze_account,
    open_session,
    resolve_session,
)
from src.domain.second_factor import (  # noqa: E402
    MAX_PENDING_FAILURES,
    backup_code_hash,
    new_backup_codes,
    new_totp_secret,
)

pytestmark = requires_db

ПАРОЛЬ = "пароль-учётки-теста-d463-вторая-ступень"


class Люди:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.ид: dict[str, str] = {}

    def завести(self, логин: str, роль: str) -> str:
        create_account(логин, tenant="HQ", password=ПАРОЛЬ, role=роль)
        учётка = authenticate(логин, ПАРОЛЬ)
        assert учётка is not None
        self.ид[логин] = учётка.id
        return учётка.id

    def sql(self, запрос: str, *параметры: object) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(запрос, параметры)  # type: ignore[arg-type]

    def rows(self, запрос: str) -> list[tuple[object, ...]]:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            return conn.execute(запрос).fetchall()  # type: ignore[arg-type]


@pytest.fixture
def люди(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> Люди:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "HQ")
    группа = Люди(pg_dsn)
    группа.завести("sofia", "superadmin")
    группа.завести("anna", "admin")
    группа.завести("dev", "developer")
    return группа


def _ключ(кто: str, n: int = 1) -> dict[str, object]:
    return {
        "credential_id": f"cred-{кто}-{n}".encode(),
        "public_key": b"pk",
        "sign_count": 0,
        "transports": ("internal",),
        "name": f"Ключ {n}",
    }


# --- полупройденный вход ---------------------------------------------------------


def test_полувход_гасится_один_раз(люди: Люди) -> None:
    токен = sf.open_pending(люди.ид["anna"], method="password", next_path="/settings")
    assert sf.find_pending(токен) is not None
    первый = sf.consume_pending(токен)
    второй = sf.consume_pending(токен)
    assert первый is not None and первый.user_id == люди.ид["anna"]
    assert первый.next_path == "/settings"
    assert второй is None, "погашенный полувход прошёл второй раз"
    assert sf.find_pending(токен) is None


def test_просроченный_полувход_мёртв(люди: Люди) -> None:
    токен = sf.open_pending(люди.ид["anna"], method="google", next_path=None)
    люди.sql("update web_second_steps set expires_at = now() - interval '1 second'")
    assert sf.find_pending(токен) is None
    assert sf.consume_pending(токен) is None


def test_полувход_мёртв_после_пяти_неудач(люди: Люди) -> None:
    токен = sf.open_pending(люди.ид["anna"], method="password", next_path=None)
    for _ in range(MAX_PENDING_FAILURES):
        assert sf.find_pending(токен) is not None
        sf.note_pending_failure(токен)
    assert sf.find_pending(токен) is None
    assert sf.consume_pending(токен) is None, "мёртвый полувход погасился и открыл бы вход"


def test_чужой_токен_полувхода_не_находится(люди: Люди) -> None:
    sf.open_pending(люди.ид["anna"], method="password", next_path=None)
    assert sf.find_pending("чужой-токен") is None
    assert sf.consume_pending("чужой-токен") is None


# --- резервные коды --------------------------------------------------------------


def test_резервный_код_одноразовый(люди: Люди) -> None:
    коды = new_backup_codes()
    uid = люди.ид["anna"]
    sf.replace_backup_codes(uid, tuple(h for k in коды if (h := backup_code_hash(uid, k))))
    h = backup_code_hash(uid, коды[0])
    assert h is not None
    assert sf.use_backup_code(uid, h) is True
    assert sf.use_backup_code(uid, h) is False, "резервный код сработал дважды"
    assert sf.status_of(uid).backup_left == len(коды) - 1


def test_новый_набор_гасит_прежние_коды(люди: Люди) -> None:
    uid = люди.ид["anna"]
    старые = new_backup_codes()
    sf.replace_backup_codes(uid, tuple(h for k in старые if (h := backup_code_hash(uid, k))))
    новые = new_backup_codes()
    sf.replace_backup_codes(uid, tuple(h for k in новые if (h := backup_code_hash(uid, k))))
    h = backup_code_hash(uid, старые[0])
    assert h is not None
    assert sf.use_backup_code(uid, h) is False, "код из прежнего набора остался действующим"


def test_резервный_код_чужой_учётки_не_гасится(люди: Люди) -> None:
    коды = new_backup_codes()
    sf.replace_backup_codes(
        люди.ид["anna"],
        tuple(h for k in коды if (h := backup_code_hash(люди.ид["anna"], k))),
    )
    чужой = backup_code_hash(люди.ид["dev"], коды[0])
    assert чужой is not None
    assert sf.use_backup_code(люди.ид["dev"], чужой) is False


# --- TOTP ------------------------------------------------------------------------


def test_шаг_totp_повторно_не_принимается(люди: Люди) -> None:
    uid = люди.ид["anna"]
    assert sf.begin_totp(uid, new_totp_secret()) is True
    assert sf.confirm_totp(uid, step=1000) is True
    assert sf.accept_totp_step(uid, step=1001) is True
    assert sf.accept_totp_step(uid, step=1001) is False, "тот же код принят повторно"
    assert sf.accept_totp_step(uid, step=1000) is False, "код старее принятого принят"
    assert sf.accept_totp_step(uid, step=1002) is True


def test_неподтверждённое_приложение_не_способ_входа(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.begin_totp(uid, new_totp_secret())
    assert sf.has_any(uid) is False
    assert sf.accept_totp_step(uid, step=5) is False
    assert sf.status_of(uid).totp_pending is True


def test_подтверждённое_приложение_не_перезаписывается(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.begin_totp(uid, new_totp_secret())
    sf.confirm_totp(uid, step=1)
    assert sf.begin_totp(uid, new_totp_secret()) is False


# --- ключи доступа ---------------------------------------------------------------


def test_счётчик_ключа_принимается_только_от_прежнего(люди: Люди) -> None:
    ключ = sf.add_passkey(люди.ид["anna"], **_ключ("anna"))  # type: ignore[arg-type]
    assert sf.touch_passkey(ключ.id, old_count=0, new_count=5) is True
    assert sf.touch_passkey(ключ.id, old_count=0, new_count=6) is False, "гонка выиграла дважды"
    найден = sf.passkey_by_credential(ключ.credential_id)
    assert найден is not None and найден[0].sign_count == 5
    assert найден[1] == люди.ид["anna"]


def test_вызов_ключа_снимается_один_раз(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.store_challenge("привязка", purpose=sf.PURPOSE_AUTHENTICATE, user_id=uid, challenge=b"abc")
    assert sf.take_challenge("привязка", purpose=sf.PURPOSE_AUTHENTICATE, user_id=uid) == b"abc"
    assert sf.take_challenge("привязка", purpose=sf.PURPOSE_AUTHENTICATE, user_id=uid) is None


def test_вызов_чужой_привязки_и_чужого_человека_не_снимается(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.store_challenge("привязка", purpose=sf.PURPOSE_AUTHENTICATE, user_id=uid, challenge=b"abc")
    assert sf.take_challenge("другая", purpose=sf.PURPOSE_AUTHENTICATE, user_id=uid) is None
    assert sf.take_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid) is None
    assert (
        sf.take_challenge("привязка", purpose=sf.PURPOSE_AUTHENTICATE, user_id=люди.ид["dev"])
        is None
    )


def test_просроченный_вызов_не_снимается(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.store_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid, challenge=b"abc")
    люди.sql("update web_webauthn_challenges set expires_at = now() - interval '1 second'")
    assert sf.take_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid) is None


def test_новый_вызов_вытесняет_прежний(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.store_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid, challenge=b"one")
    sf.store_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid, challenge=b"two")
    assert sf.take_challenge("привязка", purpose=sf.PURPOSE_REGISTER, user_id=uid) == b"two"


# --- последний способ админа -----------------------------------------------------


def test_админу_последний_ключ_не_снять(люди: Люди) -> None:
    ключ = sf.add_passkey(люди.ид["anna"], **_ключ("anna"))  # type: ignore[arg-type]
    assert sf.remove_passkey(люди.ид["anna"], ключ.id) == sf.LAST_FACTOR
    assert sf.has_any(люди.ид["anna"]) is True


def test_админу_последнее_приложение_не_снять_а_с_ключом_можно(люди: Люди) -> None:
    uid = люди.ид["sofia"]
    sf.begin_totp(uid, new_totp_secret())
    sf.confirm_totp(uid, step=1)
    assert sf.remove_totp(uid) == sf.LAST_FACTOR
    ключ = sf.add_passkey(uid, **_ключ("sofia"))  # type: ignore[arg-type]
    assert sf.remove_totp(uid) == sf.REMOVED
    assert sf.remove_passkey(uid, ключ.id) == sf.LAST_FACTOR


def test_админ_с_двумя_ключами_снимает_один(люди: Люди) -> None:
    uid = люди.ид["anna"]
    первый = sf.add_passkey(uid, **_ключ("anna", 1))  # type: ignore[arg-type]
    sf.add_passkey(uid, **_ключ("anna", 2))  # type: ignore[arg-type]
    assert sf.remove_passkey(uid, первый.id) == sf.REMOVED
    assert len(sf.status_of(uid).passkeys) == 1


def test_не_админу_последний_способ_снять_можно(люди: Люди) -> None:
    uid = люди.ид["dev"]
    ключ = sf.add_passkey(uid, **_ключ("dev"))  # type: ignore[arg-type]
    assert sf.remove_passkey(uid, ключ.id) == sf.REMOVED
    assert sf.has_any(uid) is False


def test_чужой_ключ_своей_рукой_не_снимается(люди: Люди) -> None:
    ключ = sf.add_passkey(люди.ид["anna"], **_ключ("anna"))  # type: ignore[arg-type]
    sf.add_passkey(люди.ид["dev"], **_ключ("dev"))  # type: ignore[arg-type]
    assert sf.remove_passkey(люди.ид["dev"], ключ.id) == sf.MISSING
    assert len(sf.status_of(люди.ид["anna"]).passkeys) == 1


# --- сброс и сессия --------------------------------------------------------------


def test_сброс_снимает_всё_и_полувход(люди: Люди) -> None:
    uid = люди.ид["anna"]
    sf.add_passkey(uid, **_ключ("anna"))  # type: ignore[arg-type]
    sf.begin_totp(uid, new_totp_secret())
    sf.confirm_totp(uid, step=1)
    sf.replace_backup_codes(uid, ("0" * 64,))
    токен = sf.open_pending(uid, method="password", next_path=None)
    assert sf.reset_all(uid) == 2
    состояние = sf.status_of(uid)
    assert not состояние.has_factor and состояние.backup_left == 0
    assert sf.find_pending(токен) is None


def test_сессия_знает_есть_ли_вторая_ступень(люди: Люди) -> None:
    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    открыта = open_session(учётка)
    токен = открыта.token
    до = resolve_session(токен)
    assert до is not None and до.has_second_factor is False
    assert до.passed_second_step is False
    sf.add_passkey(
        учётка.id,
        keep_session_id=открыта.session_id,
        **_ключ("anna"),  # type: ignore[arg-type]
    )
    после = resolve_session(токен)
    assert после is not None and после.has_second_factor is True


def test_первый_способ_закрывает_прочие_сессии_но_не_свою(люди: Люди) -> None:
    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    своя = open_session(учётка)
    чужая = open_session(учётка)

    sf.add_passkey(
        учётка.id,
        keep_session_id=своя.session_id,
        **_ключ("anna"),  # type: ignore[arg-type]
    )

    assert resolve_session(своя.token) is not None
    assert resolve_session(чужая.token) is None
    # Второй способ уже не первый: сессии не трогаются.
    третья = open_session(учётка, second_step=True)
    sf.add_passkey(
        учётка.id,
        keep_session_id=своя.session_id,
        **_ключ("anna", 2),  # type: ignore[arg-type]
    )
    assert resolve_session(третья.token) is not None


def test_сессия_после_второй_ступени_помечена(люди: Люди) -> None:
    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None

    обычная = resolve_session(open_session(учётка).token)
    после = resolve_session(open_session(учётка, second_step=True).token)

    assert обычная is not None and обычная.passed_second_step is False
    assert после is not None and после.passed_second_step is True


def test_замороженный_не_находится_для_второй_ступени(люди: Люди) -> None:
    from src.db.web_access import find_by_id

    assert find_by_id(люди.ид["dev"]) is not None
    freeze_account("dev", tenant="HQ")
    assert find_by_id(люди.ид["dev"]) is None


def test_журнал_входов_принимает_вторую_ступень(люди: Люди) -> None:
    from src.db import journals

    for результат in ("ok", "bad-code", "passkey-fail", "backup-used"):
        journals.record_login(
            method="second-step", result=результат, user_id=люди.ид["anna"], ip="203.0.113.7"
        )
    with psycopg.connect(люди.dsn) as conn:
        число = conn.execute(
            "select count(*) from login_journal where method = 'second-step'"
        ).fetchone()
    assert число is not None and число[0] == 4


def test_полная_сессия_человеку_со_способом_без_второй_ступени_не_выдаётся(люди: Люди) -> None:
    from src.db.errors import SecondStepRequiredError

    учётка = authenticate("anna", ПАРОЛЬ)
    assert учётка is not None
    assert open_session(учётка) is not None  # способа нет: сессия (для админа — только подключение)
    sf.add_passkey(учётка.id, **_ключ("anna"))  # type: ignore[arg-type]

    with pytest.raises(SecondStepRequiredError):
        open_session(учётка)
    assert open_session(учётка, second_step=True) is not None


# --- ключи, которыми не входили (D485) ----------------------------------------------


def test_простаивающий_ключ_снимается_а_свежий_и_недавно_использованный_остаются(
    люди: Люди,
) -> None:
    from src.bot import upload_sweeper

    uid = люди.ид["anna"]
    старый = sf.add_passkey(uid, **_ключ("anna", 1))  # type: ignore[arg-type]
    забытый = sf.add_passkey(uid, **_ключ("anna", 2))  # type: ignore[arg-type]
    недавний = sf.add_passkey(uid, **_ключ("anna", 3))  # type: ignore[arg-type]
    свежий = sf.add_passkey(uid, **_ключ("anna", 4))  # type: ignore[arg-type]
    # Снимаются: 60 дней и ни разу не использован; 45 дней без входа. Остаются: входили вчера
    # (хотя создан 90 дней назад) и только что созданный.
    люди.sql(
        "update web_passkeys set created_at = now() - interval '60 days' where id = %s", старый.id
    )
    люди.sql(
        "update web_passkeys set created_at = now() - interval '90 days',"
        " last_used_at = now() - interval '45 days' where id = %s",
        забытый.id,
    )
    люди.sql(
        "update web_passkeys set created_at = now() - interval '90 days',"
        " last_used_at = now() - interval '1 day' where id = %s",
        недавний.id,
    )

    снято = upload_sweeper.purge_idle_passkeys_once()

    assert снято == 2
    оставшиеся = {k.id for k in sf.status_of(uid).passkeys}
    assert оставшиеся == {недавний.id, свежий.id}, "снят не тот ключ"
    записи = люди.rows("select action, target from action_journal where action = 'passkey_expired'")
    assert записи == [("passkey_expired", "keys=2")]


# --- первый способ: проверка и вставка в одной транзакции (D485) ---------------------


def test_первым_объявленный_ключ_не_пишется_если_способ_уже_есть(люди: Люди) -> None:
    uid = люди.ид["dev"]
    sf.add_passkey(uid, **_ключ("dev", 1))  # type: ignore[arg-type]

    with pytest.raises(sf.NotFirstFactorError):
        sf.add_passkey(uid, only_if_first=True, **_ключ("dev", 2))  # type: ignore[arg-type]

    assert len(sf.status_of(uid).passkeys) == 1


def test_два_параллельных_первых_ключа_записывается_ровно_один(люди: Люди) -> None:
    from concurrent.futures import ThreadPoolExecutor

    uid = люди.ид["dev"]

    def попытка(n: int) -> bool:
        try:
            sf.add_passkey(uid, only_if_first=True, **_ключ("dev", n))  # type: ignore[arg-type]
        except sf.NotFirstFactorError:
            return False
        return True

    for круг in range(5):
        люди.sql("delete from web_passkeys where user_id = %s", uid)
        with ThreadPoolExecutor(max_workers=4) as пул:
            исходы = list(пул.map(попытка, [круг * 10 + i for i in range(4)]))
        assert sum(исходы) == 1, f"«первым» записалось {sum(исходы)} способов: {исходы}"
        assert len(sf.status_of(uid).passkeys) == 1
