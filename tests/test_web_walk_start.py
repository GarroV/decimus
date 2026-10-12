"""D392: начало проверки из мини-аппа — `POST /tg/walk/start`.

Ядро здесь — что именно ляжет в новую проверку и чьё это решение. Язык речи и
язык отчёта выбираются раздельно (D393): подмена одного другим молча уехала бы
партнёру в отчёт. Идущую проверку стирает только явное «заменить» (T052), а
память бота о прежней проверке не должна достаться новой — ни кнопки, ни слова.
Успех проверяется по состоянию проверки на диске, а не по коду ответа.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.bot.material import Comment, MaterialStore
from src.bot.pending import PendingStore, Proposal
from src.bot.unit_pick import UnitMatch
from src.db.bot_links import NEVER_BOUND
from src.db.errors import AccessError
from src.domain import get_state, handed_over, run_id, start_inspection
from src.domain.bot_checklists import BotChecklist
from src.domain.config import check_environment
from src.domain.engine import chat_dir
from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME
from src.web import walk, walk_access, walk_start

ПУТЬ = walk_start.START_PATH
НЕ_ЗНАЮ = UnitMatch(name=None, suggestions=(), checked=True)
НЕТ_СПРАВОЧНИКА = UnitMatch(name=None, suggestions=(), checked=False)


class Клиент:
    def __init__(self, flask_client: Any, user_id: int = АУДИТОР) -> None:
        self.c = flask_client
        self.init = подписать(user_id)

    def пост(self, **тело: Any) -> Any:
        return self.c.post(
            ПУТЬ,
            data=json.dumps(тело),
            content_type="application/json",
            headers={"X-Telegram-Init-Data": self.init},
        )

    def старт(self, **сверх: Any) -> Any:
        тело = {
            "op": "start",
            "unit": "Белград 1",
            "kind": "repeat",
            "speech_lang": "en",
        } | сверх
        return self.пост(**тело)


@pytest.fixture
def клиент(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Клиент:
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
    # Справочника точек нет: название принимается каноничным, как при его отказе.
    monkeypatch.setattr(walk_start, "match_unit", lambda *_a, **_k: НЕТ_СПРАВОЧНИКА)
    monkeypatch.setattr(walk_start, "suggest_units", lambda *_a, **_k: [])
    monkeypatch.setattr(walk_start, "suggest_index", lambda **_k: {"units": []})
    монк = _приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН, ALLOWED_TELEGRAM_IDS=f"{АУДИТОР},777")
    return Клиент(монк.test_client())


def _заметки(chat_id: int = АУДИТОР) -> Path:
    return chat_dir(chat_id, check_environment()) / NOTES_FILE_NAME


def _сдать(chat_id: int = АУДИТОР) -> None:
    _заметки(chat_id).write_text(json.dumps({HANDED_OVER_KEY: 0}), encoding="utf-8")


# ── доступ ──────────────────────────────────────────────────────────────


def test_без_подписи_401_и_проверка_не_начата(клиент: Клиент) -> None:
    ответ = клиент.c.post(ПУТЬ, data=json.dumps({"op": "options"}), content_type="application/json")

    assert ответ.status_code == 401
    assert get_state(АУДИТОР) is None


def test_подделанная_подпись_401(клиент: Клиент) -> None:
    ответ = клиент.c.post(
        ПУТЬ,
        data=json.dumps({"op": "start"}),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": подписать(АУДИТОР, token="999:other")},
    )

    assert ответ.status_code == 401
    assert get_state(АУДИТОР) is None


def test_того_кого_бот_не_пускает_мастер_не_пускает(клиент: Клиент) -> None:
    чужой = Клиент(клиент.c, user_id=5555)  # подпись настоящая, в списке бота его нет

    ответ = чужой.старт()

    assert ответ.status_code == 401
    assert get_state(5555) is None


# ── что ложится в проверку ──────────────────────────────────────────────


def test_старт_кладёт_ровно_выбранное(клиент: Клиент) -> None:
    ответ = клиент.старт(kind="unscheduled", speech_lang="en")

    assert ответ.status_code == 200, ответ.get_json()
    проверка = get_state(АУДИТОР)
    assert проверка is not None
    assert проверка.unit == "Belgrade-1", "название сводится к каноничному, как у бота (D233)"
    assert (проверка.kind, проверка.speech_lang, проверка.report_lang) == (
        "unscheduled",
        "en",
        "en",
    ), "язык отчёта на старте равен языку чек-листа и меняется в конце (D415)"
    assert проверка.ui_lang == "ru"
    assert проверка.auditor == "Аудитор", "имя — из профиля Telegram, как у бота"
    assert проверка.checklist_code == "bizdev" and проверка.tenant
    assert ответ.get_json()["state"] == "active"
    assert проверка.run_id, "у начатой проверки есть личность (память бота сверяется по ней)"


def test_приходящий_язык_отчёта_игнорируется(клиент: Клиент) -> None:
    """Старый клиент ещё шлёт `report_lang`: он принимается и не влияет (D415)."""
    клиент.старт(speech_lang="ru", report_lang="en")

    проверка = get_state(АУДИТОР)

    assert проверка is not None
    assert (проверка.speech_lang, проверка.report_lang) == ("ru", "ru")


def test_чек_лист_из_нескольких_выбирается_и_закрытый_отказ(
    клиент: Клиент, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    два = [
        BotChecklist(code="bizdev", name_ru="БД", name_en="BD", source=tmp_path),
        BotChecklist(code="rnd", name_ru="РНД", name_en="RnD", source=tmp_path),
    ]
    monkeypatch.setattr(walk_start, "open_checklists", lambda _space: два)

    опции = клиент.пост(op="options").get_json()
    без_выбора = клиент.старт()

    assert [c["code"] for c in опции["checklists"]] == ["bizdev", "rnd"]
    assert без_выбора.status_code == 422 and без_выбора.get_json()["field"] == "checklist"
    assert get_state(АУДИТОР) is None, "без выбранного чек-листа проверка не начинается"


def test_чек_листов_нет_старт_отказывает(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk_start, "open_checklists", lambda _space: [])

    ответ = клиент.старт()

    assert ответ.status_code == 409
    assert get_state(АУДИТОР) is None


@pytest.mark.parametrize(
    "поле",
    [
        pytest.param({"kind": "weekly"}, id="вид-вне-перечня"),
        pytest.param({"speech_lang": "sr"}, id="речь-вне-перечня"),
    ],
)
def test_вид_и_языки_только_из_перечня(клиент: Клиент, поле: dict[str, str]) -> None:
    ответ = клиент.старт(**поле)

    assert ответ.status_code == 400
    assert get_state(АУДИТОР) is None


@pytest.mark.parametrize("название", ["", "Белград", "Б" * 80])
def test_название_проверяется_как_у_бота(клиент: Клиент, название: str) -> None:
    ответ = клиент.старт(unit=название)

    assert ответ.status_code == 422 and ответ.get_json()["field"] == "unit"
    assert get_state(АУДИТОР) is None


# ── новая пиццерия ──────────────────────────────────────────────────────


def test_незнакомая_точка_у_партнёра_отказ(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk_start, "match_unit", lambda *_a, **_k: НЕ_ЗНАЮ)
    monkeypatch.setattr(walk_start, "space_of", lambda *_a: "GE")

    ответ = клиент.старт(add_unit=True)

    assert ответ.status_code == 422
    assert "управляющая компания" in ответ.get_json()["message"]
    assert get_state(АУДИТОР) is None, "партнёр точек не заводит, даже с флагом"


def test_незнакомая_точка_у_ук_спрашивает_и_заводит_по_да(
    клиент: Клиент, monkeypatch: pytest.MonkeyPatch
) -> None:
    заведено: list[str] = []
    monkeypatch.setattr(walk_start, "match_unit", lambda *_a, **_k: НЕ_ЗНАЮ)
    monkeypatch.setattr(walk_start, "upsert_unit", lambda имя, **_k: заведено.append(имя))

    спросили = клиент.старт()
    assert спросили.status_code == 409 and спросили.get_json()["need"] == "unit_new"
    assert get_state(АУДИТОР) is None and заведено == [], "без «да» ничего не заведено"

    ответ = клиент.старт(add_unit=True)

    assert ответ.status_code == 200
    assert заведено == ["Belgrade-1"]
    assert get_state(АУДИТОР).unit == "Belgrade-1"  # type: ignore[union-attr]


# ── идущая и сданная проверка ───────────────────────────────────────────


def test_идущая_проверка_без_подтверждения_не_заменяется(клиент: Клиент) -> None:
    start_inspection(АУДИТОР, unit="Podgorica-2", kind="planned", report_lang="en")
    прежняя = run_id(АУДИТОР)

    ответ = клиент.старт()

    assert ответ.status_code == 409 and ответ.get_json()["need"] == "replace"
    assert get_state(АУДИТОР).unit == "Podgorica-2"  # type: ignore[union-attr]
    assert run_id(АУДИТОР) == прежняя, "идущая проверка не тронута"


def test_идущая_заменяется_по_явному_подтверждению(клиент: Клиент) -> None:
    start_inspection(АУДИТОР, unit="Podgorica-2", kind="planned", report_lang="en")

    ответ = клиент.старт(replace=True)

    assert ответ.status_code == 200
    assert get_state(АУДИТОР).unit == "Belgrade-1"  # type: ignore[union-attr]


def test_сданная_заменяется_без_вопроса_и_признак_сдачи_уходит(клиент: Клиент) -> None:
    start_inspection(АУДИТОР, unit="Podgorica-2", kind="planned", report_lang="en")
    _сдать()
    assert handed_over(АУДИТОР)

    ответ = клиент.старт()

    assert ответ.status_code == 200, ответ.get_json()
    assert get_state(АУДИТОР).unit == "Belgrade-1"  # type: ignore[union-attr]
    assert not handed_over(АУДИТОР), "новая проверка не наследует «сдана» прежней"


def test_опции_называют_состояние_проверки(клиент: Клиент) -> None:
    нет = клиент.пост(op="options").get_json()["state"]
    start_inspection(АУДИТОР, unit="Podgorica-2", kind="planned", report_lang="en")
    идёт = клиент.пост(op="options").get_json()["state"]
    _сдать()
    сдана = клиент.пост(op="options").get_json()["state"]

    assert (нет, идёт, сдана) == ("none", "running", "sealed")


# ── память бота ─────────────────────────────────────────────────────────


def test_память_бота_о_прежней_проверке_не_достаётся_новой(клиент: Клиент) -> None:
    """Ядро D392: предложение и слово старой проверки не должны лечь в начатую из мини-аппа."""
    start_inspection(АУДИТОР, unit="Podgorica-2", kind="planned", report_lang="en")
    pending = PendingStore(run_id)
    store = MaterialStore(run_id)
    pending.propose(АУДИТОР, Proposal(file_ids=("f1",), source="comment", slot=1), at=10)
    store.queue(АУДИТОР).hold_comment(Comment(text="слово старой"))
    assert pending.proposal(АУДИТОР, at=10) is not None, "до старта предложение живо"

    ответ = клиент.старт(replace=True)

    assert ответ.status_code == 200
    assert pending.proposal(АУДИТОР, at=10) is None, "кнопка старой проверки выстрелила бы в новую"
    assert store.queue(АУДИТОР).held_comments() == ()
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


# ── подсказки ───────────────────────────────────────────────────────────


def test_подсказки_отдаются_списком(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk_start, "suggest_units", lambda typed, **_k: [f"{typed}grade-1"])

    ответ = клиент.пост(op="suggest", name="Bel")

    assert ответ.status_code == 200 and ответ.get_json() == {"suggestions": ["Belgrade-1"]}


# ── язык чек-листа запоминается (D440) ──────────────────────────────────


@pytest.fixture
def память(monkeypatch: pytest.MonkeyPatch) -> dict[int, str]:
    """Хранилище выбора в словаре — вместо базы (её тесты — `test_db_checklist_langs.py`)."""
    хранилище: dict[int, str] = {}
    monkeypatch.setattr(walk_start.checklist_langs, "chosen_checklist_lang", хранилище.get)
    monkeypatch.setattr(
        walk_start.checklist_langs,
        "choose_checklist_lang",
        lambda who, lang: хранилище.__setitem__(who, lang),
    )
    return хранилище


def test_после_старта_следующий_экран_предвыбирает_тот_же_язык(
    клиент: Клиент, память: dict[int, str]
) -> None:
    assert клиент.пост(op="options").get_json()["default_lang"] == "ru", "выбора нет — язык интерфейса"

    ответ = клиент.старт(speech_lang="en")

    assert ответ.status_code == 200, ответ.get_json()
    assert память == {АУДИТОР: "en"}
    assert клиент.пост(op="options").get_json()["default_lang"] == "en"


def test_отказанный_старт_язык_не_запоминает(клиент: Клиент, память: dict[int, str]) -> None:
    ответ = клиент.старт(speech_lang="en", unit="")

    assert ответ.status_code == 422
    assert память == {}


def test_запомненный_язык_вне_перечня_заменяется_умолчанием(
    клиент: Клиент, память: dict[int, str]
) -> None:
    память[АУДИТОР] = "sr"

    assert клиент.пост(op="options").get_json()["default_lang"] == "ru"


def test_база_молчит_предвыбор_по_умолчанию_старт_не_падает(
    клиент: Клиент, monkeypatch: pytest.MonkeyPatch
) -> None:
    def недоступна(*_a: Any) -> Any:
        raise AccessError("база недоступна")

    monkeypatch.setattr(walk_start.checklist_langs, "chosen_checklist_lang", недоступна)
    monkeypatch.setattr(walk_start.checklist_langs, "choose_checklist_lang", недоступна)

    опции = клиент.пост(op="options")
    ответ = клиент.старт(speech_lang="en")

    assert опции.status_code == 200 and опции.get_json()["default_lang"] == "ru"
    assert ответ.status_code == 200, "проверка началась, запись выбора — не повод её отказывать"
    assert get_state(АУДИТОР) is not None
