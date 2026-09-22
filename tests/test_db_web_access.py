"""T323: учётки и сессии веб-админки (`src/db/web_access.py`) — уровень базы.

Здесь проверяется то, чья ошибка молчит: пароль, границы арендатора и права
роли приложения. Ошибка в любом из трёх не падает и не кричит — она открывает
историю проверок сети тому, кому её видеть не положено, и выглядит при этом
как обычная рабочая страница.

Заслоны проверяются ЗАПУСКОМ, а не чтением миграции: «в схеме написано» и «база
так делает» — разные утверждения, и разошлись они бы молча.

Прогон идёт двумя ролями сразу, потому что весь смысл задачи в том, что они
разные. Учётки заводит роль владельца (`DATABASE_ADMIN_URL`, так же гоняются
миграции и разовые работы обслуживания), а живёт админка под ролью приложения
(`DATABASE_URL`) — и та завести или подменить учётку не может вовсе.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError, EmailTakenError  # noqa: E402
from src.db.web_access import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUDITOR,
    SESSION_TTL,
    authenticate,
    change_password,
    close_session,
    create_account,
    disable_account,
    find_by_email,
    list_accounts,
    new_session_token,
    normalize_email,
    open_session,
    password_hash,
    resolve_session,
    session_fingerprint,
    set_email,
    set_role,
)

pytestmark = requires_db

ТЕНАНТ = "rs"
ЧУЖОЙ = "me"
ПАРОЛЬ = "верный-пароль-учётки"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Окружение, где заведение учёток идёт владельцем, а вход — приложением.

    `db_env` уже поставил `DATABASE_URL` на роль приложения; здесь добавляется
    вторая половина. Возвращается DSN владельца — он нужен тестам, которые
    смотрят в таблицу в обход продукта.
    """
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return pg_dsn


# --- пароль: обратимого хранения нет ни в каком виде ------------------------


def test_пароль_не_лежит_в_базе_ни_целиком_ни_кусками(обе_роли: str) -> None:
    """В строке учётки не должно быть ничего, из чего пароль восстановим."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute("select password_hash from web_users where login = 'director'")
        (хеш,) = cur.fetchone()  # type: ignore[misc]

    assert ПАРОЛЬ not in хеш
    assert хеш.startswith("scrypt$"), "хранение обязано быть современным хешем с солью"


def test_один_и_тот_же_пароль_даёт_разные_хеши() -> None:
    """Соль своя у каждой учётки: иначе одинаковые пароли видны по совпадению."""
    assert password_hash(ПАРОЛЬ) != password_hash(ПАРОЛЬ)


def test_схема_не_принимает_пароль_вместо_хеша(обе_роли: str) -> None:
    """Ошибка «записали пароль» обязана быть отказом записи, а не тихой утечкой."""
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values (%s) on conflict do nothing", (ТЕНАНТ,))
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash) values (%s, %s, %s)",
                (ТЕНАНТ, "нехороший", ПАРОЛЬ),
            )


# --- опознание --------------------------------------------------------------


def test_верный_пароль_опознаёт(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    учётка = authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ)
    assert учётка is not None
    assert учётка.login == "director"
    assert учётка.tenant == ТЕНАНТ


def test_неверный_пароль_не_опознаёт(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    assert authenticate("director", ПАРОЛЬ + "!", tenant=ТЕНАНТ) is None


def test_незнакомый_логин_не_опознаётся(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    assert authenticate("никто", ПАРОЛЬ, tenant=ТЕНАНТ) is None


def test_отключённая_учётка_не_опознаётся(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    assert disable_account("director", tenant=ТЕНАНТ) is True
    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is None


# --- границы арендатора -----------------------------------------------------


def test_учётка_чужого_тенанта_не_опознаётся(обе_роли: str) -> None:
    """Вход не даёт доступа к чужому тенанту: фильтр стоит в SQL, а не в шаблоне."""
    create_account("director", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is None


def test_сессия_чужого_тенанта_не_открывает_этот_стенд(обе_роли: str) -> None:
    """Кука, выданная стендом другого арендатора, здесь не действует."""
    чужая = create_account("director", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    сессия = open_session(чужая)
    assert resolve_session(сессия.token, tenant=ЧУЖОЙ) is not None
    assert resolve_session(сессия.token, tenant=ТЕНАНТ) is None


def test_один_логин_живёт_в_разных_тенантах(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    create_account("director", tenant=ЧУЖОЙ, password="другой-пароль")
    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is not None
    assert authenticate("director", "другой-пароль", tenant=ЧУЖОЙ) is not None


def test_логин_внутри_одного_тенанта_не_повторяется(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with pytest.raises(AccessError):
        create_account("director", tenant=ТЕНАНТ, password="второй-пароль-подлиннее")


# --- права роли приложения --------------------------------------------------


def test_роль_приложения_не_заводит_учётки(обе_роли: str, db_env: str) -> None:
    """Учётки заводит владелец. Приложению это не «не предусмотрено», а нельзя."""
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash) values (%s, %s, %s)",
                (ТЕНАНТ, "самозванец", password_hash(ПАРОЛЬ)),
            )


def test_роль_приложения_не_правит_чужой_пароль(обе_роли: str, db_env: str) -> None:
    """Подмена хеша — это вход под чужим именем без следа. Права на это нет."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("update web_users set password_hash = %s", (password_hash("моё"),))


def test_роль_приложения_не_удаляет_учётки(обе_роли: str, db_env: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("delete from web_users")


# --- сессия: выход действительно прекращает её ------------------------------


def test_живая_сессия_опознаётся(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    опознан = resolve_session(сессия.token, tenant=ТЕНАНТ)
    assert опознан is not None
    assert опознан.login == "director"


def test_выход_прекращает_сессию_в_базе(обе_роли: str) -> None:
    """Главное свойство выхода: предъявленная снова кука больше не работает."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    assert close_session(сессия.token) is True
    assert resolve_session(сессия.token, tenant=ТЕНАНТ) is None


def test_закрытая_сессия_не_воскресает(обе_роли: str, db_env: str) -> None:
    """Заслон схемы: снять пометку закрытия нельзя даже правкой из приложения."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    close_session(сессия.token)

    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "update web_sessions set closed_at = null where fingerprint = %s",
            (session_fingerprint(сессия.token),),
        )
        assert cur.rowcount == 0, "закрытая сессия обязана остаться закрытой"


def test_отключение_учётки_гасит_живую_сессию(обе_роли: str) -> None:
    """Отняли учётку — отняли и то, что по ней уже открыто."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    disable_account("director", tenant=ТЕНАНТ)
    assert resolve_session(сессия.token, tenant=ТЕНАНТ) is None


def test_просроченная_сессия_не_опознаётся(обе_роли: str) -> None:
    """Срок кладётся сразу просроченным: правкой срока его не подвинуть.

    Продлить чужую сессию роль приложения не может — права на колонку у неё
    нет, — поэтому истёкшая сессия и создаётся здесь владельцем напрямую.
    """
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    токен = new_session_token()
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_sessions (user_id, fingerprint, expires_at) "
            "values (%s, %s, now() - interval '1 second')",
            (учётка.id, session_fingerprint(токен)),
        )
    assert resolve_session(токен, tenant=ТЕНАНТ) is None


def test_роль_приложения_не_продлевает_сессию(обе_роли: str, db_env: str) -> None:
    """Иначе «протухает через 12 часов» держалось бы честностью кода, а не схемой."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "update web_sessions set expires_at = now() + interval '100 days' "
                "where fingerprint = %s",
                (session_fingerprint(сессия.token),),
            )


def test_срок_сессии_задан_и_конечен(обе_роли: str) -> None:
    """Сессия обязана протухать сама: бессрочная кука — это вечный доступ."""
    assert timedelta(0) < SESSION_TTL <= timedelta(days=1)


def test_значения_сессионного_токена_в_базе_нет(обе_роли: str) -> None:
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    сессия = open_session(учётка)
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        cur.execute("select fingerprint from web_sessions")
        (отпечаток,) = cur.fetchone()  # type: ignore[misc]
    assert отпечаток != сессия.token
    assert сессия.token not in отпечаток


def test_схема_не_принимает_токен_вместо_отпечатка(обе_роли: str) -> None:
    """Тот же заслон, что у токенов MCP (`0011`): колонка берёт только SHA-256."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with psycopg.connect(обе_роли) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into web_sessions (user_id, fingerprint, expires_at) "
                "values (%s, %s, now() + interval '1 hour')",
                (учётка.id, new_session_token()),
            )


def test_незнакомая_кука_не_опознаётся(обе_роли: str) -> None:
    assert resolve_session(new_session_token(), tenant=ТЕНАНТ) is None


# --- команда проекта: что она показывает ------------------------------------


def test_список_учёток_не_печатает_ни_пароля_ни_хеша(обе_роли: str) -> None:
    """Команда обслуживания показывает, кто есть, а не чем он входит."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    строки = list_accounts(tenant=ТЕНАНТ)
    assert [строка.login for строка in строки] == ["director"]
    поля = str(строки[0])
    assert ПАРОЛЬ not in поля
    assert "scrypt" not in поля


def test_список_показывает_отключённую_отключённой(обе_роли: str) -> None:
    """Отключённая учётка остаётся в списке: «у кого был доступ» — часть следа."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    assert list_accounts(tenant=ТЕНАНТ)[0].disabled_at is None
    disable_account("director", tenant=ТЕНАНТ)
    строки = list_accounts(tenant=ТЕНАНТ)
    assert [строка.login for строка in строки] == ["director"]
    assert строки[0].disabled_at is not None


def test_заведённая_учётка_по_умолчанию_не_админ(обе_роли: str) -> None:
    """Умолчание — самая узкая роль.

    Заводящий человек думает про «завести Петра», а не про объём его прав.
    Умолчание, дающее больше, раздавало бы админов молча — и заметили бы это
    ровно тогда, когда кто-то отключил чужую учётку.
    """
    заведённая = create_account("petr", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    assert заведённая.role == ROLE_AUDITOR
    опознанная = authenticate("petr", ПАРОЛЬ, tenant=ТЕНАНТ)
    assert опознанная is not None
    # Роль приезжает ВМЕСТЕ с опознанием: спрошенная отдельным запросом, она
    # успела бы устареть между двумя запросами.
    assert опознанная.role == ROLE_AUDITOR


def test_роль_назначается_и_видна_вошедшему(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    assert set_role("director", tenant=ТЕНАНТ, role=ROLE_ADMIN) is True

    опознанная = authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ)
    assert опознанная is not None and опознанная.role == ROLE_ADMIN
    # И в сессии тоже: страницы спрашивают роль у сессии, а не у формы входа.
    сессия = open_session(опознанная)
    из_сессии = resolve_session(сессия.token, tenant=ТЕНАНТ)
    assert из_сессии is not None and из_сессии.role == ROLE_ADMIN


def test_роль_чужого_тенанта_не_назначается(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    # Арендатор — граница доступа, и роль её не расширяет ни в какую сторону.
    assert set_role("director", tenant="xx", role=ROLE_ADMIN) is False
    опознанная = authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ)
    assert опознанная is not None and опознанная.role == ROLE_AUDITOR


def test_незаведённая_роль_отвергается_а_не_ложится_в_базу(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    # Опечатка в роли — отказ вслух. Записанная как есть, она сделала бы
    # учётку никем: проверка прав сравнивает со списком и молча не пустит.
    for кривая in ("Admin", "админ", "superuser", ""):
        with pytest.raises(AccessError):
            set_role("director", tenant=ТЕНАНТ, role=кривая)
        with pytest.raises(AccessError):
            create_account(
                f"u{abs(hash(кривая)) % 997}", tenant=ТЕНАНТ, password=ПАРОЛЬ, role=кривая
            )


# --- Вход через учётку Google: опознание по почте (T332) ---

ПОЧТА = "director@dodobrands.io"


def test_почта_опознаёт_живую_учётку(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    assert set_email("director", tenant=ТЕНАНТ, email=ПОЧТА) is True

    учётка = find_by_email(ПОЧТА, tenant=ТЕНАНТ)

    assert учётка is not None
    assert учётка.login == "director"
    assert учётка.tenant == ТЕНАНТ


def test_регистр_и_пробелы_в_почте_не_плодят_второго_человека(обе_роли: str) -> None:
    """Google вернёт почту в своей форме, а не в той, в какой её завели у нас."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email="  Director@DodoBrands.IO ")

    учётка = find_by_email("DIRECTOR@dodobrands.io", tenant=ТЕНАНТ)

    assert учётка is not None
    assert учётка.login == "director"


def test_незнакомая_почта_получает_отказ_а_не_учётку(обе_роли: str) -> None:
    """Круг допущенных задаёт владелец, а не Google: автозавода по входу нет."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)

    assert find_by_email("kto-ugodno@gmail.com", tenant=ТЕНАНТ) is None
    assert len(list_accounts(tenant=ТЕНАНТ)) == 1


def test_отключённая_учётка_не_входит_и_через_google(обе_роли: str) -> None:
    """Отзыв доступа закрывает все двери сразу, иначе это не отзыв."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)
    disable_account("director", tenant=ТЕНАНТ)

    assert find_by_email(ПОЧТА, tenant=ТЕНАНТ) is None


def test_почта_чужого_арендатора_не_опознаётся(обе_роли: str) -> None:
    """Домен почты не говорит, чью историю человеку видно: арендатор из стенда."""
    create_account("director", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    set_email("director", tenant=ЧУЖОЙ, email=ПОЧТА)

    assert find_by_email(ПОЧТА, tenant=ТЕНАНТ) is None


def test_снятая_почта_закрывает_вход_через_google_но_не_учётку(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)

    assert set_email("director", tenant=ТЕНАНТ, email=None) is True

    assert find_by_email(ПОЧТА, tenant=ТЕНАНТ) is None
    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is not None


def test_пустая_почта_не_опознаёт_никого(обе_роли: str) -> None:
    """Пустая строка — не «любой», а никто: иначе вход открывается молчанием."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)

    assert find_by_email("", tenant=ТЕНАНТ) is None
    assert find_by_email("   ", tenant=ТЕНАНТ) is None
    with pytest.raises(ValueError):
        normalize_email("   ")


def test_две_учётки_с_одной_почтой_у_арендатора_не_заводятся(обе_роли: str) -> None:
    """Иначе опознание стало бы выбором из двух строк, а выбирать не из чего."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    create_account("auditor", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    set_email("director", tenant=ТЕНАНТ, email=ПОЧТА)

    with pytest.raises(EmailTakenError):
        set_email("auditor", tenant=ТЕНАНТ, email=ПОЧТА)


# --- Смена пароля учётки (T340, #323) ---


def test_новый_пароль_опознаёт_а_старый_перестаёт(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    НОВЫЙ = ПАРОЛЬ + "-другой"

    assert change_password("director", tenant=ТЕНАНТ, password=НОВЫЙ) is True

    assert authenticate("director", НОВЫЙ, tenant=ТЕНАНТ) is not None
    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is None


def test_смена_пароля_выгоняет_открытые_сессии(обе_роли: str) -> None:
    """Пароль меняют, когда его узнали: вошедший по старому обязан вылететь."""
    учётка = create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    открытая = open_session(учётка)
    assert resolve_session(открытая.token, tenant=ТЕНАНТ) is not None

    change_password("director", tenant=ТЕНАНТ, password=ПАРОЛЬ + "-другой")

    assert resolve_session(открытая.token, tenant=ТЕНАНТ) is None


def test_пароль_не_меняется_несуществующей_учётке(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    assert change_password("никто", tenant=ТЕНАНТ, password="какой-угодно-пароль") is False


def test_пароль_не_меняется_отключённой_учётке(обе_роли: str) -> None:
    """Отключённую не воскрешают сменой пароля: её включают отдельно и осознанно."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    disable_account("director", tenant=ТЕНАНТ)

    assert change_password("director", tenant=ТЕНАНТ, password=ПАРОЛЬ + "-другой") is False


def test_смена_пароля_не_трогает_чужого_арендатора(обе_роли: str) -> None:
    create_account("director", tenant=ЧУЖОЙ, password=ПАРОЛЬ)

    assert change_password("director", tenant=ТЕНАНТ, password=ПАРОЛЬ + "-другой") is False
    assert authenticate("director", ПАРОЛЬ, tenant=ЧУЖОЙ) is not None


def test_смена_пароля_не_принимает_короткий(обе_роли: str) -> None:
    """Правило длины стояло только на заведении — это был обход в один шаг."""
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)

    with pytest.raises(AccessError):
        change_password("director", tenant=ТЕНАНТ, password="коротыш")

    assert authenticate("director", ПАРОЛЬ, tenant=ТЕНАНТ) is not None
