"""Настройка MCP: личный токен себе на свою учётку (T209 → T253 → T261, D087, D098, D448).

Владелец назвал пункт сам: человек получает готовую строку настройки Claude
Desktop. До T253 отличие от соседнего продукта было одно и по существу —
ТОКЕНА В СТРОКЕ НЕ БЫЛО. Токены жили в `.env` записями «арендатор=токен»,
принадлежали СТОРОНЕ и открывали всю её историю проверок, а бот про
собеседника знал ровно одно: что его ID стоит в общем списке разрешённых.
Напечатанный токен был бы выдан наугад.

Теперь связь «этот человек — этот токен» есть (`src/db/mcp_access.py`), и
проверяется здесь ровно то, что из неё следует:

* строка приходит готовой, и токен в ней — ТОТ САМЫЙ, что выпущен на звавшего;
* токен показан один раз, повторный вызов гасит прежний и говорит об этом;
* выпускает себе каждый, кого бот пускает, — круга доступа нет (D448); без
  учётки за чатом токена нет, и бот говорит, как привязать бота;
* **карта токенов из `.env` не печатается и не логируется** — это тот же
  сторож, что стоял здесь с T209, и он не ослаблен появлением личных токенов,
  а дополнен: личный токен тоже не попадает в журнал.

T261 добавил к этому вопрос «какой Claude» и вторую строку — для приложения.
Строка для него не рассказывается словами, а ВЫПОЛНЯЕТСЯ: она правит файл
настроек живого человека, где уже стоят его собственные серверы, и «судя по
коду, должна работать» стоит здесь чужих рабочих инструментов. Дом при этом
подставной — настоящий файл настроек не трогается ни при каком исходе.

Что здесь НЕ проверяется намеренно: сама механика хранилища (выпуск, отпечаток,
уникальность живого токена) — она уровня базы и живёт в
`tests/test_db_mcp_access.py`. Здесь проверяется разговор.
"""

from __future__ import annotations

import logging
import re

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    STRANGER_ID,
    RecordingSession,
    callback_query,
    feed,
    make_bot,
    text_message,
)
from conftest import requires_db
from db_harness import привязать_бота

from src.bot.app import (
    MENU_COMMANDS,
    announce_commands,
    build_dispatcher,
)
from src.bot.config import UI_LANG_VAR, BotSettings
from src.bot.keyboards import (
    MCP_SETUP_SEND,
)
from src.bot.routers.mcp import (
    MCP_COMMAND,
    MCP_URL_VAR,
)
from src.bot.texts import t
from src.domain import start_inspection

pytestmark = pytest.mark.asyncio

COMMAND = f"/{MCP_COMMAND}"

#: Второй аудитор с учёткой: его токен свой и не трогает чужой.
SECOND_ID = 4343

#: Сотрудник по списку окружения (D290) без привязки бота к учётке: мидлварь его
#: пускает, а токена ему не выпустить — не на что.
OUTSIDER_ID = 4444

#: Правдоподобная карта токенов ровно в том виде, в каком её задаёт человек в
#: `.env` (`src/mcp/config.py`, `MCP_TOKENS`). Значение выдуманное и живёт
#: только в этом файле. Сторож с T209: этих знаков не должно оказаться ни в
#: одном сообщении и ни в одной строке журнала.
TOKENS_VAR = "MCP_TOKENS"
TOKEN = "MFVLDaN4gJH2sQ7cX1kZpR8tYbW3eU6o"
TOKENS = f"uk={TOKEN}"

SETTINGS = BotSettings(
    token="unused-in-tests",
    mode="polling",
    auditor_names={},
)


@pytest.fixture(autouse=True)
def _учётки(request: pytest.FixtureRequest) -> None:
    """Учётки сайта с привязанным ботом у своих людей стенда (аудит 12.10).

    Личный токен выпускается только на учётку: без привязки бот по-прежнему
    пускает сотрудника УК по списку окружения (D290), но токена ему не выдаёт
    (`OUTSIDER_ID` намеренно без учётки).
    Фикстура с условием: тест без базы её не получает.
    """
    if "db_env" not in request.fixturenames:
        return
    request.getfixturevalue("db_env")  # учётку заводит дверь базы: ей нужна база
    pg_dsn = request.getfixturevalue("pg_dsn")
    monkeypatch = request.getfixturevalue("monkeypatch")
    for кто, роль in ((AUDITOR_ID, "admin"), (SECOND_ID, "developer")):
        привязать_бота(pg_dsn, monkeypatch, кто, tenant="HQ", role=роль)


#: Токен из напечатанной команды. Ищется ровно там, где стоит, а не
#: «где-нибудь в тексте»: сверять надо то, что человек вставит в терминал.
#:
#: Токен стоит ровно там, где его подхватит установщик, — в окружении перед
#: `bash` (#244, D112). В аргументы он не попадает намеренно: `argv` виден
#: через `ps`, окружение чужого процесса на маке — нет.
_TOKEN_IN_COMMAND = re.compile(r"DECIMUS_MCP_TOKEN='?([A-Za-z0-9_-]+)")


def выданный_токен(текст: str) -> str:
    """Токен из готовой строки настройки — или явный отказ теста."""
    найден = _TOKEN_IN_COMMAND.search(текст)
    assert найден is not None, f"в строке настройки нет токена: {текст!r}"
    return найден.group(1)


async def позвать(dp: object, bot: object, команда: str, *, кто: int = AUDITOR_ID) -> None:
    """Позвать команду от имени человека — в его собственном чате."""
    await feed(dp, bot, text_message(команда, user_id=кто, chat_id=кто))


async def настроить(dp: object, bot: object, *, кто: int = AUDITOR_ID) -> None:
    """Пройти пункт целиком: вызвать и нажать кнопку (T261 → #222).

    Два шага, а не один: по кнопке выпускается токен, и вызов пункта сам по
    себе прежнюю настройку не ломает.
    """
    await позвать(dp, bot, COMMAND, кто=кто)
    await feed(dp, bot, callback_query(MCP_SETUP_SEND, user_id=кто, chat_id=кто))


def строка_настройки(session: RecordingSession) -> str:
    """Сообщение с командой — то самое, которое человек копирует.

    Ищется по токену, а не по номеру в переписке: номер разъехался бы при
    первой же правке текстов. Заодно это и проверка: команда настройки в
    переписке ровно одна.
    """
    тексты = list(session.texts)
    найдено = [текст for текст in тексты if _TOKEN_IN_COMMAND.search(текст)]
    assert len(найдено) == 1, f"строк настройки в переписке не одна, а {len(найдено)}: {тексты!r}"
    return найдено[0]


#: Начало присланной команды. Она выполняется в отдельной оболочке — так у
#: человека в сессии не остаётся ни наших переменных с токеном, ни `set -eu`
#: (`src/bot/mcp_setup.py`). Сначала скрипт скачивается во временный файл и сверяется по
#: SHA-256 (F-103), и только потом запускается — не слепой `curl | bash`. Сама команда
#: проверяется запуском в `tests/test_bot_mcp_command.py`; здесь — что в переписку
#: уехала именно она.
НАЧАЛО_КОМАНДЫ = "f=$(mktemp) && curl -fsSL"


# --- то, ради чего задача заведена ------------------------------------------


@requires_db
async def test_строка_настройки_приходит_с_личным_токеном_звавшего(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Суть T253: токен в строке — ТОТ САМЫЙ, что выпущен на этого человека.

    Проверяется не «в строке есть что-то похожее на токен», а что предъявление
    напечатанного токена опознаёт именно звавшего: связи «человек — токен» до
    T253 не существовало вовсе, и она здесь единственное, что изменилось по
    существу.

    """
    from src.db.mcp_access import resolve_token

    monkeypatch.setenv(MCP_URL_VAR, "http://127.0.0.1:8265/")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    команда = строка_настройки(session)
    assert команда.startswith(НАЧАЛО_КОМАНДЫ), "пришла не команда настройки"
    assert "ПУТЬ" not in команда and "PATH_TO" not in команда, (
        "в команде осталась заглушка: человек не обязан ничего подставлять"
    )
    assert "http://127.0.0.1:8265/" in команда, "адрес стенда в команду не подставился"
    владелец = resolve_token(выданный_токен(команда))
    assert владелец is not None, "напечатанный токен не опознаётся сервером MCP"
    assert владелец.login == f"tg-{AUDITOR_ID}", "токен выпущен не на учётку того, кто звал"


@requires_db
async def test_повторный_вызов_гасит_прежний_токен_и_говорит_об_этом(
    domain_env: object, db_env: str
) -> None:
    """«Показан один раз» без этого — просто пачка живых токенов.

    И вторая половина, не менее важная: человеку сказано вслух. Молча
    отозванный токен снаружи выглядит как поломка Claude, а не как следствие
    собственного действия, — и чинить он пойдёт не то.
    """
    from src.db.mcp_access import resolve_token

    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)
    первый = выданный_токен(строка_настройки(session))
    session.clear()

    await настроить(dp, bot)
    второй = выданный_токен(строка_настройки(session))

    assert первый != второй, "повторный вызов выдал тот же самый токен"
    assert resolve_token(первый) is None, "прежний токен продолжает работать"
    assert resolve_token(второй) is not None, "новый токен не работает"
    assert session.texts[-1] == t("mcp.replaced", "ru"), (
        "про отозванный прежний токен не сказано — человек решит, что сломался Claude"
    )


@requires_db
async def test_при_первой_выдаче_про_отзыв_не_говорится(domain_env: object, db_env: str) -> None:
    """Отзывать было нечего.

    Лишняя строка про «прежний больше не работает» отправила бы человека искать
    настройку, которой он не делал.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert t("mcp.replaced", "ru") not in session.texts


# --- пункт спрашивает не «какой Claude», а согласие (T261 → #222, D103) ------


@requires_db
async def test_пункт_сначала_говорит_что_будет_и_ждёт_кнопку(
    domain_env: object, db_env: str
) -> None:
    """Развилки про клиента больше нет, а согласие осталось — и не зря.

    По кнопке выпускается токен, а выпуск гасит прежний, то есть ломает уже
    работающую настройку человека. Поэтому вызов пункта сам по себе не делает
    ничего: он говорит, что произойдёт, и ждёт. Прежде здесь стоял вопрос
    «какой у вас Claude» — владелец эту развилку снял, поддерживается
    Claude Desktop.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, COMMAND)

    assert session.texts == [t("mcp.offer", "ru")], "пункт ответил чем-то ещё, кроме предупреждения"
    assert session.keyboard_data() == [MCP_SETUP_SEND], "кнопки настройки человеку не предложено"
    assert not any(_TOKEN_IN_COMMAND.search(текст) for текст in session.texts), (
        "токен выпущен на одном вызове пункта — прежняя настройка сломана за любопытство"
    )


@requires_db
async def test_один_вызов_пункта_прежнюю_настройку_не_ломает(
    domain_env: object, db_env: str
) -> None:
    """Открыть пункт и посмотреть — не повод гасить работающий токен.

    Выпуск заменяет прежний токен, то есть ломает уже сделанную настройку. Пока
    пункт выпускал токен на самом вызове, любопытство наказывалось: человек
    открывал его посмотреть и узнавал из третьего сообщения, что Claude у него
    только что отвалился. Теперь выпуск случается на нажатии — то есть тогда,
    когда человек и правда настраивает заново.
    """
    from src.db.mcp_access import resolve_token

    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await настроить(dp, bot)
    прежний = выданный_токен(строка_настройки(session))
    session.clear()

    await позвать(dp, bot, COMMAND)

    assert resolve_token(прежний) is not None, "вызов пункта погасил работающий токен"


@requires_db
async def test_про_перезапуск_приложения_сказано_после_команды(
    domain_env: object, db_env: str
) -> None:
    """Без перезапуска сервер в приложении не появится, и выглядит это поломкой.

    Файл настроек приложение читает только при запуске. Человек, выполнивший
    команду и открывший настройки, нашего сервера там не увидит и решит, что
    команда не сработала, — ровно так владелец и решил. Сказано ПОСЛЕ команды:
    мимо последнего сообщения не пройти.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert session.texts[-1] == t("mcp.code_restart", "ru"), "про перезапуск не сказано"
    команда = строка_настройки(session)
    assert session.texts.index(команда) < len(session.texts) - 1, "перезапуск назван до команды"


@requires_db
async def test_команда_одна_строка_и_ничего_не_ставит_на_машину(
    domain_env: object, db_env: str
) -> None:
    """Сторож против возврата простыни (#244).

    До этой задачи пункт слал сорок строк с телом моста внутри: человек их не
    читал, копировал из телеграма с потерями и справедливо боялся запускать.
    Теперь установщик лежит за адресом и скачивается (форма соседнего
    продукта, D112), а в переписку уходит ОДНА строка запуска.

    Отсюда и проверки: ни переноса строки, ни кусков установки в самом
    сообщении. Предупреждения про систему здесь больше нет — какой клиент
    настраивать, решает скрипт на машине, а не человек по памяти.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    команда = строка_настройки(session)
    assert "\n" not in команда, "команда перестала быть одной строкой"
    for след in ("plutil", "Library/Application Support", "mkdir", "chmod", "DODO_BRIDGE"):
        assert след not in команда, f"в переписку снова уехала установка целиком: {след}"
    assert "/setup" in команда, "команда не зовёт установщик с сервера"


# --- утечка: главный сторож этого файла --------------------------------------


@requires_db
async def test_карта_токенов_из_окружения_не_печатается_и_не_логируется(
    domain_env: object,
    db_env: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Сторож с T209, не ослабленный появлением личных токенов.

    Токены из `.env` принадлежат СТОРОНЕ и открывают всю её историю проверок.
    Бот выпускает теперь свои и печатает их — тем важнее, что чужих он
    по-прежнему не знает и не показывает: ни в переписке, ни в журнале.
    """
    monkeypatch.setenv(TOKENS_VAR, TOKENS)
    caplog.set_level(logging.DEBUG)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    for отправлено in session.texts:
        assert TOKEN not in отправлено, "токен стороны уехал в переписку"
    assert TOKEN not in caplog.text, "токен стороны уехал в журнал"


@requires_db
async def test_личный_токен_в_журнал_не_попадает(
    domain_env: object, db_env: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Показан один раз — значит, в журнале его быть не должно тем более.

    Переписку человек видит сам и знает, что в ней; журнал уезжает в сборщик
    логов, показывается на созвонах и живёт дольше всего остального. Токен,
    попавший туда, отзывать пришлось бы вслепую.
    """
    caplog.set_level(logging.DEBUG)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    личный = выданный_токен(строка_настройки(session))
    assert личный not in caplog.text, "личный токен уехал в журнал"


@requires_db
async def test_токен_печатается_ровно_в_одном_сообщении(domain_env: object, db_env: str) -> None:
    """Сообщение в телеграме копируется целиком одним движением.

    Поэтому объяснение и команда идут врозь (иначе объяснение уехало бы в
    терминал), а токен обязан стоять ровно в одном сообщении — том, которое
    человек копирует. Второе вхождение означало бы вторую копию секрета в
    переписке, живущую там навсегда.

    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    личный = выданный_токен(строка_настройки(session))
    с_токеном = [текст for текст in session.texts if личный in текст]
    assert len(с_токеном) == 1, "токен напечатан больше одного раза"
    assert с_токеном[0].startswith(НАЧАЛО_КОМАНДЫ), "токен уехал не в то сообщение"


# --- выпуск себе сам: круга нет (D448) -----------------------------------------


@requires_db
async def test_каждый_со_своей_учёткой_выпускает_себе_без_чьей_либо_выдачи(
    domain_env: object, db_env: str
) -> None:
    """Аудитор, которого никто никуда не приводил, получает свою строку настройки."""
    from src.db.mcp_access import resolve_token

    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot, кто=SECOND_ID)

    владелец = resolve_token(выданный_токен(строка_настройки(session)))
    assert владелец is not None and владелец.login == f"tg-{SECOND_ID}"
    assert владелец.role == "developer", "права в Claude решает роль учётки"


@requires_db
async def test_без_учётки_токена_нет_и_сказано_как_привязать(
    domain_env: object, db_env: str
) -> None:
    """Сотрудник по списку окружения проходит мидлварь, но выпускать токен не на что."""
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot, кто=OUTSIDER_ID)

    assert not any(_TOKEN_IN_COMMAND.search(текст) for текст in session.texts)
    assert session.last_text == t("mcp.unbound_self", "ru")


@requires_db
async def test_отказ_без_учётки_на_языке_стенда(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык — параметр и у отказа."""
    monkeypatch.setenv(UI_LANG_VAR, "en")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot, кто=OUTSIDER_ID)

    assert session.last_text == t("mcp.unbound_self", "en")


# --- меню: одно на всех (D448) ---------------------------------------------------


async def test_общее_меню_показывает_настройку_и_не_несёт_круга(domain_env: object) -> None:
    """Подключить Claude может каждый, кого бот пускает, — пункт в общем меню."""
    bot, session = make_bot()

    await announce_commands(bot)

    объявлено = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert объявлено, "команды в меню не объявлены вовсе"
    assert all(
        c.scope is None or type(c.scope).__name__ == "BotCommandScopeDefault" for c in объявлено
    )
    имена = {c.command for c in объявлено[0].commands}
    assert MCP_COMMAND in имена
    for пункт in ("mcp_add", "mcp_revoke", "mcp_who"):
        assert пункт not in имена, f"команда круга /{пункт} вернулась в меню"


async def test_спрятанных_команд_у_бота_нет(domain_env: object) -> None:
    """Каждая команда бота названа хотя бы в одном меню.

    Иначе о ней знает только тот, кто читал код: команда, забытая в меню, —
    ровно та скрытая функция, из-за которой показ записанного жил за кнопкой
    «Завершить» (T139). Список правится руками, и в этом весь смысл: решение
    «кому показывать» принимается, а не забывается.

    Исключение одно и названо: `/stops` — счётчик отказов мастера только
    админам (#436). Меню одно на всех (D448), и пункт, отвечающий аудиторам
    отказом, в нём не стоит; админ набирает команду сам.
    """
    имена = {name for name, _ in MENU_COMMANDS}

    assert имена == {
        "start",
        "records",
        "undo",
        "finish",
        # Сменить пиццерию начатой проверки (D628).
        "unit",
        "help",
        # Временная: обкатка формата отчёта (#261, D122) — уйдёт вместе с ней.
        "resend",
        "version",
        # Язык бота (D303) — у всех: выбрать его вправе каждый.
        "lang",
        # Подключение Claude (D448) — у всех: токен себе выпускает каждый.
        MCP_COMMAND,
    }, "состав меню разошёлся с командами бота"


async def test_меню_называет_пункты_словами_владельца(domain_env: object) -> None:
    """Названия названы владельцем (D087), поэтому проверяются, а не подразумеваются."""
    bot, session = make_bot()

    await announce_commands(bot)

    объявления = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    описания = [c.description for объявлено in объявления for c in объявлено.commands]
    assert "Новая проверка" in описания, "пункт «Новая проверка» в меню не назван"
    assert "Установка MCP" in описания, "пункт «Установка MCP» в меню не назван"


async def test_снятия_сданной_проверки_в_меню_нет() -> None:
    """Решение D086: снимает проверку управляющая компания через MCP, не аудитор.

    Проверяется не текст, а состав меню: вход, которого у бота нет, не должен
    появиться «за компанию» при следующем пополнении списка.
    """
    имена = [name for name, _ in MENU_COMMANDS]
    for запрещённое in ("retract", "delete", "remove", "drop"):
        assert запрещённое not in имена, f"в меню появилось снятие проверки: /{запрещённое}"


# --- база отказала -------------------------------------------------------------


async def test_недоступная_база_отвечает_словами_а_не_молчанием(
    domain_env: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Отказ базы на выпуске — не «вам нельзя» и не тишина.

    `DATABASE_URL` снят автоматической фикстурой, то есть база недоступна
    по-настоящему. Отказ, показанный как «нет учётки», отправил бы человека
    привязывать бота, который уже привязан. Разбор обязан уйти в журнал.
    """
    caplog.set_level(logging.ERROR)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert session.last_text == t("mcp.unavailable", "ru")
    assert caplog.records, "об отказе базы в журнале нет ни строки"


@requires_db
async def test_сорвавшийся_выпуск_не_печатает_ничего_похожего_на_токен(
    domain_env: object,
    db_env: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """База отказала на самом выпуске, когда человек уже ждёт строку настройки.

    Ему
    обязан прийти отказ, а не полстроки и не заглушка вместо токена: строку с
    подстановкой он вставит в терминал не читая.
    """
    import src.db.mcp_access as store

    caplog.set_level(logging.ERROR)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    def отказать(*_: object, **__: object) -> None:
        raise store.AccessError("база отказала на выпуске")

    monkeypatch.setattr(store, "issue_token", отказать)
    await настроить(dp, bot)

    assert session.last_text == t("mcp.unavailable", "ru")
    assert not any(текст.startswith(НАЧАЛО_КОМАНДЫ) for текст in session.texts), (
        "строка настройки ушла человеку без токена"
    )
    assert caplog.records, "о сорвавшемся выпуске в журнале нет ни строки"


# --- прочее, что держалось с T209 --------------------------------------------


@requires_db
async def test_объяснение_и_команда_разными_сообщениями(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сообщение копируется целиком, поэтому объяснение к команде не приклеено.

    С T261 проверяется сильнее: в сообщении с командой не должно быть НИЧЕГО,
    кроме неё самой, — ни предупреждения про macOS, ни просьбы перезапустить
    приложение. Всё это пришло отдельными сообщениями и в терминал не уедет.
    Хвост здесь — закрывающая метка вставки (`DODO_SETUP`): за ней у команды
    не должно оставаться ни строки.
    """
    monkeypatch.delenv(MCP_URL_VAR, raising=False)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert session.texts[1] == t("mcp.setup", "ru")
    команда = строка_настройки(session)
    assert команда.startswith(НАЧАЛО_КОМАНДЫ), (
        "команда пришла не голой — в терминал уедет лишний текст"
    )
    assert команда == команда.strip(), "к команде приклеен хвост"
    assert t("mcp.code_restart", "ru") not in команда


@requires_db
async def test_про_личный_токен_сказано_словами(domain_env: object, db_env: str) -> None:
    """Пункт отдаёт наружу работающий доступ — он же место, где сказано о цене.

    Показан один раз, повторный вызов заменит, пересылать нельзя: ничего из
    этого человек не увидит сам, а узнать обязан до того, как перешлёт строку
    коллеге «чтобы у него тоже работало».
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    объяснение = session.texts[1]
    assert объяснение == t("mcp.setup", "ru")
    assert "личный" in объяснение, "про личный токен не сказано"
    assert "один раз" in объяснение, "не сказано, что токен показан один раз"


@requires_db
async def test_адрес_не_назван_стендом_видно_в_самой_строке(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Заглушка вместо молчаливой петли: догадка, выданная за настройку, дороже."""
    monkeypatch.delenv(MCP_URL_VAR, raising=False)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert t("mcp.url_unknown", "ru") in строка_настройки(session)


@requires_db
async def test_язык_интерфейса_параметр_и_здесь(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Английский стенд не имеет права отвечать на установку по-русски.

    Проверяются все сообщения пункта, а не первое: предупреждение перед
    кнопкой, надпись на ней, объяснение и просьба перезапустить сессию — ровно
    то место, где русская строка на английском стенде заводится незаметнее
    всего. С #244 сообщений стало меньше: установка с машины ушла, а вместе с
    ней предупреждение про систему и печать об удаче из самой команды.
    """
    monkeypatch.setenv(UI_LANG_VAR, "en")
    monkeypatch.delenv(MCP_URL_VAR, raising=False)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    assert session.texts[0] == t("mcp.offer", "en")
    assert session.texts[1] == t("mcp.setup", "en")
    assert t("mcp.url_unknown", "en") in строка_настройки(session)
    assert session.texts[-1] == t("mcp.code_restart", "en")
    assert session.keyboard_texts() == [t("btn.mcp_send", "en")], (
        "надпись на кнопке осталась на языке стенда по умолчанию"
    )
    assert all("mcp." not in текст for текст in [строка_настройки(session)]), (
        "в команду просочился ключ каталога вместо текста"
    )


@requires_db
async def test_работает_и_до_начала_проверки_и_во_время(domain_env: object, db_env: str) -> None:
    """Установка — не шаг обхода: она не спрашивает проверку и не мешает ей.

    До начала проверки бот на обычный текст отвечает «проверка не начата», и
    попасть под это правило пункту меню было бы легко.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)
    до = строка_настройки(session)

    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-09-06", auditor="Гарро")
    session.clear()
    await настроить(dp, bot)

    assert до.startswith(НАЧАЛО_КОМАНДЫ)
    assert строка_настройки(session).startswith(НАЧАЛО_КОМАНДЫ)


async def test_постороннему_не_отвечает(domain_env: object) -> None:
    """Пункт даёт способ подключиться к проверкам — за общей дверью, как всё.

    Постороннего не пускает мидлварь доступа, и до базы дело не доходит вовсе:
    бот не подтверждает ему даже того, что такая команда существует.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND, user_id=STRANGER_ID, chat_id=STRANGER_ID))

    assert not session.texts, "посторонний получил ответ"
