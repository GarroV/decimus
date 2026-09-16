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


# --- T292: правка карты держится правами и ограничениями, а не слоем ---------
#
# Миграция `0013` завела вторую роль на этой таблице (`dodo_audit_admin`) и
# шесть колонок правки. Доказательство то же, что выше по файлу для `0012`:
# свойства обязаны стоять сами по себе, в обход `retract_phrase` и
# `repoint_phrase` (соседний файл `test_db_synonyms_curation.py` проверяет их
# продуктовыми вызовами) — иначе слой доступа оказался бы единственным, кто
# уважает собственный контракт.
#
# Отказ RLS молчалив: строка просто не видна для записи, и запрос отчитывается
# «затронуто 0 строк», а не падает. Отказ по правам (`InsufficientPrivilege`),
# наоборот, падает исключением. Поэтому там, где отказа не ждём, проверяется и
# число затронутых строк, и содержимое строки ПОСЛЕ попытки.

from db_harness import admin_role_dsn  # noqa: E402


def _выполнить_считая(dsn: str, sql: str, params: dict[str, Any] | tuple[Any, ...] = ()) -> int:
    """Выполнить запись и вернуть число задетых строк.

    Отдельный от `_выполнить` помощник: в позитивном случае мало того, что
    запрос не упал, — важно и сколько строк он реально задел (тот же довод,
    что у молчаливого отказа построчной политики).
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


# --- роль приложения: снятие ей тоже недоступно ------------------------------


def test_роль_приложения_снять_синоним_не_может(db_env: str) -> None:
    """Снятие — тоже запись, а UPDATE роли приложения не выдан вовсе (`0012`).

    Отказ обязан быть по правам, а не молчаливой построчной политикой: строка
    обязана остаться живой.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "update phrase_aliases set retracted_at = now(), retraction_reason = %s "
            "where phrase_normalized = %s",
            ("самовольно", "жёлтый зонт под потолком"),
        )

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")
    assert найден is not None
    assert найден.retracted_at is None, "синоним всё-таки снят ролью приложения"


def test_роль_приложения_снятую_строку_вернуть_не_может(db_env: str) -> None:
    """Тот же отказ по правам — на уже снятой строке, не только на живой.

    UPDATE не выдан вовсе, значит и возврат из снятия ролью приложения
    невозможен: разбираться в состоянии строки ей нечем в принципе.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)
    _выполнить(
        admin,
        "update phrase_aliases set retracted_at = now(), retraction_reason = %s "
        "where phrase_normalized = %s",
        ("причина снятия", "жёлтый зонт под потолком"),
    )

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            db_env,
            "update phrase_aliases set retracted_at = null, retraction_reason = null "
            "where phrase_normalized = %s",
            ("жёлтый зонт под потолком",),
        )

    состояние = _строки(
        admin,
        "select retracted_at is not null, retraction_reason from phrase_aliases "
        "where phrase_normalized = %s",
        ("жёлтый зонт под потолком",),
    )
    assert состояние == [(True, "причина снятия")], "снятая строка всё-таки вернулась в работу"


def test_роль_приложения_вторую_строку_на_снятый_ключ_не_заводит(db_env: str) -> None:
    """Первичный ключ — заслон от повторного выучивания, а не дисциплина вызовов.

    Снятая строка держит свой ключ: `insert` на тот же (арендатор, язык,
    ключ) обязан упасть нарушением уникальности, даже если строка уже неживая.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)
    _выполнить(
        admin,
        "update phrase_aliases set retracted_at = now(), retraction_reason = %s "
        "where phrase_normalized = %s",
        ("причина снятия", "жёлтый зонт под потолком"),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        _выполнить(
            db_env,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "ru",
                "key": "жёлтый зонт под потолком",
                "code": ДРУГОЙ_ПУНКТ,
                "phrase": "жёлтый зонт под потолком",
                "origin": "learned",
            },
        )

    строки = _строки(
        admin,
        "select item_code, retracted_at is not null from phrase_aliases "
        "where phrase_normalized = %s",
        ("жёлтый зонт под потолком",),
    )
    assert строки == [(ПУНКТ, True)], "в таблице не одна снятая строка с прежним кодом"


# --- роль администратора: правит шесть колонок, ни одной больше и не строки --


@pytest.mark.parametrize(
    ("колонка", "новое_значение"),
    [
        ("phrase", "'other-phrase'"),
        ("lang", "'en'"),
        ("phrase_normalized", "'other-key'"),
        ("tenant_code", "'other-tenant'"),
        ("origin", "'manual'"),
        ("created_at", "now()"),
    ],
)
def test_администратор_чужие_колонки_переписать_не_может(
    db_env: str, колонка: str, новое_значение: str
) -> None:
    """Право администратора — шесть колонок правки, а не вся строка целиком.

    Сказанное человеком, язык, ключ поиска, арендатор, происхождение и время
    заведения обязаны остаться такими, какими их завело приложение.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    запрос = (
        f"update phrase_aliases set {колонка} = {новое_значение} "  # noqa: S608
        "where phrase_normalized = %s"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(admin, запрос, ("жёлтый зонт под потолком",))

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")
    assert найден is not None
    assert найден.phrase == "жёлтый зонт под потолком"
    assert найден.lang == "ru"
    assert найден.key == "жёлтый зонт под потолком"
    assert найден.origin == "learned"


def test_администратор_снимает_и_переправляет_разрешёнными_колонками(db_env: str) -> None:
    """Позитивный случай: без него предыдущий тест зелен по неверной причине.

    Один `update` на все шесть разрешённых колонок обязан пройти и вернуть
    ровно то, что писали, — иначе непонятно, отказ выше держит заслон или
    роли вообще нечем писать.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    затронуто = _выполнить_считая(
        admin,
        "update phrase_aliases set "
        "item_code = %(code)s, retracted_at = now(), retraction_reason = %(retraction)s, "
        "corrected_at = now(), correction_reason = %(correction)s, "
        "previous_item_code = %(previous)s "
        "where phrase_normalized = %(key)s",
        {
            "code": ДРУГОЙ_ПУНКТ,
            "retraction": "увело не туда",
            "correction": "переправлено на верный пункт",
            "previous": ПУНКТ,
            "key": "жёлтый зонт под потолком",
        },
    )

    assert затронуто == 1
    строка = _строки(
        admin,
        "select item_code, retracted_at is not null, retraction_reason, "
        "corrected_at is not null, correction_reason, previous_item_code "
        "from phrase_aliases where phrase_normalized = %s",
        ("жёлтый зонт под потолком",),
    )
    assert строка == [
        (ДРУГОЙ_ПУНКТ, True, "увело не туда", True, "переправлено на верный пункт", ПУНКТ)
    ]


def test_администратор_не_вставляет_и_не_удаляет_строки(db_env: str) -> None:
    """Заводит синонимы приложение, а удалять строки в этой базе не умеет никто.

    Снятие — пометка, поэтому ни `insert`, ни `delete` администратору не
    нужны и не выданы (`0013`).
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            admin,
            _ВСТАВКА_СИНОНИМА,
            {
                "tenant": "default",
                "lang": "ru",
                "key": "синий зонт в кладовке",
                "code": ДРУГОЙ_ПУНКТ,
                "phrase": "синий зонт в кладовке",
                "origin": "manual",
            },
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _выполнить(
            admin,
            "delete from phrase_aliases where phrase_normalized = %s",
            ("жёлтый зонт под потолком",),
        )

    assert _счёт(admin, "select count(*) from phrase_aliases") == 1


# --- ограничения схемы: то, что не пропускает база, не пропускает никто -----


def test_снятие_требует_отметку_и_причину_вместе(db_env: str) -> None:
    """Обе половины пометки снятия обязаны появляться только вместе.

    `phrase_aliases_retraction_has_reason` — связь двух колонок: «когда
    снята» без «почему» и наоборот — оба одинаково не состояние, а
    недописанный запрос.
    """
    admin = admin_role_dsn(db_env)

    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin,
            "update phrase_aliases set retracted_at = now() where phrase_normalized = %s",
            ("жёлтый зонт под потолком",),
        )

    remember_phrase("синий зонт в кладовке", item_code=ПУНКТ, lang="ru")
    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin,
            "update phrase_aliases set retraction_reason = %s where phrase_normalized = %s",
            ("причина без отметки", "синий зонт в кладовке"),
        )


def test_причина_снятия_из_одних_пробелов_не_проходит(db_env: str) -> None:
    """Пустая причина выглядела бы названной, которой не прочитать.

    `phrase_aliases_retraction_reason_is_not_empty` не путает «есть текст» с
    «есть непустой текст».
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin,
            "update phrase_aliases set retracted_at = now(), retraction_reason = %s "
            "where phrase_normalized = %s",
            ("   ", "жёлтый зонт под потолком"),
        )


def test_след_правки_заполняется_целиком_или_никак(db_env: str) -> None:
    """«Исправлено, но неизвестно откуда» — не состояние, а недописанный запрос.

    `phrase_aliases_correction_is_whole` не пускает частичный след правки:
    все три колонки или ни одной.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin,
            "update phrase_aliases set corrected_at = now(), correction_reason = %s "
            "where phrase_normalized = %s",
            ("переправлено", "жёлтый зонт под потолком"),
        )


def test_правка_на_тот_же_код_не_проходит(db_env: str) -> None:
    """«Правка», ничего не исправившая, не записывается правкой.

    `phrase_aliases_correction_changed_something` не пускает
    `previous_item_code`, равный текущему коду пункта.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    admin = admin_role_dsn(db_env)

    with pytest.raises(psycopg.errors.CheckViolation):
        _выполнить(
            admin,
            "update phrase_aliases set corrected_at = now(), correction_reason = %s, "
            "previous_item_code = %s where phrase_normalized = %s",
            ("переправлено", ПУНКТ, "жёлтый зонт под потолком"),
        )
