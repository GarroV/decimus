"""T333 (#310): письмо партнёру, зафиксированное человеком, перестаёт исчезать.

Проверяется главное свойство записи: она НЕ меняется от пересборки. Заготовку
движок собирает заново при каждом открытии экрана и от правки методики или
шаблона она поедет — а у партнёра на руках лежит один-единственный текст.
Запись, которая тихо поехала бы следом, отвечала бы на вопрос «что мы
отправили» правдоподобной неправдой, и заметить это было бы нечем.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import PushError  # noqa: E402
from src.db.letters import latest_letter, save_letter  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Белград-1"
ПИСЬМО = "Уважаемые коллеги!\n\nПо итогам проверки — 97,5%, оценка A.\n\nС уважением"
ПРАВЛЕНОЕ = "Уважаемые коллеги!\n\nПо итогам проверки — 97,5%, оценка A. Срок: 14 дней.\n"


def _проверка(chat_id: int) -> str:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    return push_inspection(chat_id)


def test_зафиксированное_письмо_читается_обратно_слово_в_слово(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(920_001)

    save_letter(inspection_id, body=ПИСЬМО, lang="ru", saved_by="director")
    прочитанное = latest_letter(inspection_id)

    assert прочитанное is not None
    # Слово в слово, вместе с переносами строк: письмо уезжает партнёру как
    # есть, и съеденный перенос — это уже другой документ.
    assert прочитанное.body == ПИСЬМО
    assert прочитанное.lang == "ru"
    assert прочитанное.saved_by == "director"


def test_у_непомеченной_проверки_письма_нет_а_не_пустая_строка(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(920_002)

    # «Никто не фиксировал» и «зафиксировали пустоту» — разные вещи, и экран
    # обязан их различать: в первом случае он показывает заготовку движка.
    assert latest_letter(inspection_id) is None


def test_новая_фиксация_не_затирает_прежнюю_а_становится_последней(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(920_003)

    save_letter(inspection_id, body=ПИСЬМО, lang="ru", saved_by="director")
    save_letter(inspection_id, body=ПРАВЛЕНОЕ, lang="ru", saved_by="director")

    последнее = latest_letter(inspection_id)
    assert последнее is not None
    assert последнее.body == ПРАВЛЕНОЕ

    # Прежнее письмо осталось: из истории нельзя вынуть отправленное — партнёр
    # получил именно его, и «мы передумали» этого не отменяет.
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute(
            "select body from partner_letters where inspection_id = %s order by created_at",
            (inspection_id,),
        )
        тела = [строка[0] for строка in cur.fetchall()]
    assert тела == [ПИСЬМО, ПРАВЛЕНОЕ]


def test_пустое_письмо_не_фиксируется_вовсе(domain_env: Path, db_env: str) -> None:
    inspection_id = _проверка(920_004)

    # Письмо из пробелов выглядит в истории как отправленное и обнаруживается
    # ровно тогда, когда кто-то спрашивает, что получил партнёр.
    for пустое in ("", "   ", "\n\t "):
        with pytest.raises(PushError):
            save_letter(inspection_id, body=пустое, lang="ru", saved_by="director")

    assert latest_letter(inspection_id) is None


def test_письмо_без_языка_или_без_автора_не_фиксируется(domain_env: Path, db_env: str) -> None:
    inspection_id = _проверка(920_005)

    # Язык — параметр, никогда не константа (`CLAUDE.md`): письмо без языка
    # через год не скажет, на каком языке его читал партнёр.
    with pytest.raises(PushError):
        save_letter(inspection_id, body=ПИСЬМО, lang="  ", saved_by="director")
    # «Кто зафиксировал» спрашивают через год, когда спросить уже некого.
    with pytest.raises(PushError):
        save_letter(inspection_id, body=ПИСЬМО, lang="ru", saved_by="")

    assert latest_letter(inspection_id) is None


def test_письмо_несуществующей_проверки_не_ложится_никуда(domain_env: Path, db_env: str) -> None:
    with pytest.raises(PushError):
        save_letter(
            "00000000-0000-0000-0000-000000000000",
            body=ПИСЬМО,
            lang="ru",
            saved_by="director",
        )
