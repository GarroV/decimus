"""Настройка MCP и круг доступа к ней (T209 → T253 → T261, D087, D098, D099).

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
* отзыв поимённый и немедленный — без перезапуска чего бы то ни было;
* пункт виден не всем (D099), и невидимость держится не только меню: команду
  можно набрать руками, и заслон стоит в самом обработчике;
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

from src.bot.app import (
    MCP_MENU_COMMANDS,
    MENU_COMMANDS,
    announce_commands,
    build_dispatcher,
    circle_at_startup,
)
from src.bot.config import UI_LANG_VAR, BotSettings
from src.bot.keyboards import (
    MCP_SETUP_SEND,
)
from src.bot.routers.mcp import (
    MCP_ADD_COMMAND,
    MCP_COMMAND,
    MCP_REVOKE_COMMAND,
    MCP_URL_VAR,
    MCP_WHO_COMMAND,
)
from src.bot.texts import t
from src.domain import start_inspection

pytestmark = pytest.mark.asyncio

COMMAND = f"/{MCP_COMMAND}"

#: Второй человек — тот, кого основатель круга приводит за собой. Он есть в
#: списке разрешённых ID: иначе мидлварь доступа не пустила бы его к боту, и
#: выданный ему доступ был бы записью в базе и ничем больше.
SECOND_ID = 4343

#: Разрешённый, но в круг не приведённый. Он и есть «чужой человек» задачи:
#: не посторонний (тех не пускает мидлварь), а свой аудитор, которому настройка
#: подключения не предназначена.
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
    allowed_ids=frozenset({AUDITOR_ID, SECOND_ID, OUTSIDER_ID}),
    mode="polling",
    auditor_names={},
    mcp_owner_id=AUDITOR_ID,
    mcp_tenant="default",
)

#: Тот же стенд, но круг на нём не назначен: настройка не доступна никому.
SETTINGS_NO_CIRCLE = BotSettings(
    token="unused-in-tests",
    allowed_ids=frozenset({AUDITOR_ID}),
    mode="polling",
    auditor_names={},
    mcp_owner_id=None,
)

#: Токен из напечатанной команды. Ищется ровно там, где стоит, а не
#: «где-нибудь в тексте»: сверять надо то, что человек вставит в терминал.
#:
#: Именно `Bearer`: моста в команде больше нет (#244), токен уезжает в
#: `--header "Authorization: Bearer ..."` и стоит в строке ровно один раз.
#: Прежний образец искал `DODO_MCP_TOKEN` внутри записи настроек Desktop —
#: с короткой командой такой записи в переписке не появляется вовсе.
_TOKEN_IN_COMMAND = re.compile(r"Bearer ([A-Za-z0-9_-]+)")


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
#: (`src/bot/mcp_setup.py`). Сама команда проверяется запуском в
#: `tests/test_bot_mcp_command.py`; здесь — что в переписку уехала именно она.
НАЧАЛО_КОМАНДЫ = "claude mcp add"


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
    assert владелец.telegram_id == AUDITOR_ID, "токен выпущен не на того, кто звал"


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
    Теперь сервер подключается прямым HTTP-транспортом — проверено живым
    подключением 15.09.2026, — и в переписку уходит ОДНА строка, которая
    только прописывает сервер в настройки клиента.

    Отсюда и проверки: ни переноса строки, ни следов установки. Предупреждения
    про систему здесь больше нет и быть не должно — `claude` одинаков везде,
    а прежняя команда правила файл настроек macOS и на другой системе
    промахивалась молча.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await настроить(dp, bot)

    команда = строка_настройки(session)
    assert "\n" not in команда, "команда перестала быть одной строкой"
    for след in ("plutil", "Library/Application Support", "mkdir", "chmod", "curl"):
        assert след not in команда, f"в команде снова установка на машину: {след}"


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


# --- круг: кому пункт доступен ------------------------------------------------


@requires_db
async def test_чужой_человек_позвать_настройку_не_может(domain_env: object, db_env: str) -> None:
    """D099: пункт для избранного круга, и заслон стоит НЕ в меню.

    Меню — витрина: команду можно набрать руками, не заглядывая в него. Поэтому
    проверяется сам обработчик, а не список пунктов.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, COMMAND, кто=OUTSIDER_ID)

    assert not any(_TOKEN_IN_COMMAND.search(текст) for текст in session.texts), (
        "настройка выдана тому, кому она не предназначена"
    )
    assert session.last_text == t("mcp.not_yours", "ru")


@requires_db
async def test_нажатие_чужого_настройку_тоже_не_выдаёт(domain_env: object, db_env: str) -> None:
    """Заслон стоит и на кнопке, а не только на команде (T261).

    Кнопка остаётся в переписке навсегда, и нажать её вправе тот, у кого доступ
    с тех пор отозвали, — вопрос он уже получил, когда был в круге. Проверка,
    сделанная только на входе в пункт, такое нажатие пропустила бы, а нажатие
    выпускает токен.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(
        dp,
        bot,
        callback_query(MCP_SETUP_SEND, user_id=OUTSIDER_ID, chat_id=OUTSIDER_ID),
    )

    assert not any(_TOKEN_IN_COMMAND.search(текст) for текст in session.texts), (
        "нажатие в обход пункта выдало настройку чужому"
    )
    assert session.last_text == t("mcp.not_yours", "ru")


@requires_db
async def test_команда_чужого_не_уезжает_в_записи_проверки(domain_env: object, db_env: str) -> None:
    """Отказ отвечается словами, а не молчанием, и вот почему.

    Проглоченная команда пошла бы дальше по цепочке роутеров — в приём
    материала, — и «/mcp» стало бы комментарием к ждущему кадру, то есть
    попало бы в отчёт партнёру. Молчание здесь дороже отказа.
    """
    start_inspection(OUTSIDER_ID, "Белград 2", "planned", "ru", date="2026-09-06", auditor="Гарро")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, COMMAND, кто=OUTSIDER_ID)

    assert session.last_text == t("mcp.not_yours", "ru"), (
        "команда чужого разобрана как материал проверки"
    )


@requires_db
async def test_админ_приводит_следующего_и_тот_получает_свой_токен(
    domain_env: object, db_env: str
) -> None:
    """Каждый в круге может привести следующего — весь механизм пополнения.

    Токен приведённому при этом НЕ показывается приводившему: он выпускает его
    себе сам. Токен, показанный не своему владельцу, уже утёк.
    """
    from src.db.mcp_access import resolve_token

    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    ответ_приводившему = session.texts[-1]
    session.clear()
    await настроить(dp, bot, кто=SECOND_ID)

    assert ответ_приводившему == t("mcp.added", "ru", who=SECOND_ID)
    команда = строка_настройки(session)
    владелец = resolve_token(выданный_токен(команда))
    assert владелец is not None and владелец.telegram_id == SECOND_ID


@requires_db
async def test_доступ_не_выдаётся_тому_кого_нет_в_списке_разрешённых(
    domain_env: object, db_env: str
) -> None:
    """Доступ человеку, которого мидлварь до бота не пускает, — запись и ничего.

    Выглядела бы такая выдача работающей, а не работала бы никогда: до пункта
    настройки он просто не доберётся.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {STRANGER_ID}")

    assert session.last_text == t("mcp.add_not_allowed", "ru", who=STRANGER_ID)


@requires_db
async def test_отзыв_поимённый_и_немедленный(domain_env: object, db_env: str) -> None:
    """Требование задачи дословно: без перезапуска чего бы то ни было.

    Немедленность держится не расторопностью, а тем, что копии круга нигде нет:
    и бот, и сервер MCP спрашивают базу на каждое обращение. Поэтому здесь один
    и тот же диспетчер продолжает работать после отзыва — перезапуска между
    «отозвали» и «проверили» нет намеренно.
    """
    from src.db.mcp_access import resolve_token

    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    session.clear()
    await настроить(dp, bot, кто=SECOND_ID)
    токен_второго = выданный_токен(строка_настройки(session))
    session.clear()

    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {SECOND_ID}")

    assert session.last_text == t("mcp.revoked", "ru", who=SECOND_ID, tokens=1)
    assert resolve_token(токен_второго) is None, "отозванный токен продолжает работать"


@requires_db
async def test_отозванный_не_выпустит_себе_новый(domain_env: object, db_env: str) -> None:
    """Иначе отзыв не отзывает ничего.

    Отзыв одного токена оставил бы человека в круге, и следующим же вызовом он
    выпустил бы себе новый. Поэтому отзыв гасит и круг, и токены разом.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {SECOND_ID}")
    session.clear()

    await настроить(dp, bot, кто=SECOND_ID)

    assert session.last_text == t("mcp.not_yours", "ru")
    assert not any(_TOKEN_IN_COMMAND.search(текст) for текст in session.texts)


@requires_db
async def test_основателя_круга_отозвать_нельзя(domain_env: object, db_env: str) -> None:
    """Его называет настройка стенда, и отозванный он вернулся бы при подъёме.

    Отказ здесь честнее сделанной и молча отменённой работы: иначе круг можно
    было бы опустошить до состояния, из которого в него не попасть.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {AUDITOR_ID}")

    assert session.last_text == t("mcp.revoke_founder", "ru", who=AUDITOR_ID)
    session.clear()
    await настроить(dp, bot)
    assert строка_настройки(session), "основатель потерял доступ"


@requires_db
async def test_след_показывает_кто_кого_привёл_и_кто_отозвал(
    domain_env: object, db_env: str
) -> None:
    """Ради этого след и заведён: что доступ у тех, кого назначил владелец
    (D098), иначе нечем проверить.

    Через месяц вопрос задаётся именно так, и ответить на него по памяти
    нельзя — а отозванная строка, исчезнувшая из таблицы, не отвечает вовсе.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {OUTSIDER_ID}")
    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {OUTSIDER_ID}")
    session.clear()

    await позвать(dp, bot, f"/{MCP_WHO_COMMAND}")

    след = session.last_text
    assert t("mcp.who_founder", "ru") in след, "основатель не назван настройкой стенда"
    assert f"{SECOND_ID} — привёл: {AUDITOR_ID}" in след, "не сказано, кто кого привёл"
    assert f"{OUTSIDER_ID} — отозван: {AUDITOR_ID}" in след, "не сказано, кто отозвал"


@requires_db
async def test_круг_называет_у_кого_токен_на_руках(domain_env: object, db_env: str) -> None:
    """«В круге» и «доступ выпущен» — разные вопросы, и сверяют именно второй."""
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    await настроить(dp, bot)
    session.clear()

    await позвать(dp, bot, f"/{MCP_WHO_COMMAND}")

    след = session.last_text
    assert f"{AUDITOR_ID} — привёл" in след
    assert t("mcp.who_has_token", "ru") in след, "не видно, у кого токен выпущен"
    assert t("mcp.who_no_token", "ru") in след, "не видно, кто токен не выпускал"


async def test_круг_не_назначен_настройка_не_доступна_никому(domain_env: object) -> None:
    """Забытая переменная закрывает настройку, а не открывает её всем.

    Умолчание «пускать всех» было бы худшим из возможных: оно раздавало бы
    историю проверок партнёров всякому стенду, где о переменной не подумали, —
    а не подуманное замечают позже всего. База при этом не спрашивается вовсе:
    решается всё настройкой, и до похода в неё дело не доходит.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS_NO_CIRCLE)

    await позвать(dp, bot, COMMAND)

    assert session.last_text == t("mcp.circle_unset", "ru")
    assert not any(текст.startswith("claude mcp add") for текст in session.texts)


# --- меню: видно не всем (D099) ----------------------------------------------


async def test_общее_меню_настройки_MCP_не_показывает(domain_env: object) -> None:
    """Телеграм держит меню на аккаунт.

    Поэтому «видно не всем» — это два РАЗНЫХ объявления, а не одно
    отфильтрованное, и общее не должно нести пункт, который большинству
    отвечает отказом.
    """
    bot, session = make_bot()

    await announce_commands(bot)

    объявлено = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert объявлено, "команды в меню не объявлены вовсе"
    имена = {c.command for c in объявлено[0].commands}
    for пункт in (MCP_COMMAND, MCP_ADD_COMMAND, MCP_REVOKE_COMMAND, MCP_WHO_COMMAND):
        assert пункт not in имена, f"пункт круга /{пункт} попал в общее меню"


async def test_кругу_меню_объявляется_отдельно_и_с_настройкой(domain_env: object) -> None:
    """Вторая половина того же: у человека из круга пункт обязан быть виден.

    Проверяется и адрес объявления: меню круга уходит В ЕГО ЧАТ, а не поверх
    общего, — иначе оно досталось бы всем.
    """
    bot, session = make_bot()

    await announce_commands(bot, (SECOND_ID,))

    личные = [
        c for c in session.calls if type(c).__name__ == "SetMyCommands" and c.scope is not None
    ]
    assert личные, "меню круга не объявлено никому"
    assert getattr(личные[0].scope, "chat_id", None) == SECOND_ID
    имена = {c.command for c in личные[0].commands}
    assert MCP_COMMAND in имена, "в меню круга нет самой настройки"
    assert {MCP_ADD_COMMAND, MCP_REVOKE_COMMAND, MCP_WHO_COMMAND} <= имена


@requires_db
async def test_меню_пересобирается_сразу_после_выдачи_и_отзыва(
    domain_env: object, db_env: str
) -> None:
    """Пункт, появляющийся только после перезапуска, — это не выданный доступ.

    А отзыв, оставляющий пункт висеть, человек нажмёт: пункт у него БЫЛ.
    Убирается меню удалением личного, а не объявлением копии общего под видом
    личного: копия молча отстала бы от общего при следующем его пополнении.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")
    выдано = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert выдано, "после выдачи меню не объявлено"
    assert getattr(выдано[-1].scope, "chat_id", None) == SECOND_ID
    assert MCP_COMMAND in {c.command for c in выдано[-1].commands}

    session.clear()
    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {SECOND_ID}")
    убрано = [c for c in session.calls if type(c).__name__ == "DeleteMyCommands"]
    assert убрано, "после отзыва личное меню не убрано"
    assert getattr(убрано[-1].scope, "chat_id", None) == SECOND_ID


async def test_спрятанных_команд_у_бота_нет(domain_env: object) -> None:
    """Каждая команда бота названа хотя бы в одном меню.

    Иначе о ней знает только тот, кто читал код. С T253 меню два, поэтому
    сверяется ОБЪЕДИНЕНИЕ: пункт, показанный кругу, спрятанным не считается, а
    вот команда, забытая в обоих списках, — ровно та скрытая функция, из-за
    которой показ записанного жил за кнопкой «Завершить» (T139). Список
    правится руками, и в этом весь смысл: решение «кому показывать»
    принимается, а не забывается.
    """
    имена = {name for name, _ in MENU_COMMANDS} | {name for name, _ in MCP_MENU_COMMANDS}

    assert имена == {
        "start",
        "records",
        "undo",
        "finish",
        "version",
        MCP_COMMAND,
        MCP_ADD_COMMAND,
        MCP_REVOKE_COMMAND,
        MCP_WHO_COMMAND,
    }, "состав меню разошёлся с командами бота"


async def test_меню_называет_пункты_словами_владельца(domain_env: object) -> None:
    """Названия названы владельцем (D087), поэтому проверяются, а не подразумеваются."""
    bot, session = make_bot()

    await announce_commands(bot, (AUDITOR_ID,))

    объявления = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    описания = [c.description for объявлено in объявления for c in объявлено.commands]
    assert "Новая проверка" in описания, "пункт «Новая проверка» в меню не назван"
    assert "Установка MCP" in описания, "пункт «Установка MCP» в меню не назван"


async def test_снятия_сданной_проверки_в_меню_нет() -> None:
    """Решение D086: снимает проверку управляющая компания через MCP, не аудитор.

    Проверяется не текст, а состав ОБОИХ меню: вход, которого у бота нет, не
    должен появиться «за компанию» при следующем пополнении списка — и меню
    круга здесь место даже более вероятное, чем общее.
    """
    имена = [name for name, _ in MENU_COMMANDS] + [name for name, _ in MCP_MENU_COMMANDS]
    for запрещённое in ("retract", "delete", "remove", "drop"):
        assert запрещённое not in имена, f"в меню появилось снятие проверки: /{запрещённое}"


# --- как человек ошибается на самом деле ---------------------------------------
#
# Команда с аргументом набирается руками, и промахнуться в ней проще всего:
# позвать без аргумента, вписать имя вместо идентификатора, привести того, кто
# уже приведён. Ответы на это написаны словами — значит, обязаны проверяться,
# иначе первая же опечатка уронит обработчик вместо того, чтобы получить ответ.


@requires_db
async def test_привод_без_аргумента_объясняет_как_звать(domain_env: object, db_env: str) -> None:
    """Голая команда — самый частый способ ею воспользоваться в первый раз."""
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND}")

    assert session.last_text == t("mcp.add_usage", "ru")


@requires_db
async def test_отзыв_без_аргумента_объясняет_как_звать(domain_env: object, db_env: str) -> None:
    """То же и у отзыва: молчание здесь читалось бы как «отозвал у всех»."""
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND}")

    assert session.last_text == t("mcp.revoke_usage", "ru")


@requires_db
@pytest.mark.parametrize("аргумент", ["Вася", "@vasya", "12ab"])
async def test_не_идентификатор_называется_не_идентификатором(
    domain_env: object, db_env: str, аргумент: str
) -> None:
    """Человека зовут именем, а бот знает его числом — промах ожидаемый.

    Ответ повторяет сказанное, чтобы человек увидел, ЧТО именно бот прочитал:
    промах чаще всего в невидимом (лишний пробел, приклеенная собачка), и
    «нужно число» без этого отправляет искать ошибку не туда.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {аргумент}")

    assert session.last_text == t("mcp.id_not_a_number", "ru", given=аргумент)


@requires_db
async def test_повторный_привод_говорит_что_ничего_не_изменилось(
    domain_env: object, db_env: str
) -> None:
    """Не отказ: привести уже приведённого — не ошибка.

    Но и не «доступ выдан»: сказать так значило бы, что след привода
    переписан на нового приводившего, а он не переписан (`add_admin`).
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")

    await позвать(dp, bot, f"/{MCP_ADD_COMMAND} {SECOND_ID}")

    assert session.last_text == t("mcp.already_in", "ru", who=SECOND_ID)


@requires_db
async def test_отзыв_у_того_кого_и_не_было_не_отказ(domain_env: object, db_env: str) -> None:
    """Отзыв идемпотентен: повторить его безопасно, и это сказано прямо.

    Отказ здесь заставил бы гадать, отозван человек или команда не сработала, —
    а перепроверить это в чате нечем.
    """
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, f"/{MCP_REVOKE_COMMAND} {OUTSIDER_ID}")

    assert session.last_text == t("mcp.revoke_nobody", "ru", who=OUTSIDER_ID)


# --- база отказала -------------------------------------------------------------


@pytest.mark.parametrize(
    "команда",
    [
        COMMAND,
        f"/{MCP_ADD_COMMAND} {SECOND_ID}",
        f"/{MCP_REVOKE_COMMAND} {SECOND_ID}",
        f"/{MCP_WHO_COMMAND}",
    ],
)
async def test_недоступная_база_отвечает_словами_а_не_молчанием(
    domain_env: object, команда: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Отказ базы — не «вам нельзя» и не тишина.

    `DATABASE_URL` снят автоматической фикстурой, то есть база недоступна
    по-настоящему. Проверяется каждая команда админки: проглоченная уехала бы
    дальше по цепочке роутеров в разбор материала, а отказ, показанный как
    «доступ не выдан», отправил бы человека просить доступ у того, у кого он
    уже есть.

    Разбор при этом обязан уйти в журнал — иначе чинить нечего.
    """
    caplog.set_level(logging.ERROR)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, команда)

    assert session.last_text == t("mcp.unavailable", "ru")
    assert caplog.records, "об отказе базы в журнале нет ни строки"


@requires_db
async def test_сорвавшийся_выпуск_не_печатает_ничего_похожего_на_токен(
    domain_env: object,
    db_env: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """База отказала уже ПОСЛЕ проверки круга — на самом выпуске.

    Отдельный случай от «база недоступна вовсе»: там до выпуска дело не
    доходит, а здесь человек уже прошёл заслон и ждёт строку настройки. Ему
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


# --- подъём бота --------------------------------------------------------------


@requires_db
async def test_основатель_заводится_при_подъёме_бота(domain_env: object, db_env: str) -> None:
    """Стенд, поднятый с пустой базой, обязан иметь хотя бы одного участника.

    Попасть в круг можно только из круга — значит, без основателя, заведённого
    настройкой, завести его было бы нечем, и админка осталась бы мёртвой
    навсегда.
    """
    from src.db.mcp_access import is_admin

    круг = circle_at_startup(SETTINGS)

    assert is_admin(AUDITOR_ID), "основатель круга при подъёме не заведён"
    assert круг == (AUDITOR_ID,), "меню круга объявлять некому"


async def test_круг_не_назначен_база_при_подъёме_не_спрашивается(
    domain_env: object,
) -> None:
    """Пустая переменная — не повод идти в базу и не повод падать.

    `DATABASE_URL` в этом тесте снят автоматической фикстурой, поэтому поход в
    базу здесь и не мог бы удаться: проверяется, что до него дело не доходит.
    """
    assert circle_at_startup(SETTINGS_NO_CIRCLE) == ()


async def test_недоступная_база_не_мешает_боту_подняться(domain_env: object) -> None:
    """Обход точки — работа аудитора, и останавливать её из-за списка доступа
    к MCP несоразмерно.

    Круг тогда просто не объявляется в меню, а сама настройка всё равно
    спрашивает базу на каждое обращение и откажет по месту — то есть молчаливой
    выдачи доступа из этого не выходит. `DATABASE_URL` снят автоматической
    фикстурой, значит база недоступна по-настоящему.
    """
    assert circle_at_startup(SETTINGS) == ()


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
async def test_отказ_чужому_тоже_на_языке_стенда(
    domain_env: object, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык — параметр и у отказа.

    Русский отказ на английском стенде ломает демо ровно так же, как русский
    вопрос, только незаметнее.
    """
    monkeypatch.setenv(UI_LANG_VAR, "en")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await позвать(dp, bot, COMMAND, кто=OUTSIDER_ID)

    assert session.last_text == t("mcp.not_yours", "en")


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
