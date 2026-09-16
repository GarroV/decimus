"""T284: карта синонимов формулировок (`src/db/synonyms.py`).

Решение D119: если аудитор сказал иначе или с ошибками и ПРЯМОГО совпадения с
методикой не нашлось, разобранная формулировка складывается в базу как синоним
пункта и работает при следующем поиске; прямое совпадение синонима второй
строки не заводит. Здесь проверяется место, где эти синонимы живут: схема,
ключ поиска и слой доступа. Кто и когда кладёт синоним — работа потребителя
(T285, блок `binding`), и она здесь не проверяется.

Формулировки в оснастке выдуманы целиком. Методика управляющей компании в
репозиторий не попадает ни строкой, ни примером (`tests/test_methodology_leak.py`,
репозиторий публичный): тест про синонимы совершенно не нуждается в настоящих
словах, чтобы проверять связывание кодами.
"""

from __future__ import annotations

import pytest
from conftest import requires_db

# `psycopg` — зависимость блока `db`, а не всего проекта: без этой строки сбор
# этого файла падает целиком в окружении, где её ещё не поставили (см.
# аналогичный приём и объяснение в `tests/conftest.py`, раздел про `db`).
psycopg = pytest.importorskip("psycopg")

from src.db.errors import SynonymError  # noqa: E402
from src.db.synonyms import (  # noqa: E402
    ALREADY_KNOWN,
    CONFLICT,
    LEARNED,
    MANUAL,
    REMEMBERED,
    list_phrases,
    lookup_phrase,
    normalize_phrase,
    remember_phrase,
)

pytestmark = requires_db

#: Выдуманные коды пунктов. Настоящие коды методики сюда не попадают намеренно:
#: связывание проверяется кодом как таковым, а не тем, какой он.
ПУНКТ = "ZZ9.1"
ДРУГОЙ_ПУНКТ = "ZZ9.2"


def _строки(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_синоним_заводится_и_находится(db_env: str) -> None:
    """Базовый цикл. Без него остальное обсуждать нечего: положили — нашли."""
    записано = remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    assert записано.outcome == REMEMBERED
    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")

    assert найден is not None
    assert найден.item_code == ПУНКТ
    assert найден.phrase == "жёлтый зонт под потолком"
    assert найден.origin == LEARNED
    assert найден.created_at is not None


def test_написание_синонима_не_важно(db_env: str) -> None:
    """Суть задачи: аудитор говорит как говорится, а не как записано в базе.

    Регистр, лишние пробелы и точка в конце — то, чем одна и та же фраза
    отличается от себя же при вводе с телефона. Опечатки этим не лечатся: их
    разбирает потребитель (T285), сюда формулировка приходит уже разобранной.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    найден = lookup_phrase("  Жёлтый   зонт  под Потолком.  ", lang="ru")

    assert найден is not None
    assert найден.item_code == ПУНКТ


def test_прямое_совпадение_синонима_не_заводит_вторую_строку(db_env: str) -> None:
    """Решение D119: уже известный синоним второй строки в карте не заводит.

    Считаются строки в базе, а не возвращённое значение: слой мог бы честно
    ответить «уже знаю» и всё равно написать вторую строку.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    повтор = remember_phrase("Жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    assert повтор.outcome == ALREADY_KNOWN
    assert повтор.alias.item_code == ПУНКТ
    assert _строки(db_env, "select count(*) from phrase_aliases") == [(1,)]


def test_синоним_другого_пункта_не_переписывает_заведённый(db_env: str) -> None:
    """Разночтение называется вслух, а не решается втихую.

    Переписать — значит дать одной ошибке аудитора перенаправить формулировку,
    которая уже работает. Промолчать — значит сказать потребителю «запомнил»,
    ничего не запомнив. Поэтому третий исход: строка остаётся прежней, а
    вызывающий узнаёт, к какому пункту она ведёт.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")

    спор = remember_phrase("жёлтый зонт под потолком", item_code=ДРУГОЙ_ПУНКТ, lang="ru")

    assert спор.outcome == CONFLICT
    assert спор.alias.item_code == ПУНКТ
    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")
    assert найден is not None and найден.item_code == ПУНКТ
    assert _строки(db_env, "select count(*) from phrase_aliases") == [(1,)]


def test_язык_у_синонима_свой(db_env: str) -> None:
    """Язык — параметр, а не константа (конституция, принцип 4).

    Одна и та же строка на двух языках — два разных синонима, и найтись
    английский по русскому запросу не должен: иначе карта начнёт срабатывать
    на совпадениях написания между языками сети.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    remember_phrase("yellow umbrella by the ceiling", item_code=ДРУГОЙ_ПУНКТ, lang="en")

    assert lookup_phrase("yellow umbrella by the ceiling", lang="ru") is None
    найден = lookup_phrase("yellow umbrella by the ceiling", lang="en")
    assert найден is not None and найден.item_code == ДРУГОЙ_ПУНКТ


def test_язык_пишется_одним_написанием(db_env: str) -> None:
    """«RU» и «ru» — один язык. Иначе карта раздвоится на регистре кода языка."""
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="RU")

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")

    assert найден is not None
    assert найден.lang == "ru"


def test_пустая_формулировка_в_карту_не_ложится(db_env: str) -> None:
    """Пустой ключ совпал бы с любой пустой строкой и увёл бы к случайному пункту."""
    with pytest.raises(SynonymError, match="пустая"):
        remember_phrase("   ", item_code=ПУНКТ, lang="ru")

    assert lookup_phrase("   ", lang="ru") is None


def test_пункт_без_кода_в_карту_не_ложится(db_env: str) -> None:
    """Синоним без пункта — строка, которая никуда не ведёт, то есть мусор в карте."""
    with pytest.raises(SynonymError, match="кода пункта"):
        remember_phrase("жёлтый зонт под потолком", item_code="  ", lang="ru")


def test_происхождение_записи_хранится_кодом(db_env: str) -> None:
    """Зачем оно: выученное машиной и заведённое человеком правятся по-разному.

    Происхождение — код, а не формулировка (конституция, принцип 5): по нему
    управляющая компания однажды отберёт накопленное автоматически, и перевод
    или правка слова этот отбор не сломает.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru", origin=MANUAL)

    найден = lookup_phrase("жёлтый зонт под потолком", lang="ru")

    assert найден is not None
    assert найден.origin == MANUAL


def test_выдуманное_происхождение_не_принимается(db_env: str) -> None:
    """Список источников закрыт: неизвестный код означает потерянный отбор."""
    with pytest.raises(SynonymError, match="Неизвестное происхождение"):
        remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru", origin="сорока")


def test_карта_отдаётся_целиком_и_с_ключом_поиска(db_env: str) -> None:
    """Потребителю нужна не только выборка по одной фразе, но и карта разом.

    `src.recognize` не имеет права импортировать `src.db` (слои в
    `pyproject.toml`), поэтому сопоставлением занимается ярус выше — и он берёт
    карту одним запросом, вместе с ключом, по которому она ищется.
    """
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    remember_phrase("Синий Зонт  в кладовке", item_code=ДРУГОЙ_ПУНКТ, lang="ru")
    remember_phrase("yellow umbrella by the ceiling", item_code=ПУНКТ, lang="en")

    русские = list_phrases(lang="ru")

    assert [(a.key, a.item_code) for a in русские] == [
        ("жёлтый зонт под потолком", ПУНКТ),
        ("синий зонт в кладовке", ДРУГОЙ_ПУНКТ),
    ]
    assert [a.phrase for a in русские] == ["жёлтый зонт под потолком", "Синий Зонт  в кладовке"]


def test_карта_отбирается_по_пункту(db_env: str) -> None:
    """Вопрос «как ещё называют этот пункт» — тот же, что задаст управляющая компания."""
    remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")
    remember_phrase("синий зонт в кладовке", item_code=ДРУГОЙ_ПУНКТ, lang="ru")

    отобранные = list_phrases(item_code=ПУНКТ)

    assert [a.phrase for a in отобранные] == ["жёлтый зонт под потолком"]


def test_карта_не_на_связи_отказом_а_не_пустотой(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Синонимов нет» и «карта недоступна» — разные ответы.

    Отданная пустота означала бы, что при потерянной базе система молча
    перестаёт узнавать выученное и переспрашивает аудитора заново — то самое,
    от чего уходит D119.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://nouser@127.0.0.1:1/nodb?connect_timeout=2")

    with pytest.raises(SynonymError):
        lookup_phrase("жёлтый зонт под потолком", lang="ru")
    with pytest.raises(SynonymError):
        remember_phrase("жёлтый зонт под потолком", item_code=ПУНКТ, lang="ru")


def test_ключ_поиска_считается_одним_правилом() -> None:
    """Правило нормализации — часть контракта, а не внутренняя мелочь.

    Разойдись запись с поиском хоть на одном знаке — карта перестанет работать
    молча и только на части написаний.
    """
    assert normalize_phrase("  Жёлтый   зонт  под Потолком.  ") == "жёлтый зонт под потолком"
    assert normalize_phrase("ЖЁЛТЫЙ ЗОНТ!") == "жёлтый зонт"
    assert normalize_phrase("   ") == ""
