"""T284: карта синонимов формулировок держится базой, а не только слоем (D119).

Соседний файл (`test_db_synonyms.py`) проверяет карту через `src.db.synonyms` —
то есть предполагает, что вызывающий уважает контракт слоя: не пишет туда, куда
слой не пускает. Здесь то же самое проверяется в обход слоя, сырым SQL под
ролью приложения: и права роли (миграция `0012_phrase_aliases.sql`, `grant
select, insert`), и ограничения схемы обязаны стоять сами по себе, потому что
слой доступа — не единственный, кто умеет писать SQL к этой таблице.

Формулировки в оснастке выдуманы целиком, как и в соседнем файле: связывание
проверяется кодом пункта, а не тем, что это за пункт (`tests/test_methodology_leak.py`
не пускает в публичный репозиторий ни одной настоящей формулировки).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import requires_db

# `psycopg` — зависимость блока `db`, а не всего проекта: без этой строки сбор
# этого файла падает целиком в окружении, где её ещё не поставили (см. тот же
# приём и объяснение в `tests/test_db_synonyms.py` и `tests/conftest.py`).
psycopg = pytest.importorskip("psycopg")

from src.db.synonyms import list_phrases, lookup_phrase, remember_phrase  # noqa: E402

pytestmark = requires_db

#: Выдуманный код пункта. Настоящие коды методики сюда не попадают намеренно:
#: связывание проверяется кодом как таковым, а не тем, какой он (см. образец).
ПУНКТ = "ZZ9.1"
ДРУГОЙ_ПУНКТ = "ZZ9.2"

_ВСТАВКА_СИНОНИМА = """
insert into phrase_aliases (tenant_code, lang, phrase_normalized, item_code, phrase, origin)
values (%(tenant)s, %(lang)s, %(key)s, %(code)s, %(phrase)s, %(origin)s)
"""


def _строки(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()  # type: ignore[no-any-return]


def _счёт(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> int:
    строки = _строки(dsn, sql, params)
    assert строки
    return int(строки[0][0])


def _выполнить(dsn: str, sql: str, params: dict[str, Any] | tuple[Any, ...] = ()) -> None:
    """Выполнить запись одним подключением.

    Своё, отдельное от `_строки` подключение на каждый вызов: если запись
    отказывает исключением, `with psycopg.connect(...)` откатывает и закрывает
    его сам — вызывающему не нужно помнить про `conn.rollback()`, чтобы
    следующий вызов (уже новым подключением) не наткнулся на прерванную
    транзакцию.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


# --- права роли приложения: только select и insert (миграция `0012`) --------


def test_роль_приложения_синоним_переписать_не_может(db_env: str) -> None:
    """UPDATE роли приложения не выдан вовсе — это свойство базы, а не слоя.

    Синоним, который уже работает, не должен переписываться ошибкой одного
    аудитора (см. комментарий у `grant` в миграции `0012`): отказ обязан быть
    по правам, а не молчаливой построчной политикой.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "update phrase_aliases set item_code = %s where phrase_normalized = %s",
            (ДРУГОЙ_ПУНКТ, "жёлтый зонт под потолком"),
        )

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")
    assert найден is not None
    assert найден.item_code == ПУНКТ, "синоним всё-таки переписан ролью приложения"


def test_роль_приложения_синоним_удалить_не_может(db_env: str) -> None:
    """DELETE роли приложения не выдан вовсе — по тому же доводу, что и UPDATE.

    Неверный синоним ролью приложения не убрать: правка и снятие — работа
    управляющей компании, у неё свои права (см. тот же комментарий в `0012`).
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "delete from phrase_aliases where phrase_normalized = %s",
            ("жёлтый зонт под потолком",),
        )

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")
    assert найден is not None, "синоним всё-таки удалён ролью приложения"


# --- ограничения схемы: то, что не пропускает слой, не пропускает и база ----
#
# Каждая проверка идёт прямым `insert` под ролью приложения, в обход
# `remember_phrase`, — чтобы показать, что отказ держит ограничение таблицы
# (миграция `0012`), а не только проверка в питоне.


def test_выдуманное_происхождение_не_проходит_мимо_слоя(db_env: str) -> None:
    """Список источников закрыт ограничением `phrase_aliases_origin_is_a_code`."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "ru",
                "key": "синий зонт в кладовке",
                "code": ПУНКТ,
                "phrase": "синий зонт в кладовке",
                "origin": "сорока",
            },
        )


def test_пустой_ключ_поиска_не_проходит_мимо_слоя(db_env: str) -> None:
    """Пустой ключ совпал бы с любой пустой строкой — заслон `phrase_aliases_key_not_blank`."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "ru",
                "key": "",
                "code": ПУНКТ,
                "phrase": "синий зонт в кладовке",
                "origin": "learned",
            },
        )


def test_пустой_код_пункта_не_проходит_мимо_слоя(db_env: str) -> None:
    """Синоним без кода — строка, которая никуда не ведёт: заслон `_item_code_not_blank`."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "ru",
                "key": "синий зонт в кладовке",
                "code": "   ",
                "phrase": "синий зонт в кладовке",
                "origin": "learned",
            },
        )


def test_язык_в_другом_написании_не_проходит_мимо_слоя(db_env: str) -> None:
    """«RU» и «ru» — один язык и в схеме тоже: заслон `phrase_aliases_lang_is_one_spelling`."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "RU",
                "key": "синий зонт в кладовке",
                "code": ПУНКТ,
                "phrase": "синий зонт в кладовке",
                "origin": "learned",
            },
        )


# --- арендатор: своя карта, а не общая на всех -------------------------------


def test_карта_одного_арендатора_не_отвечает_на_вопросы_другого(db_env: str) -> None:
    """Ключ поиска начинается с арендатора: партнёр не должен видеть чужую карту."""
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru", tenant="альфа")

    assert lookup_phrase("жёлтый зонт под потолком", lang="ru", tenant="бета") is None
    assert list_phrases(lang="ru", tenant="бета") == []
    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru", tenant="альфа")
    assert найден is not None
    assert найден.item_code == ПУНКТ


def test_синоним_несуществующего_арендатора_не_ложится_в_никуда(db_env: str) -> None:
    """Ссылка на `tenants (code)` не даёт синониму привязаться к партнёру, которого нет.

    Встречное утверждение — тем же тестом: `remember_phrase` заводит строку
    арендатора сама (`_INSERT_TENANT_SQL` в `src.db.synonyms`), а не полагается
    на то, что кто-то завёл её заранее.
    """
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "нет-такого",
                "lang": "ru",
                "key": "синий зонт в кладовке",
                "code": ПУНКТ,
                "phrase": "синий зонт в кладовке",
                "origin": "learned",
            },
        )

    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru", tenant="альфа")

    assert _счёт(db_env, "select count(*) from tenants where code = %s", ("альфа",)) == 1
