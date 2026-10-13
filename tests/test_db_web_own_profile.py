"""Свой профиль из «Настроек» (D447) — уровень базы: почта Google и язык сайта.

Пишут функции базы (`0061`) под ролью приложения; строку учётки каждая
выбирает по ЖИВОЙ СЕССИИ, чей токен ей предъявлен. Здесь проверяется то, что
держит база, а не экран: метка привязки одноразовая и своя, почта уникальна,
снятие почты требует действующего пароля, остальные сессии закрываются.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    create_account,
    disable_account,
    find_by_email,
    open_session,
    resolve_session,
    set_email,
)
from src.db.web_own_profile import (  # noqa: E402
    begin_google_link,
    finish_google_link,
    own_avatar,
    save_google_profile,
    set_web_lang,
    unlink_google,
)

pytestmark = requires_db

ТЕНАНТ = "HQ"
ПАРОЛЬ = "верный-пароль-учётки"
ПОЧТА = "director@dodobrands.io"
МЕТКА = "метка-захода-привязки"
СРОК = 600


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Учётки заводит владелец, а свой профиль правит роль приложения."""
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return pg_dsn


def test_привязка_своей_сессией_пишет_почту_и_закрывает_остальные_входы(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    своя = open_session(учётка)
    другая = open_session(учётка)

    assert begin_google_link(своя.token, state=МЕТКА, ttl_seconds=СРОК) is True
    assert finish_google_link(своя.token, state=МЕТКА, email=" Director@Dodobrands.io ") == "ok"

    найдена = find_by_email(ПОЧТА)
    assert найдена is not None and найдена.login == "director"
    assert resolve_session(своя.token) is not None
    assert resolve_session(другая.token) is None, "вошедший по утёкшему паролю пережил привязку"


def test_метка_чужой_сессии_ничего_не_привязывает(обе_роли: str) -> None:
    """Возврат от Google в другой сессии — даже той же учётки — метку не гасит."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сосед = create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    начавшая = open_session(учётка)
    чужая = open_session(сосед)
    begin_google_link(начавшая.token, state=МЕТКА, ttl_seconds=СРОК)

    assert finish_google_link(чужая.token, state=МЕТКА, email=ПОЧТА) == "state"
    assert find_by_email(ПОЧТА) is None


def test_повтор_метки_не_проходит(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    begin_google_link(сессия.token, state=МЕТКА, ttl_seconds=СРОК)
    assert finish_google_link(сессия.token, state=МЕТКА, email=ПОЧТА) == "ok"
    assert unlink_google(сессия.token, current=ПАРОЛЬ) == "ok"

    assert finish_google_link(сессия.token, state=МЕТКА, email=ПОЧТА) == "state"
    assert find_by_email(ПОЧТА) is None


def test_незаписанная_метка_не_проходит(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    assert finish_google_link(сессия.token, state="с-потолка", email=ПОЧТА) == "state"


def test_занятая_почта_не_привязывается_и_метка_гаснет(обе_роли: str) -> None:
    create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("petr", tenant=ТЕНАНТ, email=ПОЧТА)
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    begin_google_link(сессия.token, state=МЕТКА, ttl_seconds=СРОК)

    assert finish_google_link(сессия.token, state=МЕТКА, email=ПОЧТА) == "taken"
    assert finish_google_link(сессия.token, state=МЕТКА, email="other@dodobrands.io") == "state"
    найдена = find_by_email(ПОЧТА)
    assert найдена is not None and найдена.login == "petr"


def test_уже_привязанная_почта_не_перезаписывается(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)
    учётка = find_by_email(ПОЧТА)
    assert учётка is not None
    сессия = open_session(учётка)
    begin_google_link(сессия.token, state=МЕТКА, ttl_seconds=СРОК)

    assert finish_google_link(сессия.token, state=МЕТКА, email="new@dodobrands.io") == "linked"
    assert find_by_email(ПОЧТА) is not None


def test_отключённая_учётка_не_привязывает(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    begin_google_link(сессия.token, state=МЕТКА, ttl_seconds=СРОК)
    disable_account("director", tenant=ТЕНАНТ)

    assert finish_google_link(сессия.token, state=МЕТКА, email=ПОЧТА) == "session"
    assert begin_google_link(сессия.token, state="вторая", ttl_seconds=СРОК) is False


def test_снятие_без_верного_пароля_не_снимает(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)
    учётка = find_by_email(ПОЧТА)
    assert учётка is not None
    сессия = open_session(учётка)
    другая = open_session(учётка)

    assert unlink_google(сессия.token, current="не-тот-пароль") == "denied"
    assert find_by_email(ПОЧТА) is not None

    assert unlink_google(сессия.token, current=ПАРОЛЬ) == "ok"
    assert find_by_email(ПОЧТА) is None
    assert resolve_session(сессия.token) is not None
    assert resolve_session(другая.token) is None
    assert unlink_google(сессия.token, current=ПАРОЛЬ) == "none"


def test_функция_снятия_не_верит_хешу_чужой_учётки(обе_роли: str, db_env: str) -> None:
    """Хеш соседа, поданный со своим токеном, не снимает ничего: сверка — по своей строке."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    create_account("petr", tenant=ТЕНАНТ, password="другой-пароль-соседа")
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)
    учётка = find_by_email(ПОЧТА)
    assert учётка is not None
    сессия = open_session(учётка)
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute("select password_hash from web_users where login = 'petr'")
        (хеш_соседа,) = cur.fetchone()  # type: ignore[misc]

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("select unlink_own_google(%s, %s)", (сессия.token, хеш_соседа))
        assert cur.fetchone() == ("denied",)
    assert find_by_email(ПОЧТА) is not None


def test_роль_приложения_не_пишет_почту_и_не_видит_меток(обе_роли: str, db_env: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("update web_users set email = 'x@y.z' where login = 'director'")
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("select count(*) from web_google_link_states")


def test_язык_сайта_хранится_за_учёткой(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    сосед = open_session(create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ))
    before = resolve_session(сессия.token)
    assert before is not None and before.web_lang is None

    assert set_web_lang(сессия.token, "en") is True

    after = resolve_session(сессия.token)
    assert after is not None and after.web_lang == "en"
    соседа = resolve_session(сосед.token)
    assert соседа is not None and соседа.web_lang is None
    with pytest.raises(AccessError):
        set_web_lang(сессия.token, "english")
    assert set_web_lang("нет-такой-сессии", "ru") is False


# ── Имя и фото из Google (D468, 0064) ─────────────────────────────────

ФОТО = b"\xff\xd8\xff\xe0" + b"photo-of-director"
ФОТО_ДРУГОГО = b"\x89PNG\r\n\x1a\n" + b"photo-of-somebody"


def test_имя_и_фото_пишутся_своей_учётке_и_приезжают_с_сессией(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    assert save_google_profile(
        сессия.token, name=" Иван Петров ", avatar=ФОТО, avatar_type="image/jpeg"
    )

    вошедший = resolve_session(сессия.token)
    assert вошедший is not None
    assert вошедший.display_name == "Иван Петров"
    assert вошедший.avatar_etag is not None and len(вошедший.avatar_etag) == 16
    assert own_avatar(сессия.token) == (ФОТО, "image/jpeg", вошедший.avatar_etag)


def test_своё_фото_отдаётся_по_сессии_а_чужое_нет(обе_роли: str) -> None:
    первая = open_session(create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ))
    вторая = open_session(create_account("other", tenant=ТЕНАНТ, password=ПАРОЛЬ))
    save_google_profile(первая.token, name="Первый", avatar=ФОТО, avatar_type="image/jpeg")
    save_google_profile(вторая.token, name="Второй", avatar=ФОТО_ДРУГОГО, avatar_type="image/png")

    assert own_avatar(первая.token) is not None and own_avatar(первая.token)[0] == ФОТО
    assert own_avatar(вторая.token) is not None and own_avatar(вторая.token)[0] == ФОТО_ДРУГОГО
    assert own_avatar("токен-которого-нет") is None


def test_запись_без_живой_сессии_ничего_не_пишет(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)

    assert (
        save_google_profile("чужой-токен", name="Взломщик", avatar=ФОТО, avatar_type="image/jpeg")
        is False
    )
    вошедший = resolve_session(сессия.token)
    assert вошедший is not None and вошедший.display_name is None and вошедший.avatar_etag is None


def test_пустое_значение_прежнее_не_затирает(обе_роли: str) -> None:
    сессия = open_session(create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ))
    save_google_profile(сессия.token, name="Иван Петров", avatar=ФОТО, avatar_type="image/jpeg")

    save_google_profile(сессия.token, name=None, avatar=None, avatar_type=None)
    save_google_profile(сессия.token, name="  ", avatar=None, avatar_type=None)

    вошедший = resolve_session(сессия.token)
    assert вошедший is not None and вошедший.display_name == "Иван Петров"
    assert own_avatar(сессия.token) is not None


def test_фото_выше_предела_база_не_принимает(обе_роли: str) -> None:
    сессия = open_session(create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ))

    with pytest.raises(AccessError):
        save_google_profile(
            сессия.token, name=None, avatar=ФОТО + b"\x00" * 204800, avatar_type="image/jpeg"
        )


def test_роль_приложения_сама_колонки_профиля_не_пишет(обе_роли: str, pg_dsn: str) -> None:
    """Запись — только функцией по сессии: прямой `update` ролью приложения отказан."""
    from src.db.config import check_environment
    from src.db.pool import connection

    open_session(create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ))

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        connection(check_environment().dsn) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("update web_users set display_name = 'Взломщик'")
